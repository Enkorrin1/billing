"""Durable, bounded, and SSRF-safe delivery of configured outbound webhooks."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit


MAX_PAYLOAD_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 2_000
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RETRY_BASE_SECONDS = 15
DEFAULT_RETRY_MAX_SECONDS = 3_600
DEFAULT_LEASE_SECONDS = 30
DEFAULT_BATCH_LIMIT = 2
MAX_DNS_RESULTS = 32
DEFAULT_DNS_TIMEOUT_SECONDS = 3
_DNS_RESOLVER_SLOTS = threading.BoundedSemaphore(4)
_NAT64_GLOBAL = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


class DeliveryRejected(ValueError):
    """A destination or response is unsafe or permanently invalid."""


def _timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


def _int_env(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, value))


def max_attempts() -> int:
    return _int_env("WEBHOOK_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 1, 32)


def _normalise_host(host: str) -> str:
    candidate = host.rstrip(".").lower()
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        try:
            ascii_host = candidate.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise DeliveryRejected("Invalid webhook host name") from exc
        if not ascii_host or len(ascii_host) > 253:
            raise DeliveryRejected("Invalid webhook host name")
        labels = ascii_host.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
            for label in labels
        ):
            raise DeliveryRejected("Invalid webhook host name")
        return ascii_host


def _is_public_global(address) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_public_global(ip.ipv4_mapped)
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
        if ip in _NAT64_GLOBAL or ip in _NAT64_LOCAL:
            return False
    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_unspecified
        and not ip.is_reserved
    )


def _allowed_hosts(value: str | None = None) -> set[str]:
    raw = os.environ.get("WEBHOOK_ALLOWED_HOSTS", "") if value is None else value
    result = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            result.add(_normalise_host(item))
    return result


def validate_url(url: str, allowed_hosts: set[str] | None = None) -> dict:
    """Validate URL syntax and policy without resolving or contacting its host."""
    if not isinstance(url, str) or not url or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise DeliveryRejected("Webhook URL is empty or contains control characters")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise DeliveryRejected("Invalid webhook URL") from exc
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise DeliveryRejected("Webhook URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise DeliveryRejected("Webhook URL must not contain credentials")
    if parsed.fragment:
        raise DeliveryRejected("Webhook URL must not contain a fragment")
    if not parsed.hostname:
        raise DeliveryRejected("Webhook URL must contain a host")

    host = _normalise_host(parsed.hostname)
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise DeliveryRejected("Invalid webhook port")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _is_public_global(literal):
        raise DeliveryRejected("Webhook destination must be a public global address")

    allowed = _allowed_hosts() if allowed_hosts is None else {_normalise_host(item) for item in allowed_hosts}
    if allowed and host not in allowed:
        raise DeliveryRejected("Webhook host is not in WEBHOOK_ALLOWED_HOSTS")

    host_for_header = f"[{host}]" if ":" in host else host
    explicit_port = parsed.port
    host_header = f"{host_for_header}:{port}" if explicit_port is not None else host_for_header
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/?%:@!$&'()*+,;=-._~")
    request_target = path + (f"?{query}" if query else "")
    return {
        "url": url,
        "scheme": scheme,
        "host": host,
        "port": port,
        "host_header": host_header,
        "request_target": request_target,
    }


def _resolve_public_addresses(host: str, port: int, resolver=None) -> list[tuple[int, tuple]]:
    resolver = resolver or socket.getaddrinfo
    resolved = threading.Event()
    result = {}

    def resolve():
        try:
            result["records"] = resolver(host, port, type=socket.SOCK_STREAM)
        except Exception as exc:
            result["error"] = exc
        finally:
            resolved.set()
            _DNS_RESOLVER_SLOTS.release()

    dns_timeout = _int_env("WEBHOOK_DNS_TIMEOUT_SECONDS", DEFAULT_DNS_TIMEOUT_SECONDS, 1, 10)
    if not _DNS_RESOLVER_SLOTS.acquire(timeout=dns_timeout):
        raise OSError("Webhook DNS resolver is busy")
    try:
        threading.Thread(target=resolve, name="webhook-dns", daemon=True).start()
    except Exception as exc:
        _DNS_RESOLVER_SLOTS.release()
        raise OSError("Webhook DNS resolver could not start") from exc
    if not resolved.wait(dns_timeout):
        raise OSError("Webhook DNS resolution timed out")
    if "error" in result:
        raise result["error"]
    records = result.get("records", [])
    if len(records) > MAX_DNS_RESULTS:
        raise DeliveryRejected("Webhook DNS returned too many addresses")
    addresses = []
    seen = set()
    for family, socktype, proto, _canonname, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6) or socktype not in (socket.SOCK_STREAM, 0):
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except (ValueError, IndexError, TypeError) as exc:
            raise DeliveryRejected("DNS returned an invalid webhook address") from exc
        if not _is_public_global(ip):
            raise DeliveryRejected("Webhook DNS resolved to a non-public address")
        key = (family, tuple(sockaddr))
        if key not in seen:
            seen.add(key)
            addresses.append((family, tuple(sockaddr)))
    if not addresses:
        raise OSError("Webhook host did not resolve to a usable address")
    return addresses


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, family, sockaddr, timeout):
        super().__init__(host=host, port=port, timeout=timeout)
        self._family = family
        self._sockaddr = sockaddr

    def connect(self):
        sock = socket.socket(self._family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self._sockaddr)
        except Exception:
            sock.close()
            raise
        self.sock = sock


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, family, sockaddr, timeout):
        super().__init__(host=host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._family = family
        self._sockaddr = sockaddr

    def connect(self):
        raw_sock = socket.socket(self._family, socket.SOCK_STREAM)
        try:
            raw_sock.settimeout(self.timeout)
            raw_sock.connect(self._sockaddr)
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)
        except Exception:
            raw_sock.close()
            raise


def _connection_factory(secure, host, port, family, sockaddr, timeout):
    connection_type = _PinnedHTTPSConnection if secure else _PinnedHTTPConnection
    return connection_type(host, port, family, sockaddr, timeout)


def _result(status_code=None, response_body="", duration_ms=0, error=None, retryable=False):
    return {
        "status_code": status_code,
        "response_body": (response_body or "")[:MAX_RESPONSE_BYTES],
        "duration_ms": max(0, int(duration_ms)),
        "error": (str(error)[:MAX_RESPONSE_BYTES] if error else None),
        "retryable": bool(retryable),
    }


def send_payload(
    url: str,
    secret: str,
    event: str,
    payload,
    delivery_id: str | None,
    *,
    resolver=None,
    connection_factory=None,
    timeout_seconds: int | None = None,
    allowed_hosts: set[str] | None = None,
    signature: str | None = None,
    address_offset: int = 0,
):
    """POST a signed payload to one pinned public IP; redirects and proxies are never used."""
    started = time.monotonic()
    delivery_id = delivery_id or str(uuid.uuid4())
    try:
        target = validate_url(url, allowed_hosts)
    except DeliveryRejected as exc:
        return _result(error=exc, duration_ms=(time.monotonic() - started) * 1000)

    try:
        addresses = _resolve_public_addresses(target["host"], target["port"], resolver)
    except DeliveryRejected as exc:
        return _result(error=exc, duration_ms=(time.monotonic() - started) * 1000)
    except OSError as exc:
        return _result(error=exc, retryable=True, duration_ms=(time.monotonic() - started) * 1000)

    payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        return _result(error="Webhook payload exceeds the configured size limit",
                       duration_ms=(time.monotonic() - started) * 1000)
    if signature is None:
        signature = hmac.new((secret or "").encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    elif not re.fullmatch(r"[0-9a-f]{64}", signature):
        return _result(error="Webhook signature snapshot is invalid", duration_ms=(time.monotonic() - started) * 1000)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Signature-SHA256": signature,
        "X-Desk-Event": event,
        "X-Desk-Delivery-ID": delivery_id,
        "User-Agent": "Desk-Webhook/1.0",
        "Host": target["host_header"],
        "Connection": "close",
    }
    timeout_seconds = timeout_seconds or _int_env("WEBHOOK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, 1, 30)
    connection_factory = connection_factory or _connection_factory

    family, sockaddr = addresses[int(address_offset) % len(addresses)]
    connection = connection_factory(target["scheme"] == "https", target["host"], target["port"],
                                    family, sockaddr, timeout_seconds)
    try:
        connection.connect()
    except OSError as exc:
        connection.close()
        return _result(error=exc, retryable=not isinstance(exc, ssl.SSLCertVerificationError),
                       duration_ms=(time.monotonic() - started) * 1000)

    try:
        connection.request("POST", target["request_target"], body=payload_bytes, headers=headers)
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")[:MAX_RESPONSE_BYTES]
        status_code = int(response.status)
        if 200 <= status_code < 300:
            return _result(status_code, body, (time.monotonic() - started) * 1000)
        if 300 <= status_code < 400:
            return _result(status_code, body, (time.monotonic() - started) * 1000,
                           f"HTTP {status_code}: redirects are not followed")
        retryable = status_code in (408, 425, 429) or status_code >= 500
        return _result(status_code, body, (time.monotonic() - started) * 1000,
                       f"HTTP {status_code}", retryable)
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        return _result(error=exc, retryable=not isinstance(exc, ssl.SSLCertVerificationError),
                       duration_ms=(time.monotonic() - started) * 1000)
    finally:
        connection.close()


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS webhook_outbox (
            delivery_id TEXT PRIMARY KEY,
            webhook_id INTEGER NOT NULL,
            target_url TEXT NOT NULL,
            signature TEXT NOT NULL,
            event TEXT NOT NULL,
            payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending','sending','retry','delivered','failed','cancelled')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL,
            lease_until REAL,
            claim_token TEXT,
            status_code INTEGER,
            response_body TEXT NOT NULL DEFAULT '',
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            delivered_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_outbox_due
            ON webhook_outbox(state, available_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_webhook_outbox_endpoint
            ON webhook_outbox(webhook_id, created_at);
        CREATE TABLE IF NOT EXISTS webhook_delivery_attempts (
            id INTEGER PRIMARY KEY,
            delivery_id TEXT NOT NULL REFERENCES webhook_outbox(delivery_id) ON DELETE CASCADE,
            attempt INTEGER NOT NULL,
            state TEXT NOT NULL,
            status_code INTEGER,
            response_body TEXT NOT NULL DEFAULT '',
            error TEXT,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(delivery_id, attempt)
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_delivery_attempts
            ON webhook_delivery_attempts(delivery_id, attempt);
    """)


def _subscribed_events(raw_events: str) -> set[str]:
    try:
        parsed = json.loads(raw_events) if raw_events.startswith("[") else [item.strip() for item in raw_events.split(",")]
        return {str(item) for item in parsed}
    except Exception:
        return {raw_events}


def enqueue(conn, event: str, payload: dict, created_at: str | None = None) -> list[str]:
    """Snapshot active recipients and payload into the caller's transaction."""
    payload_json = json.dumps(payload, ensure_ascii=False)
    if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Webhook payload exceeds the configured size limit")
    created_at = created_at or _timestamp(time.time())
    rows = conn.execute("SELECT id, url, secret, events FROM webhooks WHERE is_active=1").fetchall()
    delivery_ids = []
    for row in rows:
        subscriptions = _subscribed_events(row["events"])
        if "*" not in subscriptions and event not in subscriptions:
            continue
        delivery_id = str(uuid.uuid4())
        signature = hmac.new(row["secret"].encode("utf-8"), payload_json.encode("utf-8"), hashlib.sha256).hexdigest()
        conn.execute("""
            INSERT INTO webhook_outbox(delivery_id, webhook_id, target_url, signature, event, payload,
                state, attempts, available_at, created_at, updated_at)
            VALUES(?,?,?,?,?,?,'pending',0,?,?,?)
        """, (delivery_id, row["id"], row["url"], signature, event, payload_json,
              time.time(), created_at, created_at))
        delivery_ids.append(delivery_id)
    return delivery_ids


def cancel_pending(conn, webhook_id: int, reason: str = "Webhook configuration changed", now_epoch=None):
    now_epoch = time.time() if now_epoch is None else float(now_epoch)
    stamp = _timestamp(now_epoch)
    return conn.execute("""
        UPDATE webhook_outbox
        SET state='cancelled', claim_token=NULL, lease_until=NULL, last_error=?, updated_at=?
        WHERE webhook_id=? AND state IN ('pending','retry','sending')
    """, (reason[:MAX_RESPONSE_BYTES], stamp, webhook_id)).rowcount


def claim_batch(conn, now_epoch: float, limit: int, lease_seconds: int, attempt_limit: int):
    stamp = _timestamp(now_epoch)
    conn.execute("""
        UPDATE webhook_outbox
        SET state=CASE WHEN attempts >= ? THEN 'failed' ELSE 'retry' END,
            available_at=?, lease_until=NULL, claim_token=NULL,
            last_error=COALESCE(last_error, 'Delivery lease expired'), updated_at=?
        WHERE state='sending' AND lease_until<=?
    """, (attempt_limit, now_epoch, stamp, now_epoch))
    conn.execute("""
        UPDATE webhook_outbox
        SET state='failed', last_error=COALESCE(last_error, 'Maximum attempts reached'), updated_at=?
        WHERE state IN ('pending','retry') AND attempts>=?
    """, (stamp, attempt_limit))

    eligible = conn.execute("""
        SELECT delivery_id FROM webhook_outbox
        WHERE state IN ('pending','retry') AND available_at<=? AND attempts<?
        ORDER BY available_at, created_at, delivery_id LIMIT ?
    """, (now_epoch, attempt_limit, max(1, min(int(limit), 100)))).fetchall()
    jobs = []
    for row in eligible:
        token = str(uuid.uuid4())
        conn.execute("""
            UPDATE webhook_outbox
            SET state='sending', attempts=attempts+1, claim_token=?, lease_until=?, updated_at=?
            WHERE delivery_id=? AND state IN ('pending','retry') AND available_at<=? AND attempts<?
        """, (token, now_epoch + lease_seconds, stamp, row["delivery_id"], now_epoch, attempt_limit))
        job = conn.execute("SELECT * FROM webhook_outbox WHERE delivery_id=? AND claim_token=?",
                           (row["delivery_id"], token)).fetchone()
        if job:
            jobs.append(dict(job))
    return jobs


def finish_attempt(conn, delivery_id: str, claim_token: str, result: dict, now_epoch: float,
                   attempt_limit: int, retry_base_seconds: int, retry_max_seconds: int) -> bool:
    stamp = _timestamp(now_epoch)
    row = conn.execute("""
        SELECT attempts, webhook_id, event, payload FROM webhook_outbox
        WHERE delivery_id=? AND state='sending' AND claim_token=?
    """, (delivery_id, claim_token)).fetchone()
    if not row:
        return False

    attempt = int(row["attempts"])
    status_code = result.get("status_code")
    body = str(result.get("response_body") or "")[:MAX_RESPONSE_BYTES]
    error = str(result.get("error") or "")[:MAX_RESPONSE_BYTES] or None
    if status_code is not None and 200 <= int(status_code) < 300:
        state = "delivered"
        next_at = now_epoch
        delivered_at = stamp
    elif result.get("retryable") and attempt < attempt_limit:
        state = "retry"
        delay = min(retry_base_seconds * (2 ** max(0, attempt - 1)), retry_max_seconds)
        next_at = now_epoch + delay
        delivered_at = None
    else:
        state = "failed"
        next_at = now_epoch
        delivered_at = None

    updated = conn.execute("""
        UPDATE webhook_outbox
        SET state=?, available_at=?, lease_until=NULL, claim_token=NULL,
            status_code=?, response_body=?, last_error=?, updated_at=?, delivered_at=?
        WHERE delivery_id=? AND state='sending' AND claim_token=?
    """, (state, next_at, status_code, body, error, stamp, delivered_at, delivery_id, claim_token)).rowcount
    if not updated:
        return False
    conn.execute("""
        INSERT INTO webhook_delivery_attempts(delivery_id, attempt, state, status_code, response_body, error,
            duration_ms, created_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (delivery_id, attempt, state, status_code, body, error,
          max(0, int(result.get("duration_ms") or 0)), stamp))
    legacy_body = body or (f"Error: {error}" if error else "")
    conn.execute("""
        INSERT INTO webhook_logs (webhook_id, event, payload, status_code, response_body, duration_ms, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (row["webhook_id"], row["event"], str(row["payload"])[:10000], status_code,
          legacy_body, max(0, int(result.get("duration_ms") or 0)), stamp))
    conn.execute("""
        DELETE FROM webhook_logs WHERE webhook_id=? AND id NOT IN (
            SELECT id FROM webhook_logs WHERE webhook_id=? ORDER BY id DESC LIMIT 100
        )
    """, (row["webhook_id"], row["webhook_id"]))
    return True


def _deliver_job(job: dict):
    return send_payload(job["target_url"], "", job["event"], job["payload"], job["delivery_id"],
                        signature=job["signature"], address_offset=max(0, int(job["attempts"]) - 1))


def run_batch(conn_factory, sender=None, *, limit: int | None = None, clock=None,
              lease_seconds: int | None = None, attempt_limit: int | None = None,
              retry_base_seconds: int | None = None, retry_max_seconds: int | None = None) -> int:
    """Claim a bounded batch, perform network I/O outside SQLite writes, then finish by token."""
    clock = clock or time.time
    limit = _int_env("WEBHOOK_BATCH_LIMIT", DEFAULT_BATCH_LIMIT, 1, 100) if limit is None else max(1, min(int(limit), 100))
    lease_seconds = _int_env("WEBHOOK_LEASE_SECONDS", DEFAULT_LEASE_SECONDS, 5, 600) if lease_seconds is None else max(1, int(lease_seconds))
    attempt_limit = max_attempts() if attempt_limit is None else max(1, min(int(attempt_limit), 32))
    retry_base_seconds = _int_env("WEBHOOK_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS, 1, 86_400) if retry_base_seconds is None else max(1, int(retry_base_seconds))
    retry_max_seconds = _int_env("WEBHOOK_RETRY_MAX_SECONDS", DEFAULT_RETRY_MAX_SECONDS, retry_base_seconds, 604_800) if retry_max_seconds is None else max(retry_base_seconds, int(retry_max_seconds))
    sender = sender or _deliver_job

    processed = 0
    for _ in range(limit):
        with conn_factory() as conn:
            conn.execute("BEGIN IMMEDIATE")
            jobs = claim_batch(conn, clock(), 1, lease_seconds, attempt_limit)
        if not jobs:
            break
        job = jobs[0]
        with conn_factory() as conn:
            current = conn.execute("""
                SELECT 1 FROM webhook_outbox WHERE delivery_id=? AND state='sending' AND claim_token=?
            """, (job["delivery_id"], job["claim_token"])).fetchone()
        if not current:
            continue
        try:
            result = sender(job)
            if not isinstance(result, dict):
                raise TypeError("Webhook sender must return a result dictionary")
        except Exception as exc:
            result = _result(error=f"{type(exc).__name__}: {exc}", retryable=True)
        with conn_factory() as conn:
            conn.execute("BEGIN IMMEDIATE")
            finish_attempt(conn, job["delivery_id"], job["claim_token"], result, clock(),
                           attempt_limit, retry_base_seconds, retry_max_seconds)
        processed += 1
    return processed


def list_deliveries(conn, webhook_id: int, limit: int = 50):
    rows = conn.execute("""
        SELECT delivery_id, webhook_id, event, state, attempts, available_at, lease_until,
               status_code, response_body, last_error, created_at, updated_at, delivered_at
        FROM webhook_outbox WHERE webhook_id=? ORDER BY created_at DESC, delivery_id DESC LIMIT ?
    """, (webhook_id, max(1, min(int(limit), 100)))).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["attempt_logs"] = [dict(attempt) for attempt in conn.execute("""
            SELECT attempt, state, status_code, response_body, error, duration_ms, created_at
            FROM webhook_delivery_attempts WHERE delivery_id=? ORDER BY attempt
        """, (row["delivery_id"],)).fetchall()]
        result.append(item)
    return result
