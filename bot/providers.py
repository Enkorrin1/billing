"""Telegram and MAX wire formats, isolated from service-desk business rules."""

import hashlib
import json
import os
import re
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


PROVIDERS = ("telegram", "max")
MAX_UPDATE_TYPES = ("message_created", "message_callback", "bot_started", "bot_stopped")


def config(provider):
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider")
    prefix = provider.upper()
    return {"token": os.getenv(prefix + "_BOT_TOKEN", ""),
            "secret": os.getenv(prefix + "_WEBHOOK_SECRET", ""),
            "url": os.getenv(prefix + "_BOT_URL", "")}


def public_url():
    return os.getenv("APP_PUBLIC_URL", "").rstrip("/")


def configured(provider):
    c = config(provider)
    return bool(c["token"] and c["secret"] and c["url"] and public_url())


def validate_config(provider):
    c = config(provider)
    if not configured(provider):
        raise ValueError(f"Configure {provider.upper()}_BOT_TOKEN, _WEBHOOK_SECRET, _BOT_URL and APP_PUBLIC_URL")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", c["secret"]):
        raise ValueError("Webhook secret must contain 32–128 ASCII letters, digits, '_' or '-'")
    for url in (c["url"], public_url()):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Public and bot URLs must use HTTPS")
    if provider == "max" and urlparse(public_url()).port not in (None, 443):
        raise ValueError("MAX requires HTTPS on port 443")
    return c


@dataclass(frozen=True)
class Event:
    provider: str
    event_id: str
    external_id: str
    chat_id: str
    display_name: str
    text: str = ""
    callback_id: str = ""
    action: str = ""
    reply_id: str = ""
    unsupported: bool = False
    stopped: bool = False


def normalize(provider, update):
    """Accept only personal dialogs. Ignore edits and all bot-authored messages."""
    if not isinstance(update, dict):
        raise ValueError("Expected an object")
    if provider == "telegram":
        if "update_id" not in update:
            raise ValueError("Missing update_id")
        cb = update.get("callback_query") or {}
        msg = cb.get("message") or update.get("message") or {}
        sender = cb.get("from") or msg.get("from") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") != "private" or not sender.get("id") or sender.get("is_bot"):
            return None
        # A private Telegram chat belongs to its sender.
        if str(chat.get("id")) != str(sender["id"]):
            return None
        return Event(provider, str(update["update_id"]), str(sender["id"]), str(chat["id"]),
                     str(sender.get("first_name", "Пользователь"))[:100],
                     str(msg.get("text") or "") if not cb else "",
                     str(cb.get("id") or ""), str(cb.get("data") or ""),
                     str((msg.get("reply_to_message") or {}).get("message_id") or ""),
                     unsupported=not cb and not isinstance(msg.get("text"), str))
    kind = update.get("update_type")
    if kind not in ("message_created", "message_callback", "bot_started", "bot_stopped"):
        return None
    cb = update.get("callback") or {}
    msg = update.get("message") or {}
    sender = cb.get("user") or msg.get("sender") or update.get("user") or {}
    recipient = msg.get("recipient") or {}
    if not sender.get("user_id") or sender.get("is_bot"):
        return None
    if msg and recipient.get("chat_type") != "dialog":
        return None
    chat_id = recipient.get("chat_id", update.get("chat_id"))
    if chat_id is None:
        return None
    body = msg.get("body") or {}
    # Provider IDs, not message text, identify repeated deliveries.
    raw_id = cb.get("callback_id") or body.get("mid")
    if not raw_id:
        raw_id = hashlib.sha256(json.dumps(update, sort_keys=True).encode()).hexdigest()
    link = msg.get("link") or {}
    return Event(provider, kind + ":" + str(raw_id), str(sender["user_id"]), str(chat_id),
                 str(sender.get("first_name") or sender.get("name") or "Пользователь")[:100],
                 "/start" if kind == "bot_started" else str(body.get("text") or "") if not cb else "",
                 str(cb.get("callback_id") or ""), str(cb.get("payload") or ""),
                 str((link.get("message") or {}).get("mid") or "") if link.get("type") == "reply" else "",
                 unsupported=kind == "message_created" and (bool(body.get("attachments")) or not body.get("text")),
                 stopped=kind == "bot_stopped")


class DeliveryError(Exception):
    """Never embed response bodies or token-bearing URLs in exceptions/logs."""
    def __init__(self, code, retry_after=0, permanent=False, blocked=False):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after
        self.permanent = permanent
        self.blocked = blocked


class ProviderClient:
    def __init__(self, provider, transport=None):
        self.provider = provider
        self.token = config(provider)["token"]
        ca_file = os.getenv("BOT_CA_BUNDLE")
        context = ssl.create_default_context(cafile=ca_file) if ca_file else True
        self.client = httpx.Client(timeout=15, transport=transport, verify=context)

    def close(self):
        self.client.close()

    def request(self, method, payload=None, params=None, http_method="POST"):
        if not self.token:
            raise DeliveryError("not_configured", retry_after=300)
        if self.provider == "telegram":
            url, headers = f"https://api.telegram.org/bot{self.token}/{method}", {}
        else:
            url, headers = f"https://platform-api2.max.ru/{method}", {"Authorization": self.token}
        try:
            response = self.client.request(http_method, url, json=payload, params=params, headers=headers)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise DeliveryError("network_or_invalid_response") from None
        if not isinstance(data, dict):
            raise DeliveryError("invalid_response")
        status = response.status_code
        if self.provider == "telegram" and not data.get("ok", False):
            status = data.get("error_code", status if status >= 400 else 502)
        if status >= 400 or (self.provider == "max" and data.get("success") is False):
            delay = (data.get("parameters") or {}).get("retry_after", response.headers.get("Retry-After", 0))
            try:
                delay = min(max(float(delay), 0), 86400)
            except (TypeError, ValueError):
                delay = 0
            raise DeliveryError(f"api_{status}", delay, permanent=status in (400, 403, 404), blocked=status == 403)
        return data

    def check_connection(self):
        """Read-only check; never print provider responses or webhook secrets."""
        validate_config(self.provider)
        expected = public_url() + "/webhooks/" + self.provider
        if self.provider == "telegram":
            profile = self.request("getMe", {})
            if not (profile.get("result") or {}).get("is_bot"):
                raise DeliveryError("invalid_bot_profile", permanent=True)
            webhook = self.request("getWebhookInfo", {}).get("result") or {}
            if webhook.get("url") != expected:
                raise DeliveryError("webhook_not_registered", permanent=True)
            if webhook.get("last_error_message"):
                raise DeliveryError("webhook_delivery_error", permanent=True)
        else:
            profile = self.request("me", http_method="GET")
            if not profile.get("is_bot"):
                raise DeliveryError("invalid_bot_profile", permanent=True)
            subscriptions = self.request("subscriptions", http_method="GET").get("subscriptions")
            if not isinstance(subscriptions, list):
                raise DeliveryError("invalid_response", permanent=True)
            matching = [s for s in subscriptions if isinstance(s, dict) and s.get("url") == expected]
            if not matching:
                raise DeliveryError("webhook_not_registered", permanent=True)
            if not any(s.get("update_types") in (None, []) or
                       (isinstance(s.get("update_types"), list) and
                        all(kind in s["update_types"] for kind in MAX_UPDATE_TYPES)) for s in matching):
                raise DeliveryError("webhook_missing_event_types", permanent=True)
        return True

    def deliver(self, chat_id, payload):
        if payload.get("ack"):
            if self.provider == "telegram":
                self.request("answerCallbackQuery", {"callback_query_id": payload["ack"]})
            else:
                self.request("answers", {"notification": "Принято"}, {"callback_id": payload["ack"]})
            return None
        buttons = payload.get("buttons", [])
        if self.provider == "telegram":
            rows = [[{"text": b["text"], **({"url": b["url"]} if "url" in b else {"callback_data": b["token"]})} for b in row] for row in buttons]
            result = self.request("sendMessage", {"chat_id": chat_id, "text": payload["text"],
                                                   "reply_markup": {"inline_keyboard": rows}})
            return str(result["result"]["message_id"])
        rows = [[{"text": b["text"], **({"type": "link", "url": b["url"]} if "url" in b else {"type": "callback", "payload": b["token"]})} for b in row] for row in buttons]
        data = {"text": payload["text"]}
        if rows:
            data["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": rows}}]
        result = self.request("messages", data, {"chat_id": chat_id})
        return str(result["message"]["body"]["mid"])

    def register_webhook(self):
        c = validate_config(self.provider)
        url = public_url() + "/webhooks/" + self.provider
        if self.provider == "telegram":
            return self.request("setWebhook", {"url": url, "secret_token": c["secret"],
                                               "allowed_updates": ["message", "callback_query"]})
        return self.request("subscriptions", {"url": url, "secret": c["secret"],
                                               "update_types": list(MAX_UPDATE_TYPES)})
