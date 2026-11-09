import hashlib
import hmac
import json
import socket
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import webhook_delivery as delivery


class WebhookDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="webhook-delivery-")
        self.db_path = Path(self.temp.name) / "delivery.db"
        with self.db() as conn:
            conn.execute(
                """CREATE TABLE webhooks (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    secret TEXT NOT NULL,
                    events TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                )"""
            )
            conn.execute(
                """CREATE TABLE webhook_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status_code INTEGER,
                    response_body TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )"""
            )
            delivery.init_schema(conn)
            conn.execute(
                "INSERT INTO webhooks(id,url,secret,events,is_active) VALUES(1,?,?,?,1)",
                ("https://hooks.example.test/events", "signing-secret", '["*"]'),
            )

    def tearDown(self):
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def db(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def conn_factory(self):
        return self.db()

    def enqueue(self, event="ticket.updated", payload=None, created_at="2026-11-09T00:00:00+00:00"):
        with self.db() as conn:
            return delivery.enqueue(conn, event, payload or {"ticket_id": 7}, created_at)

    def test_outbox_write_rolls_back_with_the_caller_transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            delivery_ids = delivery.enqueue(
                conn,
                "ticket.updated",
                {"ticket_id": 7},
                "2026-11-09T00:00:00+00:00",
            )
            self.assertEqual(len(delivery_ids), 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM webhook_outbox").fetchone()[0], 1)
            conn.rollback()
        finally:
            conn.close()

        with self.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM webhook_outbox").fetchone()[0], 0)

    def test_expired_lease_recovers_after_restart_and_rejects_stale_worker(self):
        delivery_id = self.enqueue(payload={"case": "restart"})[0]

        # The first connection represents a worker that stops after claiming the row.
        with self.db() as conn:
            conn.execute("UPDATE webhook_outbox SET available_at=100 WHERE delivery_id=?", (delivery_id,))
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            first_claim = delivery.claim_batch(conn, 100, 1, 10, 3)[0]
        self.assertEqual(first_claim["attempts"], 1)
        self.assertEqual(first_claim["lease_until"], 110)

        # A new connection/process reclaims the expired lease with a different token.
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            second_claim = delivery.claim_batch(conn, 111, 1, 10, 3)[0]
        self.assertEqual(second_claim["attempts"], 2)
        self.assertNotEqual(second_claim["claim_token"], first_claim["claim_token"])

        success = {
            "status_code": 200,
            "response_body": "accepted",
            "duration_ms": 2,
            "error": None,
            "retryable": False,
        }
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.assertFalse(
                delivery.finish_attempt(
                    conn, delivery_id, first_claim["claim_token"], success, 112, 3, 5, 20
                )
            )
            row = conn.execute(
                "SELECT state,attempts,claim_token,status_code FROM webhook_outbox WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            self.assertEqual((row["state"], row["attempts"], row["claim_token"], row["status_code"]),
                             ("sending", 2, second_claim["claim_token"], None))
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM webhook_delivery_attempts WHERE delivery_id=?", (delivery_id,)
                ).fetchone()[0],
                0,
            )

        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.assertTrue(
                delivery.finish_attempt(
                    conn, delivery_id, second_claim["claim_token"], success, 113, 3, 5, 20
                )
            )
        with self.db() as conn:
            row = conn.execute(
                "SELECT state,attempts,status_code,delivered_at FROM webhook_outbox WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            self.assertEqual((row["state"], row["attempts"], row["status_code"]), ("delivered", 2, 200))
            self.assertTrue(row["delivered_at"])
            attempt = conn.execute(
                "SELECT attempt,state,status_code FROM webhook_delivery_attempts WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            self.assertEqual(tuple(attempt), (2, "delivered", 200))

    def test_batch_records_http_outcomes_and_retries_only_transient_responses(self):
        cases = {
            "success": (200, False, "delivered"),
            "throttle": (429, True, "retry"),
            "server_error": (503, True, "retry"),
            "bad_request": (400, False, "failed"),
            "redirect": (302, False, "failed"),
        }
        delivery_ids = {}
        for case in cases:
            delivery_ids[case] = self.enqueue(payload={"case": case})[0]
        with self.db() as conn:
            conn.execute("UPDATE webhook_outbox SET available_at=100")

        first_calls = []

        def first_sender(job):
            case = json.loads(job["payload"])["case"]
            first_calls.append(case)
            # A write from the sender succeeds because run_batch released its claim transaction.
            with self.db() as sender_conn:
                sender_conn.execute("UPDATE webhooks SET secret=secret WHERE id=1")
            status, retryable, _state = cases[case]
            return {
                "status_code": status,
                "response_body": f"HTTP {status}",
                "duration_ms": 3,
                "error": f"HTTP {status}" if status >= 300 else None,
                "retryable": retryable,
            }

        processed = delivery.run_batch(
            self.conn_factory,
            first_sender,
            limit=10,
            clock=lambda: 100,
            lease_seconds=30,
            attempt_limit=3,
            retry_base_seconds=5,
            retry_max_seconds=20,
        )
        self.assertEqual(processed, len(cases))
        self.assertCountEqual(first_calls, cases)

        with self.db() as conn:
            rows = conn.execute(
                "SELECT delivery_id,state,attempts,status_code,available_at,delivered_at,payload "
                "FROM webhook_outbox"
            ).fetchall()
            states = {json.loads(row["payload"])["case"]: row for row in rows}
            for case, (status, _retryable, state) in cases.items():
                with self.subTest(case=case):
                    row = states[case]
                    self.assertEqual((row["state"], row["attempts"], row["status_code"]), (state, 1, status))
                    if state == "retry":
                        self.assertEqual(row["available_at"], 105)
                        self.assertIsNone(row["delivered_at"])
                    elif state == "delivered":
                        self.assertTrue(row["delivered_at"])
                    else:
                        self.assertIsNone(row["delivered_at"])

        retry_calls = []

        def retry_sender(job):
            retry_calls.append(json.loads(job["payload"])["case"])
            return {
                "status_code": 204,
                "response_body": "accepted on retry",
                "duration_ms": 1,
                "error": None,
                "retryable": False,
            }

        retried = delivery.run_batch(
            self.conn_factory,
            retry_sender,
            limit=10,
            clock=lambda: 105,
            lease_seconds=30,
            attempt_limit=3,
            retry_base_seconds=5,
            retry_max_seconds=20,
        )
        self.assertEqual(retried, 2)
        self.assertCountEqual(retry_calls, ["throttle", "server_error"])

        with self.db() as conn:
            rows = conn.execute("SELECT state,attempts,payload FROM webhook_outbox").fetchall()
            final = {json.loads(row["payload"])["case"]: row for row in rows}
            self.assertEqual((final["throttle"]["state"], final["throttle"]["attempts"]), ("delivered", 2))
            self.assertEqual((final["server_error"]["state"], final["server_error"]["attempts"]), ("delivered", 2))
            self.assertEqual((final["bad_request"]["state"], final["bad_request"]["attempts"]), ("failed", 1))
            self.assertEqual((final["redirect"]["state"], final["redirect"]["attempts"]), ("failed", 1))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM webhook_delivery_attempts").fetchone()[0],
                7,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM webhook_logs").fetchone()[0], 7)

    def test_http_sender_classifies_statuses_and_never_follows_redirects(self):
        class FakeResponse:
            def __init__(self, status):
                self.status = status

            def read(self, limit):
                return b"remote response"

        class FakeConnection:
            def __init__(self, status):
                self.status = status
                self.requests = []
                self.closed = False

            def connect(self):
                return None

            def request(self, method, target, body=None, headers=None):
                self.requests.append((method, target, body, headers))

            def getresponse(self):
                return FakeResponse(self.status)

            def close(self):
                self.closed = True

        expected = {
            200: (False, None),
            204: (False, None),
            302: (False, "redirects are not followed"),
            400: (False, None),
            408: (True, None),
            425: (True, None),
            429: (True, None),
            500: (True, None),
        }
        connections = []

        def resolver(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", port))]

        for status, (retryable, error_fragment) in expected.items():
            connection = FakeConnection(status)
            connections.append(connection)
            result = delivery.send_payload(
                "https://hooks.example.com/v1/events?kind=ticket",
                "hmac-secret",
                "ticket.updated",
                {"ticket_id": 17, "title": "Проверка"},
                "delivery-123",
                resolver=resolver,
                connection_factory=lambda *_args, candidate=connection: candidate,
                allowed_hosts={"hooks.example.com"},
            )
            with self.subTest(status=status):
                self.assertEqual(result["status_code"], status)
                self.assertEqual(result["retryable"], retryable)
                if error_fragment:
                    self.assertIn(error_fragment, result["error"])
                self.assertTrue(connection.closed)
                self.assertEqual(len(connection.requests), 1)
                method, target, body, headers = connection.requests[0]
                self.assertEqual((method, target), ("POST", "/v1/events?kind=ticket"))
                self.assertEqual(
                    headers["X-Signature-SHA256"],
                    hmac.new(b"hmac-secret", body, hashlib.sha256).hexdigest(),
                )
                self.assertEqual(headers["X-Desk-Delivery-ID"], "delivery-123")

    def test_dns_policy_rejects_private_addresses_and_retryable_lookup_failures(self):
        connection_calls = []

        def private_resolver(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", port))]

        def forbidden_connection_factory(*args):
            connection_calls.append(args)
            raise AssertionError("A private DNS answer must not reach the connector")

        blocked = delivery.send_payload(
            "https://hooks.example.com/events",
            "secret",
            "ticket.updated",
            {"ticket_id": 1},
            "delivery-private",
            resolver=private_resolver,
            connection_factory=forbidden_connection_factory,
            allowed_hosts={"hooks.example.com"},
        )
        self.assertFalse(blocked["retryable"])
        self.assertIn("non-public", blocked["error"])
        self.assertEqual(connection_calls, [])

        def failing_resolver(host, port, **kwargs):
            raise OSError("temporary DNS failure")

        transient = delivery.send_payload(
            "https://hooks.example.com/events",
            "secret",
            "ticket.updated",
            {"ticket_id": 1},
            "delivery-dns-failure",
            resolver=failing_resolver,
            allowed_hosts={"hooks.example.com"},
        )
        self.assertTrue(transient["retryable"])
        self.assertIn("temporary DNS failure", transient["error"])

    def test_cancel_pending_cancels_queued_and_sending_rows(self):
        pending_id = self.enqueue(payload={"case": "pending"})[0]
        sending_id = self.enqueue(payload={"case": "sending"})[0]
        with self.db() as conn:
            conn.execute("UPDATE webhook_outbox SET available_at=100")
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            claim = delivery.claim_batch(conn, 100, 1, 30, 3)[0]

        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = delivery.cancel_pending(conn, 1, "endpoint removed", now_epoch=101)
            self.assertEqual(changed, 2)
        with self.db() as conn:
            states = {
                row["delivery_id"]: row["state"]
                for row in conn.execute("SELECT delivery_id,state FROM webhook_outbox")
            }
            self.assertEqual(states, {pending_id: "cancelled", sending_id: "cancelled"})
            self.assertFalse(
                delivery.finish_attempt(
                    conn,
                    claim["delivery_id"],
                    claim["claim_token"],
                    {"status_code": 200, "response_body": "ok", "duration_ms": 1},
                    102,
                    3,
                    5,
                    20,
                )
            )


if __name__ == "__main__":
    unittest.main()
