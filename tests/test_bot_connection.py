import os
import unittest
from unittest.mock import patch

import httpx

from bot.providers import DeliveryError, MAX_UPDATE_TYPES, ProviderClient


class MaxConnection(unittest.TestCase):
    def check(self, subscriptions, status=200):
        captured = []

        def handler(request):
            captured.append(request)
            if status != 200:
                return httpx.Response(status, json={"message": "secret-provider-detail"})
            return httpx.Response(200, json={"is_bot": True} if request.url.path == "/me"
                                  else {"subscriptions": subscriptions})

        env = {"MAX_BOT_TOKEN": "private-token", "MAX_WEBHOOK_SECRET": "s" * 40,
               "MAX_BOT_URL": "https://max.ru/test_bot", "APP_PUBLIC_URL": "https://desk.example.com"}
        with patch.dict(os.environ, env):
            client = ProviderClient("max", httpx.MockTransport(handler))
            try:
                client.check_connection()
            finally:
                client.close()
        return captured

    def test_checks_profile_and_subscription_using_get(self):
        requests = self.check([{"url": "https://desk.example.com/webhooks/max",
                                "update_types": list(MAX_UPDATE_TYPES)}])
        self.assertEqual([r.url.path for r in requests], ["/me", "/subscriptions"])
        for request in requests:
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            self.assertEqual(request.headers["authorization"], "private-token")

    def test_unfiltered_subscription_receives_all_events(self):
        self.check([{"url": "https://desk.example.com/webhooks/max"}])

    def test_missing_or_wrong_webhook(self):
        for subscriptions in ([], [{"url": "https://other.example.com/webhooks/max"}]):
            with self.assertRaisesRegex(DeliveryError, "webhook_not_registered"):
                self.check(subscriptions)

    def test_missing_callback_subscription(self):
        with self.assertRaisesRegex(DeliveryError, "webhook_missing_event_types"):
            self.check([{"url": "https://desk.example.com/webhooks/max",
                         "update_types": ["message_created"]}])

    def test_authentication_error_does_not_expose_provider_data(self):
        with self.assertRaisesRegex(DeliveryError, "^api_401$"):
            self.check([], status=401)

    def test_malformed_subscription_response(self):
        with self.assertRaisesRegex(DeliveryError, "invalid_response"):
            self.check(None)
