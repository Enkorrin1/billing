"""Historical delivery SLA rules and bounded estimate-query count."""
import csv
import tempfile
import unittest
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as service


class AnalyticsSlaHistory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_path = service.DB_PATH
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, service, "DB_PATH", self.old_path)
        service.DB_PATH = Path(self.temp.name) / "analytics-sla.db"
        service.init_db()

        with service.db() as conn:
            self.admin_id = service.create_user(
                conn, "Analytics Admin", "sla-admin@test.local", "password123", "admin"
            )["id"]
            self.customer_id = service.create_user(
                conn, "Analytics Client", "sla-client@test.local", "password123", "customer"
            )["id"]
            current = [
                ("Accepted later", "closed", "2026-01-06T10:00:00+00:00", "2026-02-01T10:00:00+00:00", [
                    ("status", "working", "done", "2026-01-05T11:00:00+00:00"),
                    ("acceptance", "done", "accepted", "2026-02-01T10:00:00+00:00"),
                ]),
                ("Edited later", "done", "2026-01-07T10:00:00+00:00", "2026-02-01T10:00:00+00:00", [
                    ("status", "working", "done", "2026-01-06T12:00:00+00:00"),
                ]),
                ("Resubmitted late", "closed", "2026-01-10T10:00:00+00:00", "2026-02-01T10:00:00+00:00", [
                    ("status", "working", "done", "2026-01-05T10:00:00+00:00"),
                    ("acceptance", "done", "returned", "2026-01-07T10:00:00+00:00"),
                    ("status", "working", "done", "2026-01-11T10:00:00+00:00"),
                    ("acceptance", "done", "accepted", "2026-02-01T10:00:00+00:00"),
                ]),
                ("Returned pending", "working", "2026-01-10T10:00:00+00:00", "2026-02-01T10:00:00+00:00", [
                    ("status", "working", "done", "2026-01-05T10:00:00+00:00"),
                    ("acceptance", "done", "returned", "2026-01-07T10:00:00+00:00"),
                ]),
                ("Returned but closed", "closed", "2026-01-10T10:00:00+00:00", "2026-02-01T10:00:00+00:00", [
                    ("status", "working", "done", "2026-01-05T10:00:00+00:00"),
                    ("acceptance", "done", "returned", "2026-01-07T10:00:00+00:00"),
                ]),
                ("Direct close", "closed", "2026-01-07T10:00:00+00:00", "2026-01-06T10:00:00+00:00", [
                    ("status", "working", "closed", "2026-01-06T10:00:00+00:00"),
                ]),
                ("Declined", "closed", "2026-01-10T10:00:00+00:00", "2026-01-06T10:00:00+00:00", [
                    ("decline", "new", "closed", "2026-01-06T10:00:00+00:00"),
                ]),
                ("Merged", "closed", "2026-01-10T10:00:00+00:00", "2026-01-06T10:00:00+00:00", [
                    ("merged", "working", "999", "2026-01-06T10:00:00+00:00"),
                ]),
                ("Admin close", "closed", "2026-01-10T10:00:00+00:00", "2026-01-06T10:00:00+00:00", [
                    ("admin_status_correction", "working", "closed", "2026-01-06T10:00:00+00:00"),
                ]),
                ("Legacy closed", "closed", "2026-01-10T10:00:00+00:00", "2026-02-01T10:00:00+00:00", []),
                ("Old admin close", "closed", "2026-01-10T10:00:00+00:00", "2026-01-06T10:00:00+00:00", [
                    ("status", "working", "closed", "2026-01-06T10:00:00+00:00"),
                    ("assignment", "", "7", "2026-01-06T10:00:00+00:00"),
                    ("admin_edit", None, "edit", "2026-01-06T10:00:00+00:00"),
                ]),
            ]
            for row in current:
                self._insert_ticket(conn, *row, created_at="2026-01-01T10:00:00+00:00")

            for index in range(10):
                self._insert_ticket(
                    conn,
                    f"Previous {index}",
                    "done",
                    "2025-12-25T10:00:00+00:00",
                    "2025-12-20T10:00:00+00:00",
                    [("status", "working", "done", "2025-12-20T10:00:00+00:00")],
                    created_at="2025-12-15T10:00:00+00:00",
                )

        self.admin = TestClient(service.app)
        self.addCleanup(self.admin.close)
        login = self.admin.post(
            "/api/login", json={"email": "sla-admin@test.local", "password": "password123"}
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.filters = {"date_from": "2026-01-01", "date_to": "2026-01-31"}

    def _insert_ticket(self, conn, title, status, due, updated, events, created_at):
        ticket_id = conn.execute(
            """INSERT INTO tickets(customer_id, title, description, status, created_at, updated_at,
                   delivery_due_at, estimate_due_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (self.customer_id, title, "Analytics fixture", status, created_at, updated,
             due, "2026-01-04T10:00:00+00:00"),
        ).lastrowid
        conn.execute(
            """INSERT INTO estimates(ticket_id, author_id, version, amount_minor, assessment_minutes, note,
                   state, created_at, effort_minutes, performer_effort_minutes, pm_effort_minutes,
                   total_billable_minutes, hourly_rate_rub, amount_rub, client_note)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ticket_id, self.admin_id, 1, 0, 1, "fixture", "pending", created_at,
             0, 0, 0, 0, 3000, 0, ""),
        )
        for kind, old_value, new_value, stamp in events:
            conn.execute(
                """INSERT INTO ticket_events(ticket_id, actor_id, kind, old_value, new_value, created_at)
                   VALUES(?,?,?,?,?,?)""",
                (ticket_id, self.admin_id, kind, old_value, new_value, stamp),
            )
        if title in ("Accepted later", "Resubmitted late"):
            conn.execute(
                "UPDATE tickets SET accepted_at=?, accepted_by_id=? WHERE id=?",
                ("2026-02-01T10:00:00+00:00", self.customer_id, ticket_id),
            )
        return ticket_id

    def test_delivery_history_and_csv_share_sla_rule(self):
        summary_response = self.admin.get("/api/analytics/summary", params=self.filters)
        self.assertEqual(summary_response.status_code, 200, summary_response.text)
        summary = summary_response.json()
        delivery = summary["sla_details"]["delivery"]
        self.assertEqual((delivery["met"], delivery["total"], delivery["pending"]), (3, 6, 0))
        self.assertEqual((delivery["unknown"], delivery["excluded"]), (1, 4))
        self.assertEqual(
            {item["title"] for item in delivery["violations"]},
            {"Resubmitted late", "Returned pending", "Returned but closed"},
        )
        self.assertEqual(summary["avg_resolution_hours"], 144.8)

        csv_response = self.admin.get("/api/analytics/export.csv", params=self.filters)
        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        rows = list(csv.DictReader(StringIO(csv_response.text.lstrip("\ufeff")), delimiter=";"))
        by_title = {row["Заголовок"]: row for row in rows}
        self.assertEqual(by_title["Accepted later"]["Фактическая сдача"], "2026-01-05T11:00:00+00:00")
        self.assertEqual(by_title["Accepted later"]["SLA сдачи"], "В срок")
        self.assertEqual(by_title["Edited later"]["SLA сдачи"], "В срок")
        self.assertEqual(by_title["Resubmitted late"]["Фактическая сдача"], "2026-01-11T10:00:00+00:00")
        self.assertEqual(by_title["Resubmitted late"]["SLA сдачи"], "Просрочено")
        self.assertEqual(by_title["Returned pending"]["SLA сдачи"], "Просрочено")
        self.assertEqual(by_title["Returned but closed"]["SLA сдачи"], "Просрочено")
        self.assertEqual(by_title["Direct close"]["SLA сдачи"], "В срок")
        self.assertEqual(by_title["Declined"]["SLA сдачи"], "Исключено")
        self.assertEqual(by_title["Merged"]["SLA сдачи"], "Исключено")
        self.assertEqual(by_title["Admin close"]["SLA сдачи"], "Исключено")
        self.assertEqual(by_title["Old admin close"]["SLA сдачи"], "Исключено")
        self.assertEqual(by_title["Legacy closed"]["SLA сдачи"], "Неизвестно")

        labels = [row["SLA сдачи"] for row in rows]
        self.assertEqual(labels.count("В срок"), delivery["met"])
        self.assertEqual(labels.count("Просрочено"), len(delivery["violations"]))
        self.assertEqual(labels.count("Неизвестно"), delivery["unknown"])
        self.assertEqual(labels.count("Исключено"), delivery["excluded"])

    def test_first_estimate_query_count_is_fixed_for_both_summary_periods(self):
        with service.db() as conn:
            legacy_queries = []
            conn.set_trace_callback(legacy_queries.append)
            for ticket_id in conn.execute("SELECT id FROM tickets").fetchall():
                conn.execute(
                    "SELECT created_at FROM estimates WHERE ticket_id=? ORDER BY version ASC LIMIT 1",
                    (ticket_id["id"],),
                ).fetchone()
            conn.set_trace_callback(None)

        optimized_queries = []
        original_db = service.db

        @contextmanager
        def traced_db():
            with original_db() as conn:
                conn.set_trace_callback(optimized_queries.append)
                yield conn

        with patch.object(service, "db", traced_db):
            response = self.admin.get("/api/analytics/summary", params=self.filters)
        self.assertEqual(response.status_code, 200, response.text)
        before = sum("SELECT created_at FROM estimates WHERE ticket_id=" in query for query in legacy_queries)
        after = sum("FROM estimates e" in query and "MIN(e0.version)" in query for query in optimized_queries)
        self.assertEqual(before, 21)
        self.assertEqual(after, 2)


if __name__ == "__main__":
    unittest.main()
