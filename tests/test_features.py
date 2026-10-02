import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

temp = tempfile.TemporaryDirectory()
os.environ.setdefault("APP_DB", str(Path(temp.name) / "test.db"))
import app as service


class BillingFlag(unittest.TestCase):
    def setUp(self):
        with service.db() as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM users WHERE email='flag@example.com'")
        self.client = TestClient(service.app)
        self.assertEqual(self.client.post("/api/register", json={"name": "Flag", "email": "flag@example.com", "password": "password123"}).status_code, 200)

    def test_billing_hidden_by_default(self):
        with mock.patch.dict(os.environ, {"BILLING_ENABLED": ""}):
            os.environ.pop("BILLING_ENABLED")
            self.assertFalse(self.client.get("/api/public/settings").json()["billing_enabled"])
            response = self.client.get("/api/billing/overview")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "Раздел биллинга отключён")
            self.assertEqual(self.client.post("/api/billing/invoices", json={}).status_code, 404)

    def test_billing_enabled_by_flag(self):
        with mock.patch.dict(os.environ, {"BILLING_ENABLED": "1"}):
            self.assertTrue(self.client.get("/api/public/settings").json()["billing_enabled"])
            self.assertEqual(self.client.get("/api/billing/overview").status_code, 200)


if __name__ == "__main__":
    unittest.main()
