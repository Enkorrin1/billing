import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi.testclient import TestClient

temp = tempfile.TemporaryDirectory()
os.environ.setdefault("APP_DB", str(Path(temp.name) / "test.db"))
import app as service
from web_push import WebPush, b64url, b64url_decode, encrypt_payload


def hkdf(salt, info, length, ikm):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def browser_decrypt(body, ua_key, auth_secret):
    """Расшифровка на стороне браузера по RFC 8291 — проверяет, что сервер шифрует правильно."""
    salt, record_size, key_len = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    server_public = body[21:21 + key_len]
    ciphertext = body[21 + key_len:]
    ua_public = ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_public))
    ikm = hkdf(auth_secret, b"WebPush: info\x00" + ua_public + server_public, 32, shared)
    cek = hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert record_size == 4096 and plain.endswith(b"\x02")
    return plain[:-1]


class WebPushCrypto(unittest.TestCase):
    def test_payload_decrypts_in_browser(self):
        ua_key = ec.generate_private_key(ec.SECP256R1())
        auth_secret = os.urandom(16)
        p256dh = b64url(ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        body = encrypt_payload("Новая заявка №7".encode(), p256dh, b64url(auth_secret))
        self.assertEqual(browser_decrypt(body, ua_key, auth_secret).decode(), "Новая заявка №7")

    def test_vapid_token_is_signed_by_published_key(self):
        sender = WebPush(Path(temp.name) / "vapid" / "push.db")
        header = sender._vapid_header("https://fcm.googleapis.com/fcm/send/abc")
        token = header.split("t=")[1].split(",")[0]
        key = header.split("k=")[1]
        head, claims, signature = token.split(".")
        self.assertEqual(json.loads(b64url_decode(claims))["aud"], "https://fcm.googleapis.com")
        raw = b64url_decode(signature)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(key))
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
        self.assertTrue((Path(temp.name) / "vapid" / "vapid_private.pem").exists())
        self.assertEqual(WebPush(Path(temp.name) / "vapid" / "push.db").public_key, key)


class PushRoutes(unittest.TestCase):
    def setUp(self):
        with service.db() as conn:
            conn.execute("DELETE FROM push_subscriptions")
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM users WHERE email='push@example.com'")
        self.client = TestClient(service.app)
        self.assertEqual(self.client.post("/api/register", json={"name": "Push", "email": "push@example.com", "password": "password123"}).status_code, 200)
        ua_key = ec.generate_private_key(ec.SECP256R1())
        self.keys = {
            "p256dh": b64url(ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            "auth": b64url(os.urandom(16)),
        }

    def test_subscribe_validates_and_unsubscribes(self):
        self.assertEqual(TestClient(service.app).get("/api/push/key").status_code, 401)
        self.assertEqual(len(b64url_decode(self.client.get("/api/push/key").json()["public_key"])), 65)
        bad = self.client.post("/api/push/subscribe", json={"endpoint": "https://evil.example.com/hook", "keys": self.keys})
        self.assertEqual(bad.status_code, 422)
        endpoint = "https://fcm.googleapis.com/fcm/send/device-1"
        self.assertEqual(self.client.post("/api/push/subscribe", json={"endpoint": endpoint, "keys": self.keys}).status_code, 200)
        self.assertEqual(self.client.post("/api/push/subscribe", json={"endpoint": endpoint, "keys": self.keys}).status_code, 200)
        with mock.patch.object(service.web_push, "enqueue") as enqueue:
            self.assertEqual(self.client.post("/api/push/test").json()["devices"], 1)
            enqueue.assert_called_once()
        self.assertEqual(self.client.post("/api/push/unsubscribe", json={"endpoint": endpoint}).status_code, 200)
        self.assertEqual(self.client.post("/api/push/test").json()["devices"], 0)

    def test_expired_subscription_is_removed(self):
        endpoint = "https://updates.push.services.mozilla.com/wpush/v2/abc"
        self.client.post("/api/push/subscribe", json={"endpoint": endpoint, "keys": self.keys})
        user_id = self.client.get("/api/me").json()["id"]
        with mock.patch.object(service.web_push, "send", return_value=410) as send:
            service.web_push._deliver(user_id, {"title": "t", "body": "b", "url": "/"})
            send.assert_called_once()
        with service.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
