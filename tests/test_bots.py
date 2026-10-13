import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

_initial = tempfile.TemporaryDirectory()
os.environ["APP_DB"] = str(Path(_initial.name) / "initial.db")
import app as desk
from bot_providers import DeliveryError, ProviderClient, normalize
from bot_service import BotEngine
from bot_worker import claim, deliver_one


ENV = {"APP_PUBLIC_URL": "https://desk.example.com",
       "TELEGRAM_BOT_TOKEN": "test-telegram", "TELEGRAM_WEBHOOK_SECRET": "t" * 40,
       "TELEGRAM_BOT_URL": "https://t.me/test_desk_bot",
       "MAX_BOT_TOKEN": "test-max", "MAX_WEBHOOK_SECRET": "m" * 40,
       "MAX_BOT_URL": "https://max.ru/test_desk_bot"}


class Bots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = desk.DB_PATH
        desk.DB_PATH = Path(self.temp.name) / "bots.db"
        desk.init_db()
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.client = TestClient(desk.app)
        self.other = TestClient(desk.app)
        self.user = self.client.post("/api/register", json={"name": "Заказчик", "email": "customer@example.com", "password": "password123"}).json()
        self.other_user = self.other.post("/api/register", json={"name": "Другой", "email": "other@example.com", "password": "password123"}).json()
        with desk.db() as conn:
            self.staff = dict(desk.create_user(conn, "Менеджер", "staff@example.com", "password123", "admin"))
        self.admin = TestClient(desk.app)
        self.admin.post("/api/login", json={"email": "staff@example.com", "password": "password123"})
        self.sequence = 0
        self.engine = desk.bot_engine

    def tearDown(self):
        self.client.close()
        self.other.close()
        self.admin.close()
        self.env.stop()
        desk.DB_PATH = self.old_db
        self.temp.cleanup()

    def update(self, provider="telegram", text="", token=None, external=101, reply=None, group=False):
        self.sequence += 1
        if provider == "telegram":
            message = {"message_id": self.sequence, "chat": {"id": external, "type": "group" if group else "private"},
                       "from": {"id": external, "first_name": "Тест", "is_bot": False}, "text": text}
            if reply:
                message["reply_to_message"] = {"message_id": reply}
            if token:
                return {"update_id": self.sequence, "callback_query": {"id": "cb" + str(self.sequence), "from": message["from"], "message": message, "data": token}}
            return {"update_id": self.sequence, "message": message}
        message = {"sender": {"user_id": external, "first_name": "Тест", "is_bot": False},
                   "recipient": {"chat_id": external + 1000, "chat_type": "chat" if group else "dialog"},
                   "body": {"mid": "mid" + str(self.sequence), "text": text}, "timestamp": self.sequence}
        if reply:
            message["link"] = {"type": "reply", "message": {"mid": str(reply), "text": "Previous"}}
        if token:
            return {"update_type": "message_callback", "timestamp": self.sequence, "message": message,
                    "callback": {"callback_id": "cb" + str(self.sequence), "payload": token, "user": message["sender"]}}
        return {"update_type": "message_created", "timestamp": self.sequence, "message": message}

    def send(self, provider="telegram", text="", token=None, external=101, reply=None):
        update = self.update(provider, text, token, external, reply)
        result = self.engine.receive(provider, update)
        return update, result

    def link(self, provider="telegram", client=None, external=101):
        client = client or self.client
        response = client.post(f"/api/bots/{provider}/pairing")
        self.assertEqual(response.status_code, 200, response.text)
        self.send(provider, response.json()["command"], external=external)
        code = self.last_payload(provider)["text"].split("подтверждения: ")[1].split(".")[0]
        confirmed = client.post(f"/api/bots/{provider}/confirm", json={"code": code})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        with desk.db() as conn:
            return dict(conn.execute("SELECT * FROM bot_links WHERE provider=? AND external_id=?", (provider, str(external))).fetchone())

    def last_payload(self, provider="telegram"):
        with desk.db() as conn:
            rows = conn.execute("SELECT payload FROM bot_outbox WHERE provider=? ORDER BY id DESC", (provider,)).fetchall()
            return next(json.loads(r["payload"]) for r in rows if not json.loads(r["payload"]).get("ack"))

    def test_customer_bot_uses_support_identity_in_history_and_notifications(self):
        for provider in ("telegram", "max"):
            link = self.link(provider)
            with desk.db() as conn:
                conn.execute("UPDATE bot_preferences SET channel='both' WHERE user_id=?", (self.user["id"],))
            ticket = self.client.post("/api/tickets", json={"title": "Проверка подписи", "description": "Ответ службы поддержки"}).json()
            self.admin.post(f"/api/tickets/{ticket['id']}/messages", json={"body": "Проверяем заявку", "request_id": f"privacy-{provider}"})
            payload = self.last_payload(provider)
            self.assertIn("Служба поддержки", payload["text"])
            self.assertNotIn("Менеджер", payload["text"])
            with desk.db() as conn:
                self.engine.history(conn, link, self.user, "ticket", ticket["id"])
                payloads = [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM bot_outbox WHERE provider=?", (provider,))]
            history = [p["text"] for p in payloads if "Проверяем заявку" in p.get("text", "")]
            self.assertTrue(history)
            self.assertTrue(all("Служба поддержки" in text and "Менеджер" not in text for text in history))

    def button(self, text, provider="telegram"):
        return next(b["token"] for row in self.last_payload(provider)["buttons"] for b in row if b["text"] == text)

    def click(self, text, provider="telegram", external=101):
        return self.send(provider, token=self.button(text, provider), external=external)

    def sql(self, query, params=()):
        with desk.db() as conn:
            return [dict(r) for r in conn.execute(query, params)]

    def ticket(self, title="Тестовая заявка"):
        result = self.client.post("/api/tickets", json={"title": title, "description": "Описание задачи"})
        self.assertEqual(result.status_code, 201)
        return result.json()["id"]

    def estimate(self, ticket):
        self.admin.patch(f"/api/tickets/{ticket}/assignee", json={"assignee_id": self.staff["id"]})
        result = self.admin.post(f"/api/tickets/{ticket}/estimates", json={"effort_minutes": 150, "assessment_minutes": 10, "note": "Настроим доступ"})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["id"]

    def test_customer_accepts_or_returns_work_in_bot(self):
        self.link()
        ticket = self.ticket()
        estimate = self.estimate(ticket)
        self.client.post(f"/api/tickets/{ticket}/estimates/decision", json={"estimate_id": estimate, "action": "approve"})
        self.admin.patch(f"/api/tickets/{ticket}/status", json={"status": "working"})
        self.admin.post(f"/api/tickets/{ticket}/time-entries", json={"minutes": 60, "note": "Готово"})
        self.admin.patch(f"/api/tickets/{ticket}/status", json={"status": "done"})
        self.show_ticket(ticket)
        self.click("Вернуть на доработку")
        self.send(text="Не работает экспорт")
        self.assertEqual(self.sql("SELECT status FROM tickets WHERE id=?", (ticket,))[0]["status"], "working")
        self.assertEqual(self.sql("SELECT body FROM messages WHERE ticket_id=? ORDER BY id DESC", (ticket,))[0]["body"], "Возврат на доработку: Не работает экспорт")
        self.admin.patch(f"/api/tickets/{ticket}/status", json={"status": "done"})
        self.show_ticket(ticket)
        self.click("Принять работу")
        self.click("Принять")
        self.assertEqual(self.sql("SELECT status FROM tickets WHERE id=?", (ticket,))[0]["status"], "closed")

    def test_customer_declines_staff_ticket_in_bot(self):
        self.link()
        ticket = self.admin.post("/api/tickets", json={"title": "Продлить домен", "description": "Домен истекает",
                                                      "customer_id": self.user["id"], "assignee_id": self.staff["id"],
                                                      "effort_minutes": 30}).json()["id"]
        own = self.ticket()
        self.show_ticket(own)
        self.assertNotIn("Заявка не нужна", [b["text"] for row in self.last_payload()["buttons"] for b in row])
        self.show_ticket(ticket)
        self.click("Заявка не нужна")
        self.click("Да, не нужна")
        self.assertEqual(self.sql("SELECT status FROM tickets WHERE id=?", (ticket,))[0]["status"], "closed")

    def show_ticket(self, ticket, provider="telegram"):
        link = self.sql("SELECT * FROM bot_links WHERE provider=? AND user_id=?", (provider, self.user["id"]))[0]
        with desk.db() as conn:
            self.engine.ticket(conn, link, self.user, ticket)

    def test_secure_pairing_requires_web_confirmation_and_expires(self):
        self.assertEqual(TestClient(desk.app).post("/api/bots/telegram/pairing").status_code, 401)
        pairing = self.client.post("/api/bots/telegram/pairing").json()
        self.send(text=pairing["command"])
        self.assertEqual(self.sql("SELECT * FROM bot_links"), [])
        self.assertEqual(self.other.post("/api/bots/telegram/confirm", json={"code": "ABCDEF"}).status_code, 409)
        self.assertEqual(self.client.post("/api/bots/telegram/confirm", json={"code": "000000"}).status_code, 422)
        with desk.db() as conn:
            conn.execute("UPDATE bot_pairings SET expires_at=0")
        self.send(text=pairing["command"], external=202)
        self.assertIn("недействителен", self.last_payload()["text"])
        self.assertEqual(self.client.post("/api/bots/telegram/confirm", json={"code": "ABCDEF"}).status_code, 409)
        self.link()
        self.assertEqual(self.client.get("/api/bots").json()["channel"], "telegram")

    def test_both_providers_create_one_ticket_despite_replay_and_double_click(self):
        for provider in ("telegram", "max"):
            with self.subTest(provider=provider):
                self.link(provider)
                self.click("Создать заявку", provider)
                self.send(provider, "Настроить доступ")
                # New engine instance proves the wizard is not process-local.
                self.engine = BotEngine(desk)
                self.send(provider, "Проверить роли сотрудников")
                token = self.button("Отправить заявку", provider)
                update, _ = self.send(provider, token=token)
                self.assertTrue(self.engine.receive(provider, update)["duplicate"])
                self.send(provider, token=token)
                self.assertIn("устарела", self.last_payload(provider)["text"])
        self.assertEqual(len(self.sql("SELECT * FROM tickets")), 2)

    def test_concurrent_replay_is_atomic(self):
        self.link()
        self.click("Создать заявку")
        self.send(text="Новая задача")
        self.send(text="Полное описание задачи")
        update = self.update(token=self.button("Отправить заявку"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.engine.receive("telegram", update), range(2)))
        self.assertEqual(sum(bool(r.get("duplicate")) for r in results), 1)
        self.assertEqual(len(self.sql("SELECT * FROM tickets")), 1)

    def test_draft_edit_validation_cancel_and_group_ignore(self):
        self.link()
        self.click("Создать заявку")
        self.send(text="ab")
        self.assertIn("3–140", self.last_payload()["text"])
        self.send(text="Исходная тема")
        self.send(text="Полное описание")
        self.click("Изменить тему")
        self.send(text="Исправленная тема")
        self.assertIn("Исправленная тема", self.last_payload()["text"])
        self.send(text="/cancel")
        self.engine.receive("telegram", self.update(text="/start", group=True))
        self.assertEqual(self.sql("SELECT * FROM tickets"), [])

    def test_ambiguous_text_and_native_replies_do_not_mix_conversations(self):
        for provider in ("telegram", "max"):
            with self.subTest(provider=provider):
                link = self.link(provider)
                first = self.ticket("Первая задача")
                second = self.ticket("Вторая задача")
                self.send(provider, "Куда попадёт сообщение?")
                self.assertIn("Куда отправить", self.last_payload(provider)["text"])
                self.click("В общий чат", provider)
                self.assertEqual(len(self.sql("SELECT * FROM chat_messages WHERE body='Куда попадёт сообщение?'")), 1 if provider == "telegram" else 2)
                self.show_ticket(second, provider)
                self.click(f"Ответить по заявке №{second}", provider)
                with desk.db() as conn:
                    conn.execute("INSERT INTO bot_sent VALUES(?,?,?,?,?,?)", (provider, link["chat_id"], "555", link["id"], "ticket", first))
                update, _ = self.send(provider, "Ответ на первую", reply=555)
                self.engine.receive(provider, update)
                self.assertEqual(len(self.sql("SELECT * FROM messages WHERE ticket_id=?", (first,))), 1)
                self.assertEqual(self.sql("SELECT * FROM messages WHERE ticket_id=?", (second,)), [])
                self.send(provider, "Неизвестный ответ", reply=999)
                self.assertIn("Куда отправить", self.last_payload(provider)["text"])

    def test_foreign_callback_and_revoked_link_are_denied(self):
        self.link()
        token = self.button("Создать заявку")
        self.link(client=self.other, external=202)
        self.send(token=token, external=202)
        self.assertIn("недоступна", self.last_payload()["text"])
        self.client.delete("/api/bots/telegram")
        self.send(token=token)
        self.assertIn("зарегистрируйтесь", self.last_payload()["text"])
        self.assertEqual(self.sql("SELECT * FROM tickets"), [])

    def test_estimate_confirmation_across_messengers_and_stale_buttons(self):
        self.link()
        self.link("max")
        ticket = self.ticket()
        estimate = self.estimate(ticket)
        self.show_ticket(ticket)
        self.click("Одобрить")
        confirm = self.button("Подтвердить")
        self.assertEqual(self.sql("SELECT state FROM estimates WHERE id=?", (estimate,))[0]["state"], "pending")
        self.show_ticket(ticket, "max")
        self.click("Одобрить", "max")
        self.click("Подтвердить", "max")
        self.send(token=confirm)
        self.assertEqual(self.sql("SELECT state FROM estimates WHERE id=?", (estimate,))[0]["state"], "approved")
        self.assertEqual(len(self.sql("SELECT * FROM notifications WHERE kind='estimate_decision'")), 1)

    def test_revision_with_hours_and_rejection(self):
        self.link()
        ticket = self.ticket()
        estimate = self.estimate(ticket)
        self.show_ticket(ticket)
        self.click("Запросить корректировку")
        self.send(text="Нужен меньший объём")
        self.send(text="NaN")
        self.assertIn("положительное", self.last_payload()["text"])
        self.send(text="2,5")
        row = self.sql("SELECT * FROM estimates WHERE id=?", (estimate,))[0]
        self.assertEqual(row["state"], "revision_requested")
        self.assertEqual(row["proposed_effort_minutes"], 150)
        new_id = self.estimate(ticket)
        self.show_ticket(ticket)
        self.click("Отклонить")
        self.click("Подтвердить")
        self.assertEqual(self.sql("SELECT state FROM estimates WHERE id=?", (new_id,))[0]["state"], "rejected")

    def test_notifications_preferences_exact_message_and_no_self_echo(self):
        self.link()
        self.link("max")
        ticket = self.ticket()
        self.admin.patch(f"/api/tickets/{ticket}/assignee", json={"assignee_id": self.staff["id"]})
        self.admin.post(f"/api/tickets/{ticket}/messages", json={"body": "Первый ответ", "request_id": "staff-message-1"})
        notices = self.sql("SELECT provider,payload FROM bot_outbox WHERE notification=1")
        self.assertEqual([r["provider"] for r in notices], ["telegram"])
        self.assertIn("Первый ответ", notices[0]["payload"])
        self.client.put("/api/bots/preferences", json={"channel": "both"})
        self.admin.post(f"/api/tickets/{ticket}/messages", json={"body": "Второй ответ", "request_id": "staff-message-2"})
        self.assertEqual(len(self.sql("SELECT * FROM bot_outbox WHERE notification=1")), 3)
        self.client.post(f"/api/tickets/{ticket}/messages", json={"body": "Спасибо", "request_id": "customer-message-1"})
        self.assertEqual(len(self.sql("SELECT * FROM bot_outbox WHERE notification=1")), 3)

    def test_webhook_security_malformed_limits_and_duplicate(self):
        for provider, header, secret in [("telegram", "X-Telegram-Bot-Api-Secret-Token", "t" * 40), ("max", "X-Max-Bot-Api-Secret", "m" * 40)]:
            path = "/webhooks/" + provider
            update = self.update(provider, "/start")
            self.assertEqual(self.client.post(path, json=update).status_code, 403)
            self.assertEqual(self.client.post(path, json=update, headers={header: "wrong"}).status_code, 403)
            self.assertEqual(self.client.post(path, json=update, headers={header: secret}).status_code, 200)
            self.assertTrue(self.client.post(path, json=update, headers={header: secret}).json()["duplicate"])
            self.assertEqual(self.client.post(path, content="{", headers={header: secret}).status_code, 400)
            self.assertEqual(self.client.post(path, content="x" * 262145, headers={header: secret}).status_code, 413)
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            self.assertEqual(self.client.post("/webhooks/telegram", json={}).status_code, 503)

    def test_worker_retries_records_reply_context_and_honors_revocation(self):
        link = self.link()
        ticket = self.ticket()
        with desk.db() as conn:
            conn.execute("DELETE FROM bot_outbox")
            self.engine.queue(conn, link, "Тест", context=("ticket", ticket))
        class Fake:
            def __init__(self):
                self.calls = 0
            def deliver(self, chat_id, payload):
                self.calls += 1
                if self.calls == 1:
                    raise DeliveryError("api_429", retry_after=30)
                return "sent-1"
        fake = Fake()
        self.assertTrue(deliver_one(self.engine, {"telegram": fake}))
        job = self.sql("SELECT * FROM bot_outbox")[0]
        self.assertEqual(job["state"], "pending")
        self.assertGreater(job["available_at"], time.time() + 20)
        with desk.db() as conn:
            conn.execute("UPDATE bot_outbox SET available_at=0")
            conn.execute("DELETE FROM bot_delivery_slots")
        self.assertTrue(deliver_one(self.engine, {"telegram": fake}))
        self.assertEqual(self.sql("SELECT * FROM bot_sent")[0]["context_id"], ticket)
        self.assertFalse(deliver_one(self.engine, {"telegram": fake}))
        self.client.delete("/api/bots/telegram")
        self.assertEqual(self.sql("SELECT * FROM bot_sent"), [])

    def test_worker_cancels_after_access_loss_and_disabled_user(self):
        link = self.link(client=self.admin, external=303)
        ticket = self.ticket()
        with desk.db() as conn:
            conn.execute("DELETE FROM bot_outbox")
            conn.execute("UPDATE users SET role='employee' WHERE id=?", (self.staff["id"],))
            self.engine.queue(conn, link, "Секретная заявка", context=("ticket", ticket))
        self.assertIsNone(claim(self.engine))
        self.assertEqual(self.sql("SELECT state FROM bot_outbox")[0]["state"], "cancelled")
        with desk.db() as conn:
            self.engine.queue(conn, link, "Приветствие")
            conn.execute("UPDATE users SET active=0 WHERE id=?", (self.staff["id"],))
        self.assertIsNone(claim(self.engine))
        self.assertTrue(all(r["state"] == "cancelled" for r in self.sql("SELECT state FROM bot_outbox")))

    def test_worker_lease_recovery_and_only_selected_provider(self):
        tg = self.link()
        mx = self.link("max")
        with desk.db() as conn:
            conn.execute("DELETE FROM bot_outbox")
            self.engine.queue(conn, mx, "MAX")
            self.engine.queue(conn, tg, "Telegram")
        job = claim(self.engine, {"telegram"})
        self.assertEqual(job["provider"], "telegram")
        self.assertIsNone(claim(self.engine, {"telegram"}))
        with desk.db() as conn:
            conn.execute("UPDATE bot_outbox SET lease_until=0 WHERE id=?", (job["id"],))
            conn.execute("DELETE FROM bot_delivery_slots")
        recovered = claim(self.engine, {"telegram"})
        self.assertEqual(recovered["id"], job["id"])
        self.assertNotEqual(recovered["lease_token"], job["lease_token"])

    def test_staff_only_receives_notifications_and_web_links(self):
        self.link(client=self.admin, external=303)
        self.assertIn("веб-кабинете", self.last_payload()["text"])
        self.send(text="Создай заявку", external=303)
        self.assertEqual(self.sql("SELECT * FROM tickets"), [])
        ticket = self.ticket()
        self.assertTrue(any(f"#ticket/{ticket}" in r["payload"] for r in self.sql("SELECT payload FROM bot_outbox WHERE notification=1")))

    def test_provider_payloads_and_safe_errors(self):
        for provider in ("telegram", "max"):
            captured = []
            def handler(request):
                captured.append(request)
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}} if provider == "telegram" else {"message": {"body": {"mid": "88"}}})
            client = ProviderClient(provider, httpx.MockTransport(handler))
            self.assertEqual(client.deliver("101", {"text": "Текст", "buttons": [[{"text": "Ответить", "token": "opaque"}]]}), "88")
            payload = json.loads(captured[0].content)
            if provider == "max":
                self.assertEqual(captured[0].url.host, "platform-api2.max.ru")
                self.assertEqual(captured[0].headers["authorization"], ENV["MAX_BOT_TOKEN"])
                self.assertEqual(payload["attachments"][0]["payload"]["buttons"][0][0]["payload"], "opaque")
            else:
                self.assertEqual(payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "opaque")
            client.close()
        broken = ProviderClient("telegram", httpx.MockTransport(lambda _: httpx.Response(403, json={"ok": False, "error_code": 403, "description": "private data"})))
        with self.assertRaises(DeliveryError) as error:
            broken.deliver("101", {"text": "Test"})
        self.assertTrue(error.exception.blocked)
        self.assertNotIn("private data", str(error.exception))
        broken.close()

    def test_max_stopped_resumed_and_unsupported_attachments(self):
        link = self.link("max")
        self.engine.receive("max", {"update_type": "bot_stopped", "timestamp": 999, "chat_id": 1101, "user": {"user_id": 101}})
        self.assertEqual(self.sql("SELECT enabled FROM bot_links WHERE id=?", (link["id"],))[0]["enabled"], 0)
        self.engine.receive("max", {"update_type": "bot_started", "timestamp": 1000, "chat_id": 1101, "user": {"user_id": 101}})
        self.assertEqual(self.sql("SELECT enabled FROM bot_links WHERE id=?", (link["id"],))[0]["enabled"], 1)
        update = self.update("max", "Подпись")
        update["message"]["body"]["attachments"] = [{"type": "image"}]
        self.engine.receive("max", update)
        self.assertIn("не отправлены", self.last_payload("max")["text"])


if __name__ == "__main__":
    unittest.main()
