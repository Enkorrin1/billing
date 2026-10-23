import os
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

temp = tempfile.TemporaryDirectory()
os.environ.setdefault("APP_DB", str(Path(temp.name) / "test_pm_billing.db"))
os.environ["BACKGROUND_JOBS"] = "0"
import app as service


class PmBillingTests(unittest.TestCase):
    def setUp(self):
        with service.db() as conn:
            for table in (
                "ticket_templates", "service_entries", "billing_transactions",
                "ticket_git_links", "attachments", "hour_requests", "time_entries",
                "chat_ticket_links", "chat_notifications", "chat_messages", "chats",
                "notifications", "estimates", "ticket_events", "messages", "tickets",
                "invoices", "organization_members", "organizations", "customer_profiles",
                "sessions", "users"
            ):
                conn.execute(f"DELETE FROM {table}")
            service.create_user(conn, "Admin PM", "admin@example.com", "password123", "admin")
            service.create_user(conn, "Worker", "worker@example.com", "password123", "employee")
            service.create_user(conn, "Client", "client@example.com", "password123", "customer")

        self.admin = TestClient(service.app)
        self.worker = TestClient(service.app)
        self.client = TestClient(service.app)

        self.assertEqual(self.admin.post("/api/login", json={"email": "admin@example.com", "password": "password123"}).status_code, 200)
        self.assertEqual(self.worker.post("/api/login", json={"email": "worker@example.com", "password": "password123"}).status_code, 200)
        self.assertEqual(self.client.post("/api/login", json={"email": "client@example.com", "password": "password123"}).status_code, 200)

        self.worker_id = self.worker.get("/api/me").json()["id"]
        self.client_id = self.client.get("/api/me").json()["id"]

        # Set client hourly rate to 3000 RUB
        self.admin.patch(f"/api/billing/clients/user/{self.client_id}", json={"hourly_rate_rub": 3000})

    def test_estimate_pm_markup_custom_amount_and_customer_blindness_to_hours(self):
        # 1. Customer creates ticket
        t = self.client.post("/api/tickets", json={"title": "Доработка API", "description": "Сделать эндпоинт"}).json()
        ticket_id = t["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id": self.worker_id})

        # 2. Worker enters estimated hours (120 min effort, 15 min assessment)
        est = self.worker.post(f"/api/tickets/{ticket_id}/estimates", json={
            "effort_minutes": 120, "assessment_minutes": 15, "note": "Технические детали реализации"
        }).json()
        self.assertEqual(est["state"], "pending_pm")
        self.assertEqual(est["performer_effort_minutes"], 120)

        # 3. Customer must NOT see the estimate yet
        cust_ticket = self.client.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual(cust_ticket["estimates"], [])
        self.assertEqual(cust_ticket["ticket"]["next_step"], "Готовим оценку")
        self.assertEqual(self.client.post(f"/api/tickets/{ticket_id}/estimates/decision",
                                          json={"estimate_id": est["id"], "action": "approve"}).status_code, 409)

        # 4. PM reviews: adds 60 min PM overhead and sets custom amount 10 000 RUB
        pm_review = self.admin.post(f"/api/tickets/{ticket_id}/estimates/{est['id']}/pm-review", json={
            "action": "send_to_customer",
            "pm_effort_minutes": 60,
            "custom_amount_rub": 10000,
            "client_note": "В стоимость входит разработка, код-ревью и QA тестирование"
        })
        self.assertEqual(pm_review.status_code, 200)

        # 5. Customer now sees estimate, but strictly WITHOUT performer or PM hours
        cust_ticket = self.client.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual(len(cust_ticket["estimates"]), 1)
        c_est = cust_ticket["estimates"][0]
        self.assertEqual(c_est["state"], "pending")
        self.assertEqual(c_est["amount_rub"], 10000)
        self.assertEqual(c_est["note"], "В стоимость входит разработка, код-ревью и QA тестирование")
        # Ensure hours are hidden from customer
        self.assertNotIn("performer_effort_minutes", c_est)
        self.assertNotIn("pm_effort_minutes", c_est)
        self.assertNotIn("contractor_total_minutes", c_est)

        # 6. Customer requests revision with proposed amount 8 000 RUB
        rev = self.client.post(f"/api/tickets/{ticket_id}/estimates/decision", json={
            "estimate_id": est["id"],
            "action": "request_revision",
            "proposed_amount_rub": 8000,
            "comment": "Бюджет ограничен 8000 руб"
        })
        self.assertEqual(rev.status_code, 200)

        # 7. Worker prepares revision version 2
        est2 = self.worker.post(f"/api/tickets/{ticket_id}/estimates", json={
            "effort_minutes": 100, "assessment_minutes": 10, "note": "Оптимизировали скоуп"
        }).json()
        self.assertEqual(est2["version"], 2)
        self.assertEqual(est2["state"], "pending_pm")

        # 8. PM sends version 2 with custom amount 8 000 RUB
        self.admin.post(f"/api/tickets/{ticket_id}/estimates/{est2['id']}/pm-review", json={
            "action": "send_to_customer",
            "pm_effort_minutes": 20,
            "custom_amount_rub": 8000,
            "client_note": "Согласовано по спецтарифу 8 000 ₽"
        })

        # 9. Customer approves version 2
        appr = self.client.post(f"/api/tickets/{ticket_id}/estimates/decision", json={
            "estimate_id": est2["id"],
            "action": "approve"
        })
        self.assertEqual(appr.status_code, 200)

        # 10. Verify ticket status is now 'working', approved limit for performer is set
        detail = self.client.get(f"/api/tickets/{ticket_id}").json()
        self.assertEqual(detail["ticket"]["status"], "working")
        self.assertEqual(detail["ticket"]["cost_rub"], 8000)  # agreed custom amount is authoritative
        self.assertEqual(detail["ticket"]["estimate_amount_rub"], 8000)
        listed = next(t for t in self.client.get('/api/tickets').json() if t['id']==ticket_id)
        self.assertEqual(listed['cost_rub'],8000)
        # Service charges remain separate and add to the agreed price.
        self.assertEqual(self.worker.post('/api/service-entries',json={'customer_id':self.client_id,'ticket_id':ticket_id,'kind':'chat','minutes':20,'note':'Обсуждение результатов'}).status_code,201)
        detail=self.client.get(f'/api/tickets/{ticket_id}').json()['ticket']
        self.assertEqual((detail['cost_rub'],detail['service_cost_rub'],detail['total_cost_rub']),(8000,1000,9000))

    def test_additional_hours_pm_decision_internal_vs_billed(self):
        # 1. Setup ticket and approved estimate
        t = self.client.post("/api/tickets", json={"title": "Интеграция", "description": "Связка"}).json()
        ticket_id = t["id"]
        self.admin.patch(f"/api/tickets/{ticket_id}/assignee", json={"assignee_id": self.worker_id})
        est = self.worker.post(f"/api/tickets/{ticket_id}/estimates", json={"effort_minutes": 60, "assessment_minutes": 10}).json()
        self.admin.post(f"/api/tickets/{ticket_id}/estimates/{est['id']}/pm-review", json={"action": "send_to_customer"})
        self.client.post(f"/api/tickets/{ticket_id}/estimates/decision", json={"estimate_id": est["id"], "action": "approve"})

        # 2. Worker logs 60 minutes
        self.worker.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes": 60, "note": "Часть 1"})

        # 3. Worker requests 30 additional hours
        req1 = self.worker.post(f"/api/tickets/{ticket_id}/hour-requests", json={"minutes": 30, "reason": "Внутренняя сложность"}).json()
        self.assertEqual(req1["state"], "pending_pm")

        # Customer does NOT see pending_pm hour request
        cust_view = self.client.get(f"/api/tickets/{ticket_id}").json()
        self.assertFalse(cust_view["ticket"]["pending_hour_request"])

        # 4. PM absorbs internally: bill_customer=False
        pm_dec1 = self.admin.post(f"/api/tickets/{ticket_id}/hour-requests/{req1['id']}/pm-decision", json={
            "action": "approve",
            "bill_customer": False,
            "approved_performer_minutes": 30
        })
        self.assertEqual(pm_dec1.status_code, 200)
        self.assertEqual(pm_dec1.json()["state"], "approved")

        # Worker can now log 30 more minutes
        entry2 = self.worker.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes": 30, "note": "Часть 2"})
        self.assertEqual(entry2.status_code, 201)

        # Worker tries to log more without request -> 409
        self.assertEqual(self.worker.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes": 15, "note": "Лишнее"}).status_code, 409)

        # 5. Worker requests another 45 minutes
        req2 = self.worker.post(f"/api/tickets/{ticket_id}/hour-requests", json={"minutes": 45, "reason": "Клиент изменил ТЗ"}).json()

        # 6. PM decides to bill customer: bill_customer=True with custom amount
        pm_dec2 = self.admin.post(f"/api/tickets/{ticket_id}/hour-requests/{req2['id']}/pm-decision", json={
            "action": "approve",
            "bill_customer": True,
            "approved_performer_minutes": 45,
            "customer_minutes": 45,
            "custom_amount_rub": 2500,
            "client_explanation": "Дополнительный функционал по запросу"
        })
        self.assertEqual(pm_dec2.status_code, 200)
        self.assertEqual(pm_dec2.json()["state"], "pending")

        # 7. Customer sees request with amount and explanation, but NO internal hours
        cust_view = self.client.get(f"/api/tickets/{ticket_id}").json()
        self.assertTrue(cust_view["ticket"]["pending_hour_request"])
        hr = cust_view["hour_requests"][0]
        self.assertEqual(hr["amount_rub"], 2500)
        self.assertEqual(hr["client_explanation"], "Дополнительный функционал по запросу")
        self.assertNotIn("performer_effort_minutes", hr)

        # 8. Customer approves additional work
        appr_hr = self.client.post(f"/api/tickets/{ticket_id}/hour-requests/{req2['id']}/decision", json={"action": "approve"})
        self.assertEqual(appr_hr.status_code, 200)

        # Worker can now log the final 45 minutes
        entry3 = self.worker.post(f"/api/tickets/{ticket_id}/time-entries", json={"minutes": 45, "note": "Часть 3"})
        self.assertEqual(entry3.status_code, 201)
        detail=self.client.get(f'/api/tickets/{ticket_id}').json()['ticket']
        self.assertEqual(detail['cost_rub'],5500) # 3000 base + 2500 approved extra, excludes internal extra
        listed=next(t for t in self.client.get('/api/tickets').json() if t['id']==ticket_id)
        self.assertEqual(listed['cost_rub'],5500)


if __name__ == "__main__":
    unittest.main()
