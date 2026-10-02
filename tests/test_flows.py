import os
import base64
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


temp = tempfile.TemporaryDirectory()
os.environ["APP_DB"] = str(Path(temp.name) / "test.db")
os.environ["BILLING_ENABLED"] = "1"
import app as service


class Flows(unittest.TestCase):
    def setUp(self):
        with service.db() as conn:
            conn.execute("DELETE FROM service_entries")
            conn.execute("DELETE FROM billing_transactions")
            conn.execute("DELETE FROM ticket_git_links")
            conn.execute("DELETE FROM attachments")
            conn.execute("DELETE FROM hour_requests")
            conn.execute("DELETE FROM time_entries")
            conn.execute("DELETE FROM chat_ticket_links")
            conn.execute("DELETE FROM chat_notifications")
            conn.execute("DELETE FROM chat_messages")
            conn.execute("DELETE FROM chats")
            conn.execute("DELETE FROM notifications")
            conn.execute("DELETE FROM estimates")
            conn.execute("DELETE FROM ticket_events")
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM tickets")
            conn.execute("DELETE FROM invoices")
            conn.execute("DELETE FROM organization_members")
            conn.execute("DELETE FROM organizations")
            conn.execute("DELETE FROM customer_profiles")
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM users")
            service.create_user(conn, "Admin", "admin@example.com", "password123", "admin")
        self.admin = TestClient(service.app)
        self.customer = TestClient(service.app)
        self.other = TestClient(service.app)
        self.employee = TestClient(service.app)
        self.assertEqual(self.admin.post("/api/login", json={"email":"admin@example.com","password":"password123"}).status_code, 200)
        self.assertEqual(self.customer.post("/api/register", json={"name":"Customer","email":"c@example.com","password":"password123"}).status_code, 200)
        self.assertEqual(self.other.post("/api/register", json={"name":"Other","email":"o@example.com","password":"password123"}).status_code, 200)
        self.staff = self.admin.post("/api/staff", json={"name":"Worker","email":"w@example.com","password":"password123"}).json()
        self.assertEqual(self.employee.post("/api/login", json={"email":"w@example.com","password":"password123"}).status_code, 200)

    def test_staff_profile_avatar_and_customer_visibility(self):
        self.assertEqual(self.customer.get("/api/profile/me").status_code, 403)
        self.assertEqual(self.customer.patch("/api/profile/me", json={"name":"Client","job_title":"Wrong","bio":""}).status_code, 403)
        updated = self.employee.patch("/api/profile/me", json={"name":"Анна Иванова","job_title":"Ведущий инженер","bio":"Помогаю с интеграциями"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Анна Иванова")
        self.assertEqual(self.employee.get("/api/me").json()["name"], "Анна Иванова")
        self.assertEqual(self.admin.get("/api/staff").json()[1]["job_title"], "Ведущий инженер")
        self.assertEqual(self.employee.patch("/api/profile/me", json={"name":"  ","job_title":"","bio":""}).status_code, 422)
        picture = BytesIO()
        Image.new("RGB", (900, 700), "#b6d9c5").save(picture, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(picture.getvalue()).decode()
        avatar = self.employee.post("/api/profile/me/avatar", json={"data_url": data_url})
        self.assertEqual(avatar.status_code, 200)
        self.assertIn(f"/api/staff/{self.staff['id']}/avatar", avatar.json()["avatar_url"])
        self.assertEqual(self.other.get(f"/api/staff/{self.staff['id']}/avatar").status_code, 404)
        ticket_id = self.customer.post("/api/tickets", json={"title":"Нужна помощь","description":"Подключить систему"}).json()["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]})
        profile = self.customer.get(f"/api/staff/{self.staff['id']}/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["job_title"], "Ведущий инженер")
        self.assertNotIn("email", profile.json())
        image = self.customer.get(f"/api/staff/{self.staff['id']}/avatar")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/webp")
        self.assertLess(Image.open(BytesIO(image.content)).width, 513)
        self.assertEqual(self.employee.post("/api/profile/me/avatar", json={"data_url":"data:image/png;base64," + base64.b64encode(b"not an image" * 3).decode()}).status_code, 422)
        self.assertEqual(self.employee.delete("/api/profile/me/avatar").status_code, 200)
        self.assertIsNone(self.employee.get("/api/profile/me").json()["avatar_url"])
        self.assertEqual(self.customer.get(f"/api/staff/{self.staff['id']}/avatar").status_code, 404)

    def test_customer_profile_and_company_on_ticket(self):
        self.assertEqual(self.employee.get("/api/customer-profile/me").status_code, 403)
        self.assertEqual(self.admin.patch("/api/customer-profile/me", json={"name":"Other","company_name":"Wrong"}).status_code, 403)
        initial = self.customer.get("/api/customer-profile/me").json()
        self.assertEqual(initial["company_name"], "")
        self.assertEqual(self.customer.patch("/api/customer-profile/me", json={
            "name":"  Александр   Волков ", "company_name":" Студия   Север ", "phone":"+7 (999) 123-45-67",
        }).status_code, 200)
        self.assertEqual(self.customer.get("/api/me").json()["name"], "Александр Волков")
        self.assertEqual(self.customer.get("/api/customer-profile/me").json()["company_name"], "Студия Север")
        self.assertEqual(self.customer.patch("/api/customer-profile/me", json={
            "name":"Александр", "phone":"invalid phone",
        }).status_code, 422)
        ticket = self.customer.post("/api/tickets", json={"title":"Проверка профиля","description":"Задача для команды"}).json()
        detail = self.admin.get(f"/api/tickets/{ticket['id']}").json()["ticket"]
        self.assertEqual(detail["customer_company"], "Студия Север")
        self.assertEqual(detail["customer_name"], "Александр Волков")
        self.assertNotIn("phone", detail)
        self.assertEqual(self.other.get(f"/api/tickets/{ticket['id']}").status_code, 404)

    def test_ticket_conversation_and_access(self):
        created = self.customer.post("/api/tickets", json={"title":"Тестовая задача","description":"Нужна помощь с услугой"})
        self.assertEqual(created.status_code, 201)
        ticket_id = created.json()["id"]
        self.assertEqual(self.other.get(f"/api/tickets/{ticket_id}").status_code, 404)
        self.assertEqual(self.other.post(f"/api/tickets/{ticket_id}/messages", json={"body":"Чужое","request_id":"outsider-1"}).status_code, 404)
        self.assertEqual(self.customer.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]}).status_code, 403)
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]}).status_code, 403)
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"working"}).status_code, 404)
        self.assertEqual(self.employee.get(f"/api/tickets/{ticket_id}").status_code, 404)
        self.assertEqual(self.employee.get("/api/tickets").json(), [])
        self.assertEqual(self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]}).status_code, 200)
        self.assertEqual(len(self.employee.get("/api/tickets").json()), 1)
        self.assertEqual(self.employee.get("/api/notifications").json()[0]["kind"], "assignment")
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"working"}).status_code, 409)
        quote = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes":150,"assessment_minutes":45,"note":"Настройка доступа"})
        self.assertEqual(quote.status_code, 201)
        self.assertEqual(quote.json()["effort_minutes"], 150)
        quote_id = quote.json()["id"]
        self.assertEqual(self.other.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id":quote_id,"action":"approve"}).status_code, 404)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id":quote_id,"action":"approve"}).status_code, 200)
        overview_ticket = self.customer.get("/api/tickets").json()[0]
        self.assertEqual((overview_ticket["estimate_state"], overview_ticket["effort_minutes"]), ("approved", 150))
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"working"}).status_code, 200)
        message = {"body":"Здравствуйте","request_id":"customer-1"}
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/messages", json=message).status_code, 201)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/messages", json=message).status_code, 201)
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/messages", json={"body":"Взяли в работу","request_id":"employee-1"}).status_code, 201)
        detail = self.customer.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual(len(detail["messages"]), 2)
        self.assertEqual(len(detail["events"]), 2)
        self.assertEqual(detail["ticket"]["assignee_name"], "Worker")
        self.assertEqual(detail["estimates"][0]["state"], "approved")
        self.assertEqual(len(self.other.get("/api/tickets").json()), 0)
        customer_notifications = self.customer.get("/api/notifications").json()
        self.assertIn("estimate", [n["kind"] for n in customer_notifications])
        self.assertIn("message", [n["kind"] for n in customer_notifications])
        notice_id = customer_notifications[0]["id"]
        self.assertEqual(self.other.post(f"/api/notifications/{notice_id}/read").status_code, 404)
        self.assertEqual(self.customer.post(f"/api/notifications/{notice_id}/read").status_code, 200)
        self.assertIsNotNone(self.customer.get("/api/notifications").json()[0]["read_at"])

    def test_revision_and_rejection(self):
        ticket_id = self.customer.post("/api/tickets", json={"title":"Другая задача","description":"Описание другой задачи"}).json()["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]})
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes":240,"assessment_minutes":5}).status_code, 403)
        first = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes":240,"assessment_minutes":15,"note":"Первый вариант"}).json()
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes":180,"assessment_minutes":15}).status_code, 409)
        revised = self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id":first["id"],"action":"request_revision","comment":"Сократите объём","proposed_effort_minutes":180})
        self.assertEqual(revised.status_code, 200)
        second = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes":195,"assessment_minutes":10,"note":"Сокращённый объём"}).json()
        self.assertEqual(second["version"], 2)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id":first["id"],"action":"approve"}).status_code, 409)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id":second["id"],"action":"reject"}).status_code, 200)
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"working"}).status_code, 409)
        detail = self.customer.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual([x["state"] for x in detail["estimates"]], ["rejected", "revision_requested"])
        self.assertEqual(detail["ticket"]["next_step"], "Ожидаем новую оценку")

    def test_logout_and_origin(self):
        self.assertEqual(self.customer.post("/api/logout").status_code, 200)
        self.assertEqual(self.customer.get("/api/me").status_code, 401)
        blocked = self.admin.post("/api/staff", headers={"Origin":"https://evil.example"}, json={"name":"Bad","email":"bad@example.com","password":"password123"})
        self.assertEqual(blocked.status_code, 403)

    def test_manager_dispatches_and_employee_sees_only_assigned(self):
        manager_data = self.admin.post("/api/staff", json={"name":"Manager","email":"m@example.com","password":"password123","staff_role":"manager"})
        self.assertEqual(manager_data.status_code, 201)
        self.assertTrue(manager_data.json()["is_manager"])
        manager = TestClient(service.app)
        manager.post("/api/login", json={"email":"m@example.com","password":"password123"})
        ticket_id = self.customer.post("/api/tickets", json={"title":"Проверка доступа","description":"Описание проверки доступа"}).json()["id"]
        self.assertEqual(len(manager.get("/api/tickets").json()), 1)
        self.assertEqual(manager.get("/api/notifications").json()[0]["kind"], "new_ticket")
        self.assertEqual(self.employee.get("/api/tickets").json(), [])
        self.assertEqual(self.employee.get(f"/api/tickets/{ticket_id}").status_code, 404)
        self.assertEqual(manager.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]}).status_code, 200)
        self.assertEqual(len(self.employee.get("/api/tickets").json()), 1)
        self.assertEqual(manager.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":None}).status_code, 200)
        self.assertEqual(self.employee.get(f"/api/tickets/{ticket_id}").status_code, 404)
        self.assertEqual(self.employee.get("/api/notifications").json(), [])
        self.assertEqual(manager.post("/api/staff", json={"name":"No","email":"no@example.com","password":"password123"}).status_code, 403)

    def test_general_chat_is_separate_and_private(self):
        chat = self.customer.post("/api/chats")
        self.assertEqual(chat.status_code, 201)
        chat_id = chat.json()["id"]
        self.assertEqual(self.customer.post("/api/chats").json()["id"], chat_id)
        other_chat = self.other.post("/api/chats").json()["id"]
        self.assertNotEqual(chat_id, other_chat)
        self.assertEqual(self.other.get(f"/api/chats/{chat_id}").status_code, 404)
        self.assertEqual(self.employee.get(f"/api/chats/{chat_id}").status_code, 404)
        self.assertEqual([x["id"] for x in self.customer.get("/api/chats").json()], [chat_id])
        self.assertEqual(len(self.admin.get("/api/chats").json()), 2)
        body = {"body":"Здравствуйте, общий вопрос", "request_id":"chat-request-1"}
        self.assertEqual(self.customer.post(f"/api/chats/{chat_id}/messages", json=body).status_code, 201)
        self.assertEqual(self.customer.post(f"/api/chats/{chat_id}/messages", json=body).status_code, 201)
        self.assertEqual(len(self.admin.get("/api/chat-notifications").json()), 3)
        self.assertEqual(self.employee.patch(f"/api/chats/{chat_id}/assignee", json={"assignee_id":self.staff["id"]}).status_code, 403)
        self.assertEqual(self.admin.patch(f"/api/chats/{chat_id}/assignee", json={"assignee_id":self.staff["id"]}).status_code, 200)
        self.assertEqual(len(self.employee.get("/api/chats").json()), 1)
        self.assertEqual(self.employee.post(f"/api/chats/{chat_id}/messages", json={"body":"Добрый день", "request_id":"chat-reply-1"}).status_code, 201)
        detail = self.customer.get(f"/api/chats/{chat_id}").json()
        self.assertEqual([m["body"] for m in detail["messages"]], [body["body"], "Добрый день"])
        self.assertEqual(self.customer.get("/api/tickets").json(), [])
        customer_notice = self.customer.get("/api/chat-notifications").json()[0]
        self.assertEqual(customer_notice["kind"], "message")
        self.assertEqual(self.other.post(f"/api/chat-notifications/{customer_notice['id']}/read").status_code, 404)
        self.assertEqual(self.customer.post(f"/api/chat-notifications/{customer_notice['id']}/read").status_code, 200)
        self.assertIsNotNone(self.customer.get("/api/chat-notifications").json()[0]["read_at"])
        self.admin.patch(f"/api/chats/{chat_id}/assignee", json={"assignee_id":None})
        self.assertEqual(self.employee.get(f"/api/chats/{chat_id}").status_code, 404)
        self.assertEqual(self.employee.get("/api/chat-notifications").json(), [])

    def test_chat_to_ticket_and_shared_queue(self):
        chat_id = self.customer.post("/api/chats").json()["id"]
        message_id = self.customer.post(f"/api/chats/{chat_id}/messages",
                                        json={"body":"Помогите настроить сервис", "request_id":"chat-convert-1"}).json()["id"]
        self.assertEqual(self.customer.post(f"/api/chats/{chat_id}/tickets",
                                            json={"title":"Настроить сервис","message_id":message_id}).status_code, 403)
        self.assertEqual(self.admin.post(f"/api/chats/{chat_id}/tickets",
                                         json={"title":"Не тот чат","message_id":9999}).status_code, 404)
        created = self.admin.post(f"/api/chats/{chat_id}/tickets",
                                  json={"title":"Настроить сервис","message_id":message_id})
        self.assertEqual(created.status_code, 201)
        ticket_id = created.json()["id"]
        repeated = self.admin.post(f"/api/chats/{chat_id}/tickets",
                                   json={"title":"Повтор","message_id":message_id})
        self.assertEqual(repeated.json()["id"], ticket_id)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["ticket"]["description"], "Помогите настроить сервис")
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["linked_chat"]["chat_id"], chat_id)
        self.assertEqual(self.customer.get(f"/api/chats/{chat_id}").json()["linked_tickets"][0]["id"], ticket_id)
        self.assertEqual(self.other.get(f"/api/tickets/{ticket_id}").status_code, 404)
        queue = self.admin.get("/api/work-queue")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual({x["source"] for x in queue.json()}, {"ticket", "chat"})
        self.assertTrue(all(x["next_action"] == "Назначить ответственного" for x in queue.json()))
        self.assertEqual(self.customer.get("/api/work-queue").status_code, 403)
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]})
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["ticket"]["next_step"], "Сотрудник готовит оценку")
        self.employee.post(f"/api/tickets/{ticket_id}/estimates",
                           json={"effort_minutes":120,"assessment_minutes":20})
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["ticket"]["next_step"], "Одобрите оценку трудозатрат")

    def test_staff_creates_ticket_for_customer(self):
        customer_id = self.customer.get("/api/me").json()["id"]
        other_id = self.other.get("/api/me").json()["id"]
        data = {"title":"Настроить услугу","description":"Согласовали настройку по телефону","customer_id":other_id,
                "assignee_id":self.staff["id"]}
        self.assertEqual(self.customer.post("/api/tickets", json=data).status_code, 403)
        self.assertEqual(self.employee.post("/api/tickets", json=data).status_code, 403)
        created = self.admin.post("/api/tickets", json=data)
        self.assertEqual(created.status_code, 201)
        ticket_id = created.json()["id"]
        self.assertEqual(created.json()["created_by_name"], "Admin")
        self.assertEqual(self.other.get(f"/api/tickets/{ticket_id}").status_code, 200)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").status_code, 404)
        self.assertEqual(self.employee.get(f"/api/tickets/{ticket_id}").status_code, 200)
        self.assertEqual(self.other.get("/api/notifications").json()[0]["kind"], "new_ticket")
        self.assertEqual([x["id"] for x in self.employee.get("/api/customers").json()], [other_id])
        own = self.employee.post("/api/tickets", json={"title":"Вторая задача","description":"Дополнительная работа","customer_id":other_id})
        self.assertEqual(own.status_code, 201)
        self.assertEqual(own.json()["assignee_id"], self.staff["id"])
        self.assertEqual(self.employee.post("/api/tickets", json={"title":"Чужая задача","description":"Нет доступа к клиенту","customer_id":customer_id}).status_code, 403)
        self.assertEqual(self.employee.post("/api/tickets", json={**data,"assignee_id":self.admin.get("/api/me").json()["id"]}).status_code, 403)
        self.assertEqual(self.admin.post("/api/tickets", json={"title":"Без клиента","description":"Нет заказчика"}).status_code, 422)

    def test_legacy_money_estimate_requires_new_hours(self):
        ticket_id = self.customer.post("/api/tickets", json={"title":"Старая оценка","description":"Проверка миграции оценки"}).json()["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]})
        with service.db() as conn:
            cursor = conn.execute("""INSERT INTO estimates(ticket_id,author_id,version,amount_minor,
                assessment_minutes,note,state,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (ticket_id,self.staff["id"],1,100000,15,"Старые данные","pending",service.now()))
            old_id = cursor.lastrowid
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision",
                                            json={"estimate_id":old_id,"action":"approve"}).status_code, 409)
        new = self.employee.post(f"/api/tickets/{ticket_id}/estimates",
                                 json={"effort_minutes":180,"assessment_minutes":30})
        self.assertEqual(new.status_code, 201)
        self.assertEqual(new.json()["version"], 2)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["estimates"][1]["state"], "superseded")


    def test_actual_hours_require_approval_for_overrun(self):
        ticket_id = self.customer.post("/api/tickets", json={"title":"Интеграция","description":"Настроить обмен данными"}).json()["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id":self.staff["id"]})
        quote = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes":60,"assessment_minutes":20}).json()
        self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id":quote["id"],"action":"approve"})
        self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"working"})
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"done"}).status_code, 409)
        first = {"minutes":45,"note":"Первый этап","request_id":"time-unique-1"}
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/time-entries", json=first).status_code, 201)
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/time-entries", json=first).status_code, 201)
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes":30,"note":"Второй этап"}).status_code, 409)
        request = self.employee.post(f"/api/tickets/{ticket_id}/hour-requests", json={"minutes":60,"reason":"Нужна доработка API"})
        self.assertEqual(request.status_code, 201)
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/hour-requests", json={"minutes":60,"reason":"Дубликат"}).status_code, 409)
        self.assertEqual(self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status":"done"}).status_code, 409)
        self.assertEqual(self.other.post(f"/api/tickets/{ticket_id}/hour-requests/{request.json()['id']}/decision", json={"action":"approve"}).status_code, 404)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/hour-requests/{request.json()['id']}/decision", json={"action":"approve"}).status_code, 200)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/hour-requests/{request.json()['id']}/decision", json={"action":"approve"}).status_code, 409)
        self.assertEqual(self.employee.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes":30,"note":"Второй этап"}).status_code, 201)
        detail = self.customer.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual((detail["ticket"]["approved_minutes"], detail["ticket"]["actual_minutes"]), (120,75))
        self.assertEqual(len(detail["time_entries"]), 2)

    def test_company_visibility_and_owner_approval(self):
        owner_id = self.customer.get("/api/me").json()["id"]
        org = self.admin.post("/api/organizations", json={"name":"Студия","owner_id":owner_id}).json()
        self.assertEqual(self.admin.post(f"/api/organizations/{org['id']}/members", json={"email":"o@example.com","role":"member"}).status_code, 201)
        shared = self.other.post("/api/tickets", json={"title":"Общий проект","description":"Нужна оценка работы","visibility":"organization"}).json()["id"]
        private = self.other.post("/api/tickets", json={"title":"Личный вопрос","description":"Приватное обращение","visibility":"private"}).json()["id"]
        self.assertEqual(self.customer.get(f"/api/tickets/{shared}").status_code, 200)
        self.assertEqual(self.customer.get(f"/api/tickets/{private}").status_code, 404)
        self.assertEqual(len(self.customer.get("/api/tickets").json()), 1)
        self.admin.patch(f"/api/tickets/{shared}/assignee", json={"assignee_id":self.staff["id"]})
        quote = self.employee.post(f"/api/tickets/{shared}/estimates", json={"effort_minutes":120,"assessment_minutes":15}).json()
        self.assertEqual(self.customer.post(f"/api/tickets/{shared}/estimates/decision", json={"estimate_id":quote["id"],"action":"approve"}).status_code, 200)
        self.assertEqual(self.other.get(f"/api/tickets/{shared}").json()["estimates"][0]["state"], "approved")
        self.assertEqual(self.admin.delete(f"/api/organizations/{org['id']}/members/{owner_id}").status_code, 409)
        member_id = self.other.get("/api/me").json()["id"]
        self.assertEqual(self.admin.patch(f"/api/organizations/{org['id']}/members/{member_id}", json={"role":"viewer"}).status_code, 200)
        self.assertEqual(self.other.get(f"/api/tickets/{shared}").status_code, 200)
        self.assertEqual(self.other.post(f"/api/tickets/{shared}/messages", json={"body":"Не могу писать","request_id":"viewer-check-1"}).status_code, 403)
        self.assertEqual(self.other.post(f"/api/tickets/{shared}/attachments", files={"file":("note.txt",b"test","text/plain")}).status_code, 403)
        self.assertEqual(self.other.post("/api/tickets", json={"title":"Новая общая","description":"Недоступная заявка","visibility":"organization"}).status_code, 403)
        self.assertEqual(self.admin.delete(f"/api/organizations/{org['id']}/members/{member_id}").status_code, 200)
        self.assertEqual(self.other.get(f"/api/tickets/{shared}").status_code, 404)
        self.assertEqual(self.customer.get(f"/api/tickets/{shared}").status_code, 200)

    def test_attachments_access_chat_transfer_and_deadline(self):
        chat = self.customer.post("/api/chats").json()
        message = self.customer.post(f"/api/chats/{chat['id']}/messages", json={"body":"Посмотрите файл","request_id":"file-message-1"}).json()
        uploaded = self.customer.post(f"/api/chats/{chat['id']}/attachments", data={"message_id":str(message["id"])},
                                      files={"file":("brief.txt",b"task details","text/plain")})
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(self.other.get(f"/api/attachments/{uploaded.json()['id']}").status_code, 404)
        self.assertEqual(self.customer.get(f"/api/attachments/{uploaded.json()['id']}").content, b"task details")
        ticket_id = self.admin.post(f"/api/chats/{chat['id']}/tickets", json={"title":"Задача из чата","message_id":message["id"]}).json()["id"]
        detail = self.customer.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual(detail["attachments"][0]["filename"], "brief.txt")
        self.assertEqual(self.other.get(f"/api/attachments/{detail['attachments'][0]['id']}").status_code, 404)
        self.assertEqual(self.customer.post(f"/api/tickets/{ticket_id}/attachments", files={"file":("bad.exe",b"binary","application/octet-stream")}).status_code, 422)
        due = "2026-10-02T12:00:00+00:00"
        self.assertEqual(self.admin.patch(f"/api/tickets/{ticket_id}/deadline", json={"due_at":due}).status_code, 200)
        self.assertEqual(self.customer.get(f"/api/tickets/{ticket_id}").json()["ticket"]["delivery_due_at"], due)
        self.admin.patch(f"/api/tickets/{ticket_id}/deadline", json={"due_at":"2020-01-01T12:00:00+00:00"})
        queue_item = next(item for item in self.admin.get("/api/work-queue").json() if item["source"] == "ticket" and item["id"] == ticket_id)
        self.assertTrue(queue_item["overdue"])
        self.assertIn("Просрочено", queue_item["next_action"])

    def test_billing_and_invoicing_flow(self):
        # 1. Customer views overview
        overview = self.customer.get("/api/billing/overview").json()
        self.assertEqual(overview["balance_minutes"], 0)
        self.assertEqual(overview["hourly_rate_rub"], 3000)

        # 2. Admin sets customer rate and INN
        cust_id = self.customer.get("/api/me").json()["id"]
        res = self.admin.patch(f"/api/billing/clients/user/{cust_id}", json={
            "hourly_rate_rub": 3500,
            "inn": "7712345678",
            "kpp": "",
            "legal_address": "г. Москва, ул. Арбат, 10"
        })
        self.assertEqual(res.status_code, 200)

        # 3. Admin tops up client balance
        dep = self.admin.post("/api/billing/deposit", json={
            "client_type": "user",
            "client_id": cust_id,
            "minutes": 600,
            "amount_rub": 35000,
            "description": "Предоплата по договору"
        })
        self.assertEqual(dep.status_code, 200)
        self.assertEqual(dep.json()["new_balance_minutes"], 600)

        # 4. Create ticket, approve estimate, mark done
        ticket_id = self.customer.post("/api/tickets", json={"title":"Разработка модуля","description":"Добавить экспорт"}).json()["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id": self.staff["id"]})
        est = self.employee.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 120, "assessment_minutes": 20}).json()
        self.customer.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id": est["id"], "action": "approve"})
        self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "working"})
        self.employee.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes": 120, "note": "Выполнено"})
        self.employee.patch(f"/api/tickets/{ticket_id}/status", json={"status": "done"})

        # Check ticket billing info in get_ticket
        t_detail = self.customer.get(f"/api/tickets/{ticket_id}").json()["ticket"]
        self.assertEqual(t_detail["hourly_rate_rub"], 3500)
        self.assertEqual(t_detail["cost_rub"], 7000)

        # 5. Check unbilled tickets
        unbilled = self.admin.get(f"/api/billing/unbilled-tickets?client_type=user&client_id={cust_id}").json()
        self.assertEqual(len(unbilled), 1)
        self.assertEqual(unbilled[0]["cost_rub"], 7000)

        # 6. Generate Act
        act = self.admin.post("/api/billing/invoices", json={
            "doc_type": "act",
            "client_type": "user",
            "client_id": cust_id,
            "ticket_ids": [ticket_id]
        })
        self.assertEqual(act.status_code, 201)
        act_data = act.json()
        self.assertTrue(act_data["number"].startswith("АКТ-"))
        self.assertEqual(act_data["total_rub"], 7000)
        self.assertEqual(act_data["total_minutes"], 120)

        # Balance after Act: 600 - 120 = 480
        post_act_overview = self.customer.get("/api/billing/overview").json()
        self.assertEqual(post_act_overview["balance_minutes"], 480)

        # 7. Print route returns HTML with Russian rubles in words
        print_html = self.customer.get(f"/api/billing/invoices/{act_data['id']}/print")
        self.assertEqual(print_html.status_code, 200)
        self.assertIn("АКТ №", print_html.text)
        self.assertIn("Семь тысяч рублей 00 копеек", print_html.text)

        # 8. Issue prepay invoice for 10 hours
        inv = self.admin.post("/api/billing/invoices", json={
            "doc_type": "invoice",
            "client_type": "user",
            "client_id": cust_id,
            "hours": 10.0,
            "description": "Пакет 10 часов"
        }).json()
        self.assertTrue(inv["number"].startswith("СЧ-"))

        # Customer pays invoice online
        pay = self.customer.patch(f"/api/billing/invoices/{inv['id']}/status", json={"status": "paid"})
        self.assertEqual(pay.status_code, 200)

        # Balance credited: 480 + 600 = 1080
        final_overview = self.customer.get("/api/billing/overview").json()
        self.assertEqual(final_overview["balance_minutes"], 1080)

    def test_service_hours_go_to_act(self):
        cust_id = self.customer.get("/api/me").json()["id"]
        other_id = self.other.get("/api/me").json()["id"]
        chat_id = self.customer.post("/api/chats").json()["id"]
        entry = {"customer_id": cust_id, "kind": "call", "minutes": 45, "note": "Созвон по срокам релиза",
                 "request_id": "service-call-1"}
        self.assertEqual(self.customer.post("/api/service-entries", json=entry).status_code, 403)
        call = self.employee.post("/api/service-entries", json=entry)
        self.assertEqual(call.status_code, 201)
        self.assertEqual(self.employee.post("/api/service-entries", json=entry).json()["id"], call.json()["id"])
        chat = self.employee.post("/api/service-entries", json={"customer_id": cust_id, "kind": "chat", "minutes": 30,
                                                                 "note": "Консультация в чате"}).json()
        foreign = self.customer.post("/api/tickets", json={"title":"Чужая заявка","description":"Описание"}).json()["id"]
        self.assertEqual(self.employee.post("/api/service-entries", json={"customer_id": other_id, "ticket_id": foreign,
            "kind": "chat", "minutes": 10, "note": "Не тот клиент"}).status_code, 422)

        self.assertEqual(len(self.admin.get(f"/api/chats/{chat_id}").json()["service_entries"]), 2)
        self.assertEqual(self.customer.get(f"/api/chats/{chat_id}").json()["service_entries"], [])
        self.assertEqual(self.customer.get("/api/service-entries").status_code, 403)
        overview = self.customer.get("/api/billing/overview").json()
        self.assertNotIn("service_entries", overview)
        self.assertEqual(overview["unbilled_minutes"], 75)
        self.assertEqual(len(self.admin.get("/api/billing/overview").json()["service_entries"]), 2)

        act = self.admin.post("/api/billing/invoices", json={"doc_type": "act", "client_type": "user", "client_id": cust_id,
                                                             "ticket_ids": [], "service_entry_ids": [call.json()["id"]]})
        self.assertEqual(act.status_code, 201)
        self.assertEqual(act.json()["total_minutes"], 45)
        self.assertEqual(act.json()["total_rub"], 2250)
        printed = self.customer.get(f"/api/billing/invoices/{act.json()['id']}/print").text
        self.assertIn(service.SERVICE_ACT_TITLE, printed)
        self.assertNotIn("Созвон по срокам релиза", printed)
        self.assertNotIn("Созвон по срокам релиза", str(self.customer.get(f"/api/billing/invoices/{act.json()['id']}").json()))
        self.assertEqual(self.employee.delete(f"/api/service-entries/{call.json()['id']}").status_code, 409)
        self.assertEqual(self.customer.get("/api/billing/overview").json()["balance_minutes"], -45)

        self.assertEqual(self.admin.patch(f"/api/billing/invoices/{act.json()['id']}/status", json={"status": "cancelled"}).status_code, 200)
        unbilled = self.admin.get(f"/api/service-entries?client_type=user&client_id={cust_id}&unbilled=true").json()
        self.assertEqual({x["id"] for x in unbilled}, {call.json()["id"], chat["id"]})
        self.assertEqual(self.employee.delete(f"/api/service-entries/{chat['id']}").status_code, 200)

        self.assertEqual(self.employee.post("/api/service-entries", json={"customer_id": cust_id, "ticket_id": foreign,
            "kind": "meeting", "minutes": 60, "note": "Встреча по заявке"}).status_code, 201)
        detail = self.admin.get(f"/api/tickets/{foreign}").json()
        self.assertEqual(detail["ticket"]["service_minutes"], 60)
        self.assertEqual(detail["ticket"]["service_cost_rub"], 3000)
        self.assertEqual([e["kind"] for e in detail["service_entries"]], ["meeting"])
        customer_detail = self.customer.get(f"/api/tickets/{foreign}").json()
        self.assertEqual(customer_detail["service_entries"], [])
        self.assertNotIn("service_minutes", customer_detail["ticket"])


if __name__ == "__main__":
    unittest.main()
