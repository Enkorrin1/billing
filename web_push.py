"""Web Push без сторонних обёрток: VAPID (RFC 8292) и шифрование aes128gcm (RFC 8291).

Ключ VAPID берётся из VAPID_PRIVATE_KEY (base64url, 32 байта) или создаётся один раз
и хранится рядом с базой в vapid_private.pem. Отправка идёт в фоновом потоке,
чтобы запросы к push-сервисам не задерживали ответы API.
"""
import base64
import json
import os
import queue
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _hkdf(salt: bytes, info: bytes, length: int, key_material: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key_material)


def _public_bytes(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt_payload(payload: bytes, p256dh: str, auth: str) -> bytes:
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_public = _public_bytes(server_key)
    shared = server_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, b"WebPush: info\x00" + ua_public + server_public, 32, shared)
    salt = os.urandom(16)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + (4096).to_bytes(4, "big") + bytes([len(server_public)]) + server_public
    return header + ciphertext


class WebPush:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.subject = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
        self._key = None
        self._queue: queue.Queue = queue.Queue()
        self._thread = None
        self._lock = threading.Lock()

    @property
    def private_key(self):
        if self._key is None:
            raw = os.getenv("VAPID_PRIVATE_KEY")
            if raw:
                self._key = ec.derive_private_key(int.from_bytes(b64url_decode(raw), "big"), ec.SECP256R1())
            else:
                path = self.db_path.parent / "vapid_private.pem"
                if path.exists():
                    self._key = serialization.load_pem_private_key(path.read_bytes(), password=None)
                else:
                    self._key = ec.generate_private_key(ec.SECP256R1())
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        return self._key

    @property
    def public_key(self) -> str:
        return b64url(_public_bytes(self.private_key))

    def _vapid_header(self, endpoint: str) -> str:
        parts = urlsplit(endpoint)
        claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": self.subject}
        signing_input = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode()) + "." + b64url(json.dumps(claims).encode())
        r, s = decode_dss_signature(self.private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        token = signing_input + "." + b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={token}, k={self.public_key}"

    def send(self, subscription: dict, payload: dict) -> int:
        body = encrypt_payload(json.dumps(payload, ensure_ascii=False).encode(), subscription["p256dh"], subscription["auth"])
        response = httpx.post(subscription["endpoint"], content=body, timeout=10, headers={
            "Authorization": self._vapid_header(subscription["endpoint"]),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": "86400",
            "Urgency": "normal",
        })
        return response.status_code

    def enqueue(self, user_id: int, payload: dict):
        if user_id is None:
            return
        self._queue.put((user_id, payload))
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._worker, name="web-push", daemon=True)
                self._thread.start()

    def _worker(self):
        while True:
            try:
                user_id, payload = self._queue.get(timeout=30)
            except queue.Empty:
                return
            try:
                self._deliver(user_id, payload)
            except Exception:
                pass

    def _deliver(self, user_id: int, payload: dict):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT id,endpoint,p256dh,auth FROM push_subscriptions WHERE user_id=?", (user_id,)).fetchall()
            for row in rows:
                try:
                    status = self.send(dict(row), payload)
                except httpx.HTTPError:
                    continue
                if status in (404, 410):
                    conn.execute("DELETE FROM push_subscriptions WHERE id=?", (row["id"],))
            conn.commit()
        finally:
            conn.close()
