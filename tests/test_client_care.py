import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

temp = tempfile.TemporaryDirectory()
os.environ.setdefault("APP_DB", str(Path(temp.name) / "test.db"))
import app as service
import mailer


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


class ClientCare(unittest.TestCase):
    def setUp(self):
        self.mail_dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"EMAIL_BACKEND": "file", "EMAIL_FILE_DIR": self.mail_dir.name,
                                                "EMAIL_DELAY_SECONDS": "0", "EMAIL_FROM": "Линия <desk@example.com>",
                                                "EMAIL_REPLY_TO": "support@example.com", "EMAIL_INBOUND_SECRET": "inbound-secret",
                                                "APP_PUBLIC_URL": "http://testserver"})
        self.env.start()
        with service.db() as conn:
            for table in ("email_outbox", "email_tokens", "email_inbound", "digest_log", "email_preferences", "customer_reminders",
                          "message_reads", "service_entries", "attachments", "hour_requests", "time_entries", "chat_ticket_links",
                          "chat_notifications", "chat_messages", "chats", "notifications", "estimates", "ticket_events", "messages",
                          "tickets", "organization_members", "organizations", "customer_profiles", "sessions", "users"):
                conn.execute(f"DELETE FROM {table}")
            service.create_user(conn, "Admin", "admin@example.com", "password123", "admin")
        self.admin, self.customer, self.employee = TestClient(service.app), TestClient(service.app), TestClient(service.app)
        self.admin.post("/api/login", json={"email": "admin@example.com", "password": "password123"})
        self.customer_user = self.customer.post("/api/register", json={"name": "Клиент", "email": "c@example.com", "password": "password123"}).json()
        self.staff = self.admin.post("/api/staff", json={"name": "Инженер", "email": "w@example.com", "password": "password123"}).json()
        self.employee.post("/api/login", json={"email": "w@example.com", "password": "password123"})

    def tearDown(self):
        self.env.stop()
        self.mail_dir.cleanup()

    def ticket(self):
        ticket_id = self.customer.post("/api/tickets", json={"title": "Интеграция", "description": "Связать CRM и сайт"}).json()["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id": self.staff["id"]})
        return ticket_id

    def approved_ticket(self):
        ticket_id = self.ticket()
        estimate = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 120, "assessment_minutes": 10}).json()
        self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id": estimate["id"], "action": "approve"})
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "working"}).status_code, 200)
        self.employee.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes": 60, "note": "Сделали обмен"})
        return ticket_id

    def sent_mail(self):
        service.deliver_emails()
        return [BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in sorted(Path(self.mail_dir.name).glob("*.eml"))]

    def test_reply_to_message_and_read_receipts(self):
        ticket_id = self.ticket()
        question = self.employee.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Какая у вас CRM?", "request_id": "staff-question"}).json()
        other = self.ticket()
        foreign = self.employee.post(f"/api/tickets/{other}/messages", json={"body": "Чужое", "request_id": "staff-foreign"}).json()
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/messages", json={"body": "x", "request_id": "bad-reply-1", "reply_to_id": foreign["id"]}).status_code, 422)
        answer = self.customer.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Битрикс24", "request_id": "customer-answer", "reply_to_id": question["id"]})
        self.assertEqual(answer.status_code, 201)
        self.assertEqual(answer.json()["reply_body"], "Какая у вас CRM?")
        self.assertEqual(answer.json()["reply_author_name"], "Инженер")
        self.assertEqual(self.employee.get(f"/api/tickets/{ticket_id}").json()["read_state"]["customer_read_id"], answer.json()["id"])
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["read_state"]["team_read_id"], question["id"])
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/read", json={}).json()["team_read_id"], answer.json()["id"])
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["read_state"]["team_read_id"], answer.json()["id"])
        unread = [n for n in self.employee.get("/api/notifications").json() if n["ticket_id"] == ticket_id and not n["read_at"]]
        self.assertEqual(unread, [])
        chat = self.customer.post("/api/chats").json()
        first = self.customer.post(f"/api/chats/{chat['id']}/messages", json={"body": "Привет", "request_id": "chat-first"}).json()
        reply = self.admin.post(f"/api/chats/{chat['id']}/messages", json={"body": "Здравствуйте", "request_id": "chat-reply", "reply_to_id": first["id"]}).json()
        self.assertEqual(reply["reply_body"], "Привет")
        self.assertEqual(self.customer.post(f"/api/chats/{chat['id']}/read", json={}).json()["customer_read_id"], reply["id"])

    def test_customer_accepts_or_returns_work(self):
        ticket_id = self.approved_ticket()
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "closed"}).status_code, 403)
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "done"}).status_code, 200)
        waiting = self.customer.get("/api/waiting-on-me").json()
        self.assertEqual([(w["ticket_id"], w["kind"]) for w in waiting], [(ticket_id, "acceptance")])
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/acceptance", json={"action": "accept"}).status_code, 403)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/acceptance", json={"action": "return"}).status_code, 422)
        returned = self.customer.post(f"/api/tickets/{ticket_id}/acceptance", json={"action": "return", "comment": "Не уходят заказы"})
        self.assertEqual(returned.json()["status"], "working")
        detail = self.customer.get(f"/api/tickets/{ticket_id}").json()
        self.assertIn("Возврат на доработку: Не уходят заказы", detail["messages"][-1]["body"])
        self.assertIn("acceptance", {e["kind"] for e in detail["events"]})
        self.assertIn("вернул", self.employee.get("/api/notifications").json()[0]["text"])
        self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "done"})
        accepted = self.customer.post(f"/api/tickets/{ticket_id}/acceptance", json={"action": "accept"}).json()
        self.assertEqual(accepted["status"], "closed")
        self.assertIsNotNone(accepted["accepted_at"])
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/acceptance", json={"action": "accept"}).status_code, 409)
        self.assertEqual(self.customer.get("/api/waiting-on-me").json(), [])

    def test_waiting_block_and_reminders(self):
        ticket_id = self.ticket()
        self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 90, "assessment_minutes": 5})
        waiting = self.customer.get("/api/waiting-on-me").json()
        self.assertEqual(waiting[0]["kind"], "estimate")
        self.assertIn("1,5 ч", waiting[0]["detail"])
        self.assertEqual(self.employee.get("/api/waiting-on-me").json(), [])
        self.assertEqual(service.run_reminders(), 0)
        with service.db() as conn:
            conn.execute("UPDATE estimates SET created_at=? WHERE ticket_id=?", (ago(days=3), ticket_id))
        self.assertEqual(service.run_reminders(), 1)
        self.assertEqual(service.run_reminders(), 0)
        reminder = self.customer.get("/api/notifications").json()[0]
        self.assertEqual(reminder["kind"], "reminder")
        self.assertIn("3 дня", reminder["text"])
        later = datetime.now(timezone.utc) + timedelta(days=4)
        self.assertEqual(service.run_reminders(later), 1)

        question = self.ticket()
        self.employee.patch(f"/api/tickets/{question}/status", json={"status": "waiting"})
        with service.db() as conn:
            conn.execute("UPDATE ticket_events SET created_at=? WHERE ticket_id=? AND new_value='waiting'", (ago(days=10), question))
        for step in range(3):
            service.run_reminders(datetime.now(timezone.utc) + timedelta(days=4 * step))
        silent = [n for n in self.employee.get("/api/notifications").json() if n["kind"] == "customer_silent"]
        self.assertEqual(len(silent), 1)
        queue = {item["id"]: item for item in self.employee.get("/api/work-queue").json() if item["source"] == "ticket"}
        self.assertEqual(queue[question]["next_action"], "Заказчик молчит — предложите закрыть заявку")
        self.customer.post(f"/api/tickets/{question}/messages", json={"body": "Вот ответ", "request_id": "late-answer"})
        self.assertNotIn(question, [w["ticket_id"] for w in self.customer.get("/api/waiting-on-me").json()])

    def test_meeting_summary_is_visible_to_client_without_minutes(self):
        ticket_id = self.ticket()
        payload = {"customer_id": self.customer_user["id"], "ticket_id": ticket_id, "kind": "call", "minutes": 30, "note": "Внутренняя заметка"}
        self.assertEqual(self.employee.post("/api/service-entries", json={**payload, "share": True}).status_code, 422)
        entry = self.employee.post("/api/service-entries", json={**payload, "summary": "Договорились о формате обмена", "next_steps": "Пришлём схему", "share": True}).json()
        self.assertIsNotNone(entry["shared_at"])
        summaries = self.customer.get(f"/api/tickets/{ticket_id}").json()["meeting_summaries"]
        self.assertEqual(summaries[0]["client_summary"], "Договорились о формате обмена")
        self.assertNotIn("minutes", summaries[0])
        self.assertNotIn("note", summaries[0])
        self.assertEqual(self.customer.get("/api/notifications").json()[0]["kind"], "meeting_summary")
        private = self.employee.post("/api/service-entries", json={**payload, "ticket_id": None, "note": "Созвон без заявки"}).json()
        self.assertEqual(self.customer.patch(f"/api/service-entries/{private['id']}/summary", json={"summary": "x" * 5}).status_code, 403)
        self.employee.patch(f"/api/service-entries/{private['id']}/summary", json={"summary": "Обсудили планы на квартал"})
        chat_id = self.customer.get("/api/chats").json()[0]["id"]
        chat = self.customer.get(f"/api/chats/{chat_id}").json()
        self.assertEqual(chat["meeting_summaries"][0]["client_summary"], "Обсудили планы на квартал")
        self.assertEqual(chat["service_entries"], [])

    def test_email_notification_actions_and_reply(self):
        ticket_id = self.ticket()
        self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 120, "assessment_minutes": 10, "note": "Обмен заказами"})
        mails = self.sent_mail()
        self.assertEqual(len(mails), 1)
        mail = mails[0]
        self.assertEqual(mail["To"], "c@example.com")
        self.assertEqual(mail["Reply-To"], "support@example.com")
        html_body = mail.get_body(preferencelist=("html",)).get_content()
        self.assertIn("Одобрить оценку", html_body)
        link = html_body.split('href="http://testserver/email/a/')[1].split('"')[0]
        visitor = TestClient(service.app)
        self.assertEqual(visitor.get(f"/email/a/{link}").status_code, 200)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["estimates"][0]["state"], "pending")
        self.assertEqual(visitor.post(f"/email/a/{link}").status_code, 200)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["estimates"][0]["state"], "approved")
        self.assertEqual(visitor.post(f"/email/a/{link}").status_code, 410)

        reply = f"""From: Клиент <c@example.com>
To: support@example.com
Subject: Re: {mail['Subject']}
Message-ID: <answer-1@mail.example>
In-Reply-To: {mail['Message-ID']}
Content-Type: text/plain; charset=utf-8

Схему пришлю завтра.

Вт, 2 окт. 2026 г. в 14:05, Линия <desk@example.com>:
> Оценка заявки готова
""".encode()
        self.assertEqual(service.process_inbound_email(reply), "posted")
        self.assertEqual(service.process_inbound_email(reply), "duplicate")
        body = self.employee.get(f"/api/tickets/{ticket_id}").json()["messages"][-1]["body"]
        self.assertEqual(body, "Схему пришлю завтра.")
        spoofed = reply.replace(b"c@example.com>", b"evil@example.com>").replace(b"answer-1", b"answer-2")
        self.assertEqual(service.process_inbound_email(spoofed), "sender_mismatch")
        forbidden = TestClient(service.app).post("/api/email/inbound", content=reply, headers={"X-Inbound-Secret": "wrong"})
        self.assertEqual(forbidden.status_code, 403)

    def test_email_skipped_when_seen_and_preferences(self):
        ticket_id = self.ticket()
        with mock.patch.dict(os.environ, {"EMAIL_DELAY_SECONDS": "3600"}):
            self.employee.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Первое", "request_id": "m-first"})
            self.employee.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Второе", "request_id": "m-second"})
        with service.db() as conn:
            rows = conn.execute("SELECT payload FROM email_outbox WHERE user_id=?", (self.customer_user["id"],)).fetchall()
            self.assertEqual(len(rows), 1)
            conn.execute("UPDATE email_outbox SET available_at=0")
        self.customer.post(f"/api/tickets/{ticket_id}/read", json={})
        self.assertEqual(self.sent_mail(), [])
        prefs = self.customer.get("/api/email/preferences").json()
        self.assertTrue(prefs["notify"] and prefs["digest"] and prefs["available"])
        self.assertFalse(self.employee.get("/api/email/preferences").json()["notify"])
        self.assertEqual(self.customer.put("/api/email/preferences", json={"notify": False, "digest": True, "digest_emails": ["boss@example.com", "bad"]}).status_code, 422)
        saved = self.customer.put("/api/email/preferences", json={"notify": False, "digest": True, "digest_emails": ["Boss@Example.com"]}).json()
        self.assertEqual(saved["digest_emails"], ["boss@example.com"])
        self.employee.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Третье", "request_id": "m-third"})
        with service.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM email_outbox WHERE state='pending'").fetchone()[0], 0)

    def test_monthly_digest(self):
        ticket_id = self.approved_ticket()
        self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "done"})
        self.customer.post(f"/api/tickets/{ticket_id}/acceptance", json={"action": "accept"})
        self.ticket()
        self.customer.put("/api/email/preferences", json={"notify": True, "digest": True, "digest_emails": ["boss@example.com"]})
        preview = self.customer.get("/api/digest/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Что сделано", preview.text)
        self.assertIn("Что в работе", preview.text)
        self.assertEqual(self.employee.get("/api/digest/preview").status_code, 403)
        next_month = datetime.now(timezone.utc).replace(day=1, hour=9) + timedelta(days=32)
        first_day = next_month.replace(day=1, hour=10)
        self.assertEqual(service.run_digests(first_day.replace(day=2)), 0)
        self.assertEqual(service.run_digests(first_day), 1)
        self.assertEqual(service.run_digests(first_day), 0)
        digests = [m for m in self.sent_mail() if m["Subject"].startswith("Сводка")]
        self.assertEqual(sorted(m["To"] for m in digests), ["boss@example.com", "c@example.com"])
        self.assertIn("List-Unsubscribe", digests[0])

    def test_strip_quoted_reply(self):
        self.assertEqual(mailer.strip_quoted("Готово\n\n-- \nПодпись"), "Готово")
        self.assertEqual(mailer.strip_quoted("Да\nOn Mon, Oct 2, 2026 at 2:05 PM Desk <a@b.c> wrote:\n> old"), "Да")
        self.assertEqual(mailer.strip_quoted("Ок\n02.10.2026, 14:05, \"Линия\" <desk@example.com>:\n> old"), "Ок")

    def staff_ticket(self, **extra):
        payload = {"title": "Обновить сертификат", "description": "Сертификат сайта истекает", "customer_id": self.customer_user["id"]}
        return self.admin.post("/api/tickets", json=payload | extra)

    def test_staff_ticket_with_estimate_needs_only_approval(self):
        self.assertEqual(self.staff_ticket(effort_minutes=90).status_code, 422)
        self.assertEqual(self.customer.post("/api/tickets", json={"title": "Своя", "description": "Своя заявка",
                                                                  "effort_minutes": 60}).status_code, 403)
        ticket_id = self.staff_ticket(assignee_id=self.staff["id"], effort_minutes=90, estimate_note="Замена и проверка").json()["id"]
        detail = self.customer.get(f"/api/tickets/{ticket_id}").json()
        estimate = detail["estimates"][0]
        self.assertEqual((estimate["state"], estimate["effort_minutes"], estimate["note"]), ("pending", 90, "Замена и проверка"))
        self.assertTrue(detail["ticket"]["can_decline"])
        notes = self.customer.get("/api/notifications").json()
        self.assertTrue(any(f"Согласуйте оценку: {service.fmt_hours(90)}" in n["text"] for n in notes))
        self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id": estimate["id"], "action": "approve"})
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "working"}).status_code, 200)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/decline", json={}).status_code, 409)

    def test_customer_declines_ticket_created_for_him(self):
        own = self.ticket()
        self.assertEqual(self.customer.post(f"/api/tickets/{own}/decline", json={}).status_code, 409)
        ticket_id = self.staff_ticket(assignee_id=self.staff["id"], effort_minutes=60).json()["id"]
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/decline", json={}).status_code, 403)
        result = self.customer.post(f"/api/tickets/{ticket_id}/decline", json={"comment": "Уже продлили сами"})
        self.assertEqual(result.json()["status"], "closed")
        detail = self.employee.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual(detail["estimates"][0]["state"], "rejected")
        self.assertTrue(detail["ticket"]["declined"])
        self.assertIn("Уже продлили сами", detail["messages"][-1]["body"])
        self.assertTrue(any("отказался" in n["text"] for n in self.employee.get("/api/notifications").json()))

    def test_decline_from_email_link(self):
        ticket_id = self.staff_ticket(assignee_id=self.staff["id"], effort_minutes=60).json()["id"]
        with service.db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (self.customer_user["id"],)).fetchone()
            url = service.action_url(conn, user["id"], "decline_ticket", ticket_id=ticket_id)
        path = url.split("testserver", 1)[1]
        self.assertIn("Отказаться от заявки", self.customer.get(path).text)
        self.assertEqual(self.customer.post(path).status_code, 200)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["ticket"]["status"], "closed")

    def test_auto_approve_within_customer_limit(self):
        self.customer.patch("/api/customer-profile/me", json={"name": "Клиент", "auto_approve_minutes": 120})
        self.assertEqual(self.customer.get("/api/customer-profile/me").json()["auto_approve_minutes"], 120)
        small = self.staff_ticket(assignee_id=self.staff["id"], effort_minutes=90).json()["id"]
        self.assertEqual(self.customer.get(f"/api/tickets/{small}").json()["estimates"][0]["state"], "approved")
        self.assertEqual(self.employee.patch(f"/api/tickets/{small}/status", json={"status": "working"}).status_code, 200)
        big = self.ticket()
        self.employee.post(f"/api/tickets/{big}/estimates", json={"effort_minutes": 180, "assessment_minutes": 5})
        self.assertEqual(self.customer.get(f"/api/tickets/{big}").json()["estimates"][0]["state"], "pending")
        # Профиль без поля лимита не сбрасывает его.
        self.customer.patch("/api/customer-profile/me", json={"name": "Клиент"})
        self.assertEqual(self.customer.get("/api/customer-profile/me").json()["auto_approve_minutes"], 120)

    def test_bulk_approve_and_estimate_sla(self):
        first, second = self.ticket(), self.ticket()
        ids = [self.employee.post(f"/api/tickets/{t}/estimates", json={"effort_minutes": 60, "assessment_minutes": 5}).json()["id"]
               for t in (first, second)]
        detail = self.customer.get(f"/api/tickets/{first}").json()["ticket"]
        self.assertEqual((detail["estimate_state"], detail["effort_minutes"]), ("pending", 60))
        waiting = [w for w in self.customer.get("/api/waiting-on-me").json() if w["kind"] == "estimate"]
        self.assertEqual(sum(w["effort_minutes"] for w in waiting), 120)
        self.assertEqual(self.employee.post("/api/estimates/approve", json={"estimate_ids": ids}).status_code, 403)
        self.assertEqual(self.customer.post("/api/estimates/approve", json={"estimate_ids": ids}).json()["approved"], 2)
        self.assertEqual(self.customer.post("/api/estimates/approve", json={"estimate_ids": ids}).status_code, 409)
        self.assertEqual([w for w in self.customer.get("/api/waiting-on-me").json() if w["kind"] == "estimate"], [])

    def test_ticket_templates(self):
        self.assertEqual(self.customer.get("/api/ticket-templates").status_code, 403)
        created = self.employee.post("/api/ticket-templates", json={"name": "SSL", "title": "Продлить SSL", "description": "Продлить сертификат",
                                                                    "service_type": "support", "effort_minutes": 90}).json()
        self.assertEqual([t["name"] for t in self.admin.get("/api/ticket-templates").json()], ["SSL"])
        other = TestClient(service.app)
        self.admin.post("/api/staff", json={"name": "Второй", "email": "w2@example.com", "password": "password123"})
        other.post("/api/login", json={"email": "w2@example.com", "password": "password123"})
        self.assertEqual(other.delete(f"/api/ticket-templates/{created['id']}").status_code, 403)
        self.assertEqual(self.admin.delete(f"/api/ticket-templates/{created['id']}").status_code, 200)
        self.assertEqual(self.employee.get("/api/ticket-templates").json(), [])


if __name__ == "__main__":
    unittest.main()
