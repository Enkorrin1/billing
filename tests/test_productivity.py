import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

temp = tempfile.TemporaryDirectory()
os.environ.setdefault("APP_DB", str(Path(temp.name) / "test.db"))
import app as service
import productivity

class Productivity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = service.DB_PATH
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, service, "DB_PATH", self.old_path)
        service.DB_PATH = Path(self.temp.name) / "productivity.db"
        service.init_db()
        with service.db() as conn:
            service.create_user(conn, "Admin", "admin@example.com", "password123", "admin")
        self.admin, self.customer, self.employee = TestClient(service.app), TestClient(service.app), TestClient(service.app)
        self.admin.post("/api/login", json={"email": "admin@example.com", "password": "password123"})
        self.customer_user = self.customer.post("/api/register", json={"name": "Клиент", "email": "c@example.com", "password": "password123"}).json()
        self.staff = self.admin.post("/api/staff", json={"name": "Иван Петров", "email": "ivan@example.com", "password": "password123"}).json()
        self.employee.post("/api/login", json={"email": "ivan@example.com", "password": "password123"})

    def ticket(self, title="Интеграция", assign=True):
        ticket_id = self.customer.post("/api/tickets", json={"title": title, "description": "Связать CRM и сайт"}).json()["id"]
        if assign:
            self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id": self.staff["id"]})
        return ticket_id

    def working_ticket(self):
        ticket_id = self.ticket()
        estimate = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 240, "assessment_minutes": 10}).json()
        self.admin.post(f"/api/tickets/{ticket_id}/estimates/{estimate['id']}/pm-review", json={"action": "send_to_customer"})
        self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id": estimate["id"], "action": "approve"})
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "working"}).status_code, 200)
        return ticket_id

    def notifications(self, client, kind):
        return [n for n in client.get("/api/notifications").json() if n["kind"] == kind]

    def test_decisions_show_unassigned_pm_review_and_customer_reply(self):
        unassigned = self.ticket("Без ответственного", assign=False)
        ticket_id = self.ticket()
        self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 60, "assessment_minutes": 10})
        self.customer.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Есть новости?", "request_id": "news-request"})
        admin_kinds = {(d["kind"], d["ticket_id"]) for d in self.admin.get("/api/decisions").json()}
        self.assertIn(("assign", unassigned), admin_kinds)
        self.assertIn(("pm_estimate", ticket_id), admin_kinds)
        mine = {(d["kind"], d["ticket_id"]) for d in self.employee.get("/api/decisions").json()}
        self.assertIn(("reply", ticket_id), mine)
        self.assertNotIn(("assign", unassigned), mine)
        self.assertEqual(self.customer.get("/api/decisions").status_code, 403)

    def test_mention_in_internal_note_notifies_colleague(self):
        ticket_id = self.ticket()
        self.admin.post(f"/api/tickets/{ticket_id}/internal-notes", json={"body": "@Иван Петров проверь доступы, @никто"})
        mentions = self.notifications(self.employee, "mention")
        self.assertEqual(len(mentions), 1)
        self.assertIn("Admin", mentions[0]["text"])
        self.assertIn(("mention", ticket_id), {(d["kind"], d["ticket_id"]) for d in self.employee.get("/api/decisions").json()})
        self.admin.post(f"/api/tickets/{ticket_id}/internal-notes", json={"body": "Почта ivan@example.com не упоминание"})
        self.assertEqual(len(self.notifications(self.employee, "mention")), 1)

    def test_mention_matches_email_login_and_not_author(self):
        with service.db() as conn:
            self.assertEqual(productivity.mentioned_staff(conn, "@ivan, глянь", None), {self.staff["id"]})
            self.assertEqual(productivity.mentioned_staff(conn, "@Ивановский", None), set())
            self.assertEqual(productivity.mentioned_staff(conn, "@Иван", self.staff["id"]), set())

    def test_saved_views_are_private_and_limited_to_known_filters(self):
        created = self.employee.post("/api/saved-views", json={"name": "Срочные", "filters": {"priorityFilter": "urgent", "evil": "x"}})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["filters"], {"priorityFilter": "urgent"})
        self.assertEqual(self.admin.get("/api/saved-views").json(), [])
        self.assertEqual(self.admin.delete(f"/api/saved-views/{created.json()['id']}").status_code, 404)
        self.assertEqual(self.employee.delete(f"/api/saved-views/{created.json()['id']}").status_code, 200)

    def test_escalation_notifies_once_before_and_after_deadline(self):
        ticket_id = self.ticket()
        at = datetime.now(timezone.utc)
        with service.db() as conn:
            conn.execute("UPDATE tickets SET response_due_at=?,first_staff_response_at=NULL WHERE id=?",
                         ((at + timedelta(minutes=30)).isoformat(), ticket_id))
        self.assertEqual(productivity.run_escalations(service, at), 1)
        self.assertEqual(productivity.run_escalations(service, at), 0)
        self.assertEqual(len(self.notifications(self.employee, "sla_soon")), 1)
        self.assertEqual(productivity.run_escalations(service, at + timedelta(hours=1)), 1)
        self.assertEqual(len(self.notifications(self.employee, "sla_overdue")), 1)
        self.assertEqual(len(self.notifications(self.admin, "sla_overdue")), 1)

    def test_old_overdue_tickets_are_recorded_without_flooding(self):
        ticket_id = self.ticket()
        with service.db() as conn:
            conn.execute("UPDATE tickets SET response_due_at=?,first_staff_response_at=NULL WHERE id=?",
                         ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(), ticket_id))
        productivity.run_escalations(service)
        self.assertEqual(self.notifications(self.admin, "sla_overdue"), [])

    def test_timesheet_saves_week_in_one_request(self):
        ticket_id = self.working_ticket()
        today = service.payroll.work_today()
        monday = today - timedelta(days=today.weekday())
        days = [d for d in (monday, today) if d <= today]
        entries = [{"ticket_id": ticket_id, "work_date": d.isoformat(), "minutes": 30, "note": "Настройка обмена",
                    "request_id": f"ts-{d.isoformat()}"} for d in dict.fromkeys(days)]
        self.assertEqual(self.employee.post("/api/timesheet", json={"entries": entries}).status_code, 200)
        self.employee.post("/api/timesheet", json={"entries": entries})
        sheet = self.employee.get(f"/api/timesheet?week_start={monday.isoformat()}").json()
        row = next(r for r in sheet["rows"] if r["id"] == ticket_id)
        self.assertEqual(sum(row["days"].values()), 30 * len(entries))
        self.assertEqual(row["remaining_minutes"], 240 - 30 * len(entries))

    def test_timesheet_rejects_whole_batch_on_error(self):
        ticket_id = self.working_ticket()
        today = service.payroll.work_today().isoformat()
        response = self.employee.post("/api/timesheet", json={"entries": [
            {"ticket_id": ticket_id, "work_date": today, "minutes": 60, "note": "Работа", "request_id": "batch-0001"},
            {"ticket_id": ticket_id, "work_date": today, "minutes": 600, "note": "Слишком много", "request_id": "batch-0002"}]})
        self.assertEqual(response.status_code, 409)
        self.assertIn(f"№{ticket_id}", response.json()["detail"])
        with service.db() as conn:
            self.assertEqual(service.actual_minutes(conn, ticket_id), 0)

    def test_friday_timesheet_reminder_once_per_week(self):
        self.working_ticket()
        friday = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)
        with mock.patch.object(service.web_push, "enqueue") as push:
            self.assertEqual(productivity.run_timesheet_reminders(service, friday), 1)
            self.assertEqual(productivity.run_timesheet_reminders(service, friday), 0)
            self.assertEqual(productivity.run_timesheet_reminders(service, friday - timedelta(days=1)), 0)
        self.assertEqual(push.call_count, 1)

    def test_low_balance_alert_once_until_topped_up(self):
        with mock.patch.dict(os.environ, {"BILLING_ENABLED": "1", "LOW_BALANCE_RUB": "5000"}), \
                mock.patch.object(service.web_push, "enqueue") as push:
            with service.db() as conn:
                conn.execute("UPDATE customer_profiles SET deposit_balance_rub=3000,held_rub=0 WHERE user_id=?", (self.customer_user["id"],))
            status = self.customer.get("/api/balance-status").json()
            self.assertTrue(status["low"])
            self.assertEqual(status["available_rub"], 3000)
            self.assertEqual(productivity.run_balance_alerts(service), 1)
            self.assertEqual(productivity.run_balance_alerts(service), 0)
            with service.db() as conn:
                conn.execute("UPDATE customer_profiles SET deposit_balance_rub=90000 WHERE user_id=?", (self.customer_user["id"],))
            productivity.run_balance_alerts(service)
            self.assertFalse(self.customer.get("/api/balance-status").json()["low"])
            with service.db() as conn:
                conn.execute("UPDATE customer_profiles SET deposit_balance_rub=100 WHERE user_id=?", (self.customer_user["id"],))
            self.assertEqual(productivity.run_balance_alerts(service), 1)
        self.assertEqual(push.call_count, 2)
        self.assertFalse(self.admin.get("/api/balance-status").json()["visible"])

    def test_recurring_ticket_created_on_schedule(self):
        plan = self.customer.post("/api/recurring-tickets", json={"title": "Ежемесячное обслуживание", "description": "Обновления и бэкапы",
                                                                   "frequency": "monthly", "day": 5})
        self.assertEqual(plan.status_code, 201)
        due = datetime.fromisoformat(plan.json()["next_run_at"])
        self.assertEqual(due.astimezone(service.local_tz()).day, 5)
        self.assertEqual(productivity.run_recurring(service, due - timedelta(minutes=1)), 0)
        self.assertEqual(productivity.run_recurring(service, due), 1)
        self.assertEqual(productivity.run_recurring(service, due), 0)
        tickets = [t for t in self.customer.get("/api/tickets").json() if t["title"] == "Ежемесячное обслуживание"]
        self.assertEqual(len(tickets), 1)
        listed = self.customer.get("/api/recurring-tickets").json()[0]
        self.assertEqual(listed["last_ticket_id"], tickets[0]["id"])
        self.assertGreater(listed["next_run_at"], plan.json()["next_run_at"])
        self.assertEqual(self.employee.post("/api/recurring-tickets", json={"title": "Чужое", "description": "Нельзя без менеджера",
                                                                             "frequency": "weekly", "day": 1,
                                                                             "customer_id": self.customer_user["id"]}).status_code, 403)
        self.assertEqual(self.employee.get("/api/recurring-tickets").json(), [])
        self.assertEqual(self.customer.patch(f"/api/recurring-tickets/{listed['id']}", json={"active": False}).json()["active"], 0)

    def test_next_run_handles_week_and_month_end(self):
        tz = timezone(timedelta(hours=3))
        wed = datetime(2026, 10, 28, 12, 0, tzinfo=tz)
        self.assertEqual(datetime.fromisoformat(productivity.next_run("weekly", 1, wed, tz)).astimezone(tz).date(), date(2026, 11, 2))
        self.assertEqual(datetime.fromisoformat(productivity.next_run("monthly", 28, wed, tz)).astimezone(tz).date(), date(2026, 11, 28))
        self.assertEqual(datetime.fromisoformat(productivity.next_run("monthly", 28, wed.replace(day=29), tz)).astimezone(tz).date(),
                         date(2026, 11, 28))

    def test_merge_moves_conversation_and_closes_duplicate(self):
        target = self.ticket("Не работает форма")
        source = self.ticket("Форма не отправляется")
        self.customer.post(f"/api/tickets/{source}/messages", json={"body": "Скриншот ошибки ниже", "request_id": "same-request-1"})
        self.customer.post(f"/api/tickets/{target}/messages", json={"body": "Первое сообщение", "request_id": "same-request-1"})
        self.assertEqual(self.employee.post(f"/api/tickets/{source}/merge", json={"target_id": target}).status_code, 403)
        response = self.admin.post(f"/api/tickets/{source}/merge", json={"target_id": target})
        self.assertEqual(response.status_code, 200)
        merged = self.admin.get(f"/api/tickets/{target}").json()
        self.assertEqual({m["body"] for m in merged["messages"]}, {"Скриншот ошибки ниже", "Первое сообщение"})
        self.assertEqual(self.admin.get(f"/api/tickets/{source}").json()["ticket"]["status"], "closed")
        self.assertTrue(any("объединена" in n["text"] for n in self.notifications(self.customer, "merged")))
        notes = self.admin.get(f"/api/tickets/{target}/internal-notes").json()
        self.assertTrue(any(f"№{source}" in n["body"] for n in notes))

    def test_merge_refuses_duplicate_with_billing_history(self):
        target = self.ticket()
        source = self.working_ticket()
        self.assertEqual(self.admin.post(f"/api/tickets/{source}/merge", json={"target_id": target}).status_code, 409)
        other_customer = TestClient(service.app)
        other_customer.post("/api/register", json={"name": "Другой", "email": "o@example.com", "password": "password123"})
        foreign = other_customer.post("/api/tickets", json={"title": "Чужая", "description": "Другой клиент"}).json()["id"]
        self.assertEqual(self.admin.post(f"/api/tickets/{foreign}/merge", json={"target_id": target}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
