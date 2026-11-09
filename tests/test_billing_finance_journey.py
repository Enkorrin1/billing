import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as service
import payroll
import webhook_delivery


class BillingFinanceJourneyTests(unittest.TestCase):
    """One API fixture for customer billing, document scope and USD payroll."""

    def setUp(self):
        self.old_billing = os.environ.get("BILLING_ENABLED")
        os.environ["BILLING_ENABLED"] = "1"
        self.temp = tempfile.TemporaryDirectory(prefix="billing-finance-journey-")
        self.old_path = service.DB_PATH
        service.DB_PATH = Path(self.temp.name) / "journey.db"
        service.init_db()

        self.ids = {}
        with service.db() as conn:
            for key, role in (
                ("admin", "admin"),
                ("worker", "employee"),
                ("client_a", "customer"),
                ("client_b", "customer"),
            ):
                service.create_user(
                    conn,
                    key.replace("_", " ").title(),
                    f"{key}@finance-journey.test",
                    "Password123!",
                    role,
                )
                self.ids[key] = conn.execute(
                    "SELECT id FROM users WHERE email=?",
                    (f"{key}@finance-journey.test",),
                ).fetchone()[0]

        self.clients = {}
        for key in self.ids:
            client = TestClient(service.app)
            response = client.post(
                "/api/login",
                json={"email": f"{key}@finance-journey.test", "password": "Password123!"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.clients[key] = client

        self.admin = self.clients["admin"]
        self.worker = self.clients["worker"]
        self.customer_a = self.clients["client_a"]
        self.customer_b = self.clients["client_b"]
        self.day = payroll.work_today().isoformat()

    def tearDown(self):
        for client in getattr(self, "clients", {}).values():
            client.close()
        service.DB_PATH = self.old_path
        self.temp.cleanup()
        if self.old_billing is None:
            os.environ.pop("BILLING_ENABLED", None)
        else:
            os.environ["BILLING_ENABLED"] = self.old_billing

    def customer_overview(self, client=None):
        response = (client or self.customer_a).get("/api/billing/overview")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_customer_billing_and_internal_usd_payout_are_scoped_and_idempotent(self):
        # Client A funds a RUB balance. Replaying payment must not duplicate the deposit.
        invoice_a = self.customer_a.post(
            "/api/billing/invoices",
            json={
                "doc_type": "invoice",
                "client_type": "user",
                "client_id": self.ids["client_a"],
                "amount_rub": 20_000,
            },
        )
        self.assertEqual(invoice_a.status_code, 201, invoice_a.text)
        invoice_a_id = invoice_a.json()["id"]
        paid_a = f"/api/billing/invoices/{invoice_a_id}/status"
        for _ in range(2):
            response = self.admin.patch(paid_a, json={"status": "paid"})
            self.assertEqual(response.status_code, 200, response.text)

        balance = self.customer_overview()
        self.assertEqual(balance["balance_rub"], 20_000)
        self.assertEqual(balance["held_rub"], 0)
        self.assertEqual(balance["available_rub"], 20_000)
        self.assertEqual(
            [row["amount_rub"] for row in balance["transactions"] if row["tx_type"] == "deposit"],
            [20_000],
        )

        # Client B owns a different document; A cannot read it.
        invoice_b = self.customer_b.post(
            "/api/billing/invoices",
            json={
                "doc_type": "invoice",
                "client_type": "user",
                "client_id": self.ids["client_b"],
                "amount_rub": 8_000,
            },
        )
        self.assertEqual(invoice_b.status_code, 201, invoice_b.text)
        self.assertEqual(self.customer_a.get(f"/api/billing/invoices/{invoice_b.json()['id']}").status_code, 403)
        self.assertEqual(self.customer_b.get(f"/api/billing/invoices/{invoice_b.json()['id']}").status_code, 200)

        # Price agreement produces a RUB reserve before the ticket is completed.
        ticket_response = self.customer_a.post(
            "/api/tickets",
            json={"title": "Разработка клиента A", "description": "Финансовая сквозная проверка"},
        )
        self.assertEqual(ticket_response.status_code, 201, ticket_response.text)
        ticket_id = ticket_response.json()["id"]
        assigned = self.admin.patch(
            f"/api/tickets/{ticket_id}/assignee",
            json={"assignee_id": self.ids["worker"]},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        estimate = self.worker.post(
            f"/api/tickets/{ticket_id}/estimates",
            json={"effort_minutes": 90, "assessment_minutes": 10, "note": "Внутренняя оценка"},
        )
        self.assertEqual(estimate.status_code, 201, estimate.text)
        review = self.admin.post(
            f"/api/tickets/{ticket_id}/estimates/{estimate.json()['id']}/pm-review",
            json={"action": "send_to_customer", "pm_effort_minutes": 30, "custom_amount_rub": 12_345},
        )
        self.assertEqual(review.status_code, 200, review.text)
        decision = self.customer_a.post(
            f"/api/tickets/{ticket_id}/estimates/decision",
            json={"estimate_id": estimate.json()["id"], "action": "approve"},
        )
        self.assertEqual(decision.status_code, 200, decision.text)

        balance = self.customer_overview()
        self.assertEqual(balance["balance_rub"], 20_000)
        self.assertEqual(balance["held_rub"], 12_345)
        self.assertEqual(balance["available_rub"], 7_655)
        self.assertEqual(balance["unbilled_rub"], 0)

        # Log internal work before invoicing to prove that client A's projection ignores it.
        internal_task = self.admin.post(
            "/api/tasks",
            json={"title": "Внутренняя документация", "owner_id": self.ids["worker"]},
        )
        self.assertEqual(internal_task.status_code, 201, internal_task.text)
        task_path = f"/api/tasks/{internal_task.json()['id']}"
        time_payload = {
            "minutes": 30,
            "summary": "Подготовка внутренней документации",
            "entry_date": self.day,
            "request_id": "finance-internal-time-1",
        }
        first_time = self.worker.post(task_path + "/time-entries", json=time_payload)
        self.assertEqual(first_time.status_code, 201, first_time.text)
        retry_time = self.worker.post(task_path + "/time-entries", json=time_payload)
        self.assertEqual(retry_time.status_code, 201, retry_time.text)
        self.assertEqual(retry_time.json()["id"], first_time.json()["id"])
        balance_with_internal_task = self.customer_overview()
        self.assertEqual(balance_with_internal_task["balance_rub"], 20_000)
        self.assertEqual(balance_with_internal_task["held_rub"], 12_345)
        self.assertEqual(balance_with_internal_task["unbilled_rub"], 0)

        completed = self.admin.patch(f"/api/admin/tickets/{ticket_id}", json={"status": "done"})
        self.assertEqual(completed.status_code, 200, completed.text)
        balance = self.customer_overview()
        self.assertEqual(balance["held_rub"], 12_345)
        self.assertEqual(balance["unbilled_rub"], 12_345)

        # The customer act charges the agreed amount; cancellation refunds it once and reopens the reserve.
        act_response = self.admin.post(
            "/api/billing/invoices",
            json={
                "doc_type": "act",
                "client_type": "user",
                "client_id": self.ids["client_a"],
                "ticket_ids": [ticket_id],
                "service_entry_ids": [],
            },
        )
        self.assertEqual(act_response.status_code, 201, act_response.text)
        act_id = act_response.json()["id"]
        self.assertEqual(act_response.json()["total_rub"], 12_345)
        self.assertEqual(self.customer_a.get(f"/api/billing/invoices/{act_id}").status_code, 200)
        act_detail = self.admin.get(f"/api/billing/invoices/{act_id}")
        self.assertEqual(act_detail.status_code, 200, act_detail.text)
        self.assertEqual([item["ticket_id"] for item in act_detail.json()["items"]], [ticket_id])

        balance = self.customer_overview()
        self.assertEqual(balance["balance_rub"], 7_655)
        self.assertEqual(balance["held_rub"], 0)
        self.assertEqual(balance["unbilled_rub"], 0)

        cancel_path = f"/api/billing/invoices/{act_id}/status"
        for _ in range(2):
            cancelled = self.admin.patch(cancel_path, json={"status": "cancelled"})
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
        balance = self.customer_overview()
        self.assertEqual(balance["balance_rub"], 20_000)
        self.assertEqual(balance["held_rub"], 12_345)
        self.assertEqual(balance["available_rub"], 7_655)
        self.assertEqual(balance["unbilled_rub"], 12_345)

        with service.db() as conn:
            transactions = [
                dict(row)
                for row in conn.execute(
                    "SELECT tx_type, amount_rub, invoice_id FROM billing_transactions "
                    "WHERE customer_id=? ORDER BY id",
                    (self.ids["client_a"],),
                )
            ]
            self.assertEqual(
                transactions,
                [
                    {"tx_type": "deposit", "amount_rub": 20_000, "invoice_id": invoice_a_id},
                    {"tx_type": "charge", "amount_rub": -12_345, "invoice_id": act_id},
                    {"tx_type": "adjustment", "amount_rub": 12_345, "invoice_id": act_id},
                ],
            )
            task_entries = conn.execute("SELECT COUNT(*) FROM task_time_entries").fetchone()[0]
            service_entries = conn.execute("SELECT COUNT(*) FROM service_entries").fetchone()[0]
            self.assertEqual(task_entries, 1)
            self.assertEqual(service_entries, 0)

        # Internal work is only a performer payout. Its retried request creates one USD payroll row.
        rate = self.admin.post(
            f"/api/payroll/rates/{self.ids['worker']}",
            json={"cents_per_hour": 2_500},
        )
        self.assertEqual(rate.status_code, 200, rate.text)
        payroll_view = self.admin.get(
            "/api/payroll",
            params={"period_start": self.day, "period_end": self.day},
        )
        self.assertEqual(payroll_view.status_code, 200, payroll_view.text)
        internal_rows = [row for row in payroll_view.json()["entries"] if row["source_kind"] == "task"]
        self.assertEqual(len(internal_rows), 1)
        entry = internal_rows[0]
        self.assertEqual(entry["minutes"], 30)
        self.assertEqual(self.admin.post(
            f"/api/payroll/entries/{entry['id']}/review", json={"action": "approve"}
        ).status_code, 200)

        act_payload = {
            "employee_id": self.ids["worker"],
            "period_start": self.day,
            "period_end": self.day,
            "entry_ids": [entry["id"]],
            "expected_total_cents": 1_250,
            "request_id": "finance-internal-payroll-act",
        }
        payroll_act = self.admin.post("/api/payroll/acts", json=act_payload)
        self.assertEqual(payroll_act.status_code, 201, payroll_act.text)
        payroll_act_retry = self.admin.post("/api/payroll/acts", json=act_payload)
        self.assertEqual(payroll_act_retry.status_code, 201, payroll_act_retry.text)
        self.assertEqual(payroll_act_retry.json()["id"], payroll_act.json()["id"])
        self.assertEqual(payroll_act.json()["total_cents"], 1_250)
        self.assertEqual(payroll_act.json()["items"][0]["source_kind"], "task")
        printed = self.worker.get(f"/api/payroll/acts/{payroll_act.json()['id']}/print")
        self.assertEqual(printed.status_code, 200, printed.text)
        self.assertIn("12.50 USD", printed.text)

        paid = self.admin.post(f"/api/payroll/acts/{payroll_act.json()['id']}/paid")
        self.assertEqual(paid.status_code, 200, paid.text)
        paid_retry = self.admin.post(f"/api/payroll/acts/{payroll_act.json()['id']}/paid")
        self.assertEqual(paid_retry.status_code, 200, paid_retry.text)
        self.assertEqual(paid_retry.json()["paid_at"], paid.json()["paid_at"])

        # The internal task has no client billing side effects and does not enter Client B's ledger.
        self.assertEqual(self.customer_overview()["unbilled_rub"], 12_345)
        self.assertEqual(self.customer_overview(self.customer_b)["balance_rub"], 0)
        with service.db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM billing_transactions WHERE customer_id=?",
                    (self.ids["client_a"],),
                ).fetchone()[0],
                3,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM service_entries").fetchone()[0], 0)

    def test_status_event_delivery_is_subscribed_and_visible_through_api(self):
        subscription = self.admin.post(
            "/api/webhooks",
            json={
                "url": "https://hooks.example.test/finance",
                "secret": "finance-test-secret",
                "events": ["ticket.status_changed"],
                "description": "Finance journey status events",
            },
        )
        self.assertEqual(subscription.status_code, 201, subscription.text)
        webhook_id = subscription.json()["id"]

        created = self.customer_a.post(
            "/api/tickets",
            json={"title": "Webhook finance status", "description": "Trigger one domain event"},
        )
        self.assertIn(created.status_code, (200, 201), created.text)
        ticket_id = created.json()["id"]

        assigned = self.admin.patch(
            f"/api/tickets/{ticket_id}/assignee",
            json={"assignee_id": self.ids["worker"]},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        changed = self.worker.patch(
            f"/api/tickets/{ticket_id}/status", json={"status": "waiting"}
        )
        self.assertEqual(changed.status_code, 200, changed.text)

        deliveries_url = f"/api/webhooks/{webhook_id}/deliveries"
        pending_response = self.admin.get(deliveries_url)
        self.assertEqual(pending_response.status_code, 200, pending_response.text)
        pending = pending_response.json()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event"], "ticket.status_changed")
        self.assertEqual(pending[0]["state"], "pending")
        self.assertEqual(pending[0]["attempts"], 0)

        processed = webhook_delivery.run_batch(
            service.db,
            lambda _job: {
                "status_code": 204,
                "response_body": "accepted",
                "duration_ms": 1,
                "error": None,
                "retryable": False,
            },
            limit=1,
            clock=lambda: 1_800_000_000,
        )
        self.assertEqual(processed, 1)

        delivered_response = self.admin.get(deliveries_url)
        self.assertEqual(delivered_response.status_code, 200, delivered_response.text)
        delivered = delivered_response.json()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["delivery_id"], pending[0]["delivery_id"])
        self.assertEqual(delivered[0]["state"], "delivered")
        self.assertEqual(delivered[0]["attempts"], 1)
        self.assertEqual(delivered[0]["attempt_logs"][0]["state"], "delivered")
        self.assertEqual(delivered[0]["attempt_logs"][0]["status_code"], 204)
        logs = self.admin.get(f"/api/webhooks/{webhook_id}/logs")
        self.assertEqual(logs.status_code, 200, logs.text)
        self.assertEqual(logs.json()[0]["event"], "ticket.status_changed")
        self.assertEqual(json.loads(logs.json()[0]["payload"])["ticket_id"], ticket_id)


if __name__ == "__main__":
    unittest.main()
