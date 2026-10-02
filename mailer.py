"""Почта без сторонних зависимостей: отправка через SMTP или в файлы, приём ответов через IMAP.

Бэкенд выбирается по окружению: SMTP_HOST включает отправку через SMTP, EMAIL_BACKEND=file
складывает письма в .eml-файлы рядом с базой (удобно для проверки без почтового сервера).
Без настроек почта выключена, и письма не ставятся в очередь.
"""
import html
import imaplib
import os
import re
import smtplib
import ssl
import time
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, getaddresses, make_msgid, parseaddr
from pathlib import Path

REPLY_ID = re.compile(r"<r\.([A-Za-z0-9_-]{20,64})@")
REPLY_MARKER = re.compile(r"ref:([A-Za-z0-9_-]{20,64})")
QUOTE_HEADERS = (
    re.compile(r"^\s*(On|В|Вт|Пн|Ср|Чт|Пт|Сб|Вс)\b.{0,200}(wrote|пишет|написал|написала)\s*:?\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*(Original Message|Исходное сообщение|Пересылаемое сообщение)", re.I),
    re.compile(r"^\s*(From|От|Отправлено|Sent):\s", re.I),
    re.compile(r"<[^<>\s]+@[^<>\s]+>\s*:\s*$"),
    re.compile(r"^\s*-- ?$"),
    re.compile(REPLY_MARKER.pattern),
)


def backend() -> str | None:
    if os.getenv("SMTP_HOST", "").strip():
        return "smtp"
    if os.getenv("EMAIL_BACKEND", "").strip().lower() == "file":
        return "file"
    return None


def enabled() -> bool:
    return backend() is not None


def sender() -> str:
    raw = os.getenv("EMAIL_FROM", "").strip() or os.getenv("SMTP_USER", "").strip() or "noreply@localhost"
    name, address = parseaddr(raw)
    return formataddr((name or "Линия", address or raw))


def sender_domain() -> str:
    address = parseaddr(sender())[1]
    return address.split("@", 1)[1] if "@" in address else "localhost"


def reply_address() -> str | None:
    """Адрес, на который клиенты отвечают. Без IMAP ответы не принимаются, и адрес не нужен."""
    raw = os.getenv("EMAIL_REPLY_TO", "").strip() or (os.getenv("IMAP_USER", "").strip() if os.getenv("IMAP_HOST") else "")
    return raw or None


def build(to: list[str], subject: str, text: str, html_body: str | None = None, *,
          message_id: str | None = None, headers: dict | None = None) -> EmailMessage:
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = sender()
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or make_msgid(domain=sender_domain())
    if reply_address():
        msg["Reply-To"] = reply_address()
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def send(msg: EmailMessage, file_dir: Path | None = None):
    kind = backend()
    if kind == "file":
        target = Path(os.getenv("EMAIL_FILE_DIR", "") or file_dir or "mail_outbox")
        target.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{abs(hash(msg['Message-ID'])) % 10**8:08d}.eml"
        (target / name).write_bytes(msg.as_bytes())
        return
    if kind != "smtp":
        raise RuntimeError("Почта не настроена")
    host = os.getenv("SMTP_HOST", "").strip()
    security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    port = int(os.getenv("SMTP_PORT", "465" if security == "ssl" else "587"))
    user, password = os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", "")
    context = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
    try:
        if security == "starttls":
            server.starttls(context=context)
        if user:
            server.login(user, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass


def permanent_error(exc: Exception) -> bool:
    return isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError)) or (
        isinstance(exc, smtplib.SMTPResponseException) and 500 <= exc.smtp_code < 600)


# ---------- Входящие письма ----------

def imap_configured() -> bool:
    return bool(os.getenv("IMAP_HOST", "").strip() and os.getenv("IMAP_USER", "").strip())


def fetch_unseen(handle) -> int:
    """Забирает непрочитанные письма из ящика ответов. handle(raw) вызывается для каждого письма."""
    host = os.getenv("IMAP_HOST", "").strip()
    port = int(os.getenv("IMAP_PORT", "993"))
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    box = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    processed = 0
    try:
        box.login(os.getenv("IMAP_USER", ""), os.getenv("IMAP_PASSWORD", ""))
        box.select(folder)
        status, data = box.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for num in data[0].split()[:50]:
            status, parts = box.fetch(num, "(RFC822)")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            try:
                handle(parts[0][1])
            finally:
                box.store(num, "+FLAGS", "\\Seen")
            processed += 1
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return processed


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|blockquote)\b.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value)


def parse(raw: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = html_to_text(body)
    refs = " ".join(filter(None, [str(msg.get("In-Reply-To", "")), str(msg.get("References", ""))]))
    sender_addr = (getaddresses([str(msg.get("From", ""))]) or [("", "")])[0][1].strip().lower()
    auto = str(msg.get("Auto-Submitted", "")).lower()
    return {
        "message_id": str(msg.get("Message-ID", "")).strip(),
        "from": sender_addr,
        "subject": str(msg.get("Subject", "")),
        "refs": refs,
        "body": body,
        "auto_reply": (auto and auto != "no") or bool(msg.get("X-Autoreply")) or str(msg.get("Precedence", "")).lower() in ("bulk", "auto_reply", "junk"),
    }


def reply_token(parsed: dict) -> str | None:
    match = REPLY_ID.search(parsed["refs"]) or REPLY_MARKER.search(parsed["body"])
    return match.group(1) if match else None


def strip_quoted(text: str) -> str:
    """Оставляет только новый текст ответа: отрезает цитату, подпись и служебную метку."""
    lines = text.replace("\r\n", "\n").split("\n")
    kept = []
    for line in lines:
        if line.lstrip().startswith(">") or any(p.search(line) for p in QUOTE_HEADERS):
            break
        kept.append(line)
    result = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", result)
