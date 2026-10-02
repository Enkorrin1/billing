"""Small service desk MVP: customers, tickets, messages, and assignments."""

import asyncio
import base64
import binascii
import csv
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, UnidentifiedImageError

from web_push import WebPush, b64url_decode


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("APP_DB", ROOT / "data" / "app.db"))
COOKIE = "desk_session"
STATUSES = {"new", "working", "waiting", "done", "closed"}
ATTACHMENT_DIR = DB_PATH.parent / f"{DB_PATH.stem}_attachments"
LEGACY_ATTACHMENT_DIR = DB_PATH.parent / "attachments"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip"}
app = FastAPI(title="Кабинет заявок", docs_url=None, redoc_url=None)


def now():
    return datetime.now(timezone.utc).isoformat()


class RealtimeBus:
    def __init__(self):
        self.subscribers: dict[int, list[asyncio.Queue]] = {}

    def subscribe(self, user_id: int) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.setdefault(user_id, []).append(q)
        return q

    def unsubscribe(self, user_id: int, q: asyncio.Queue):
        if user_id in self.subscribers:
            if q in self.subscribers[user_id]:
                self.subscribers[user_id].remove(q)
            if not self.subscribers[user_id]:
                del self.subscribers[user_id]

    def publish(self, user_id: int, data: dict):
        if user_id in self.subscribers:
            for q in list(self.subscribers[user_id]):
                try:
                    q.put_nowait(data)
                except Exception:
                    pass

    def broadcast(self, user_ids, data: dict):
        for uid in user_ids:
            if uid:
                self.publish(uid, data)


realtime_bus = RealtimeBus()
web_push = WebPush(DB_PATH)


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.create_function("lower", 1, lambda s: s.lower() if s is not None else None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','employee','admin')),
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staff_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            job_title TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
            avatar_webp BLOB, avatar_updated_at TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            company_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id),
            assignee_id INTEGER REFERENCES users(id), title TEXT NOT NULL,
            description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            author_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL,
            created_at TEXT NOT NULL, request_id TEXT,
            UNIQUE(ticket_id, author_id, request_id)
        );
        CREATE TABLE IF NOT EXISTS ticket_events (
            id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            actor_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
            old_value TEXT, new_value TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS estimates (
            id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            author_id INTEGER NOT NULL REFERENCES users(id), version INTEGER NOT NULL,
            amount_minor INTEGER NOT NULL CHECK(amount_minor>=0), currency TEXT NOT NULL DEFAULT 'RUB',
            assessment_minutes INTEGER NOT NULL CHECK(assessment_minutes>0),
            note TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            customer_comment TEXT, proposed_amount_minor INTEGER,
            decided_at TEXT, created_at TEXT NOT NULL,
            UNIQUE(ticket_id,version)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
            read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            assignee_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL REFERENCES chats(id),
            author_id INTEGER NOT NULL REFERENCES users(id),
            body TEXT NOT NULL, request_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(chat_id,author_id,request_id)
        );
        CREATE TABLE IF NOT EXISTS chat_notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            chat_id INTEGER NOT NULL REFERENCES chats(id),
            kind TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT NOT NULL, read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_ticket_links (
            id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL REFERENCES chats(id),
            ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(id),
            source_message_id INTEGER REFERENCES chat_messages(id),
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS organization_members (
            organization_id INTEGER NOT NULL REFERENCES organizations(id),
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            role TEXT NOT NULL CHECK(role IN ('owner','member','viewer')),
            joined_at TEXT NOT NULL, PRIMARY KEY(organization_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS time_entries (
            id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            author_id INTEGER NOT NULL REFERENCES users(id), minutes INTEGER NOT NULL CHECK(minutes>0),
            note TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT
        );
        CREATE TABLE IF NOT EXISTS hour_requests (
            id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            author_id INTEGER NOT NULL REFERENCES users(id), minutes INTEGER NOT NULL CHECK(minutes>0),
            reason TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            decided_by INTEGER REFERENCES users(id), decided_at TEXT, created_at TEXT NOT NULL,
            request_id TEXT
        );
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY, ticket_id INTEGER REFERENCES tickets(id),
            chat_id INTEGER REFERENCES chats(id), chat_message_id INTEGER REFERENCES chat_messages(id),
            author_id INTEGER NOT NULL REFERENCES users(id), filename TEXT NOT NULL,
            stored_name TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL,
            created_at TEXT NOT NULL, CHECK((ticket_id IS NULL)!=(chat_id IS NULL))
        );
        CREATE INDEX IF NOT EXISTS idx_time_entries_ticket ON time_entries(ticket_id,id);
        CREATE INDEX IF NOT EXISTS idx_hour_requests_ticket ON hour_requests(ticket_id,id);
        CREATE INDEX IF NOT EXISTS idx_attachments_ticket ON attachments(ticket_id,id);
        CREATE INDEX IF NOT EXISTS idx_attachments_chat ON attachments(chat_id,id);
        CREATE INDEX IF NOT EXISTS idx_tickets_customer ON tickets(customer_id);
        CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee_id);
        CREATE INDEX IF NOT EXISTS idx_messages_ticket ON messages(ticket_id,id);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,read_at,id);
        CREATE INDEX IF NOT EXISTS idx_chats_assignee ON chats(assignee_id);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id,id);
        CREATE INDEX IF NOT EXISTS idx_chat_notifications_user ON chat_notifications(user_id,read_at,id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_ticket_source ON chat_ticket_links(chat_id,source_message_id);
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        if "request_id" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN request_id TEXT")
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "is_manager" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_manager INTEGER NOT NULL DEFAULT 0")
        estimate_columns = {row["name"] for row in conn.execute("PRAGMA table_info(estimates)")}
        if "effort_minutes" not in estimate_columns:
            conn.execute("ALTER TABLE estimates ADD COLUMN effort_minutes INTEGER")
        if "proposed_effort_minutes" not in estimate_columns:
            conn.execute("ALTER TABLE estimates ADD COLUMN proposed_effort_minutes INTEGER")
        ticket_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
        if "created_by_id" not in ticket_columns:
            conn.execute("ALTER TABLE tickets ADD COLUMN created_by_id INTEGER REFERENCES users(id)")
        for name, declaration in {
            "organization_id": "INTEGER REFERENCES organizations(id)",
            "visibility": "TEXT NOT NULL DEFAULT 'private'",
            "service_type": "TEXT NOT NULL DEFAULT 'other'",
            "response_due_at": "TEXT",
            "estimate_due_at": "TEXT",
            "delivery_due_at": "TEXT",
            "first_staff_response_at": "TEXT",
            "rating": "INTEGER",
            "rating_comment": "TEXT",
            "rated_at": "TEXT",
        }.items():
            if name not in ticket_columns:
                conn.execute(f"ALTER TABLE tickets ADD COLUMN {name} {declaration}")
        for table in ("time_entries", "hour_requests"):
            if "request_id" not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN request_id TEXT")
            conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_request ON {table}(ticket_id,author_id,request_id)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_request ON messages(ticket_id,author_id,request_id)")

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticket_internal_notes (
            id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_internal_notes_ticket ON ticket_internal_notes(ticket_id,id);

        CREATE TABLE IF NOT EXISTS canned_responses (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Общие', created_at TEXT NOT NULL
        );
        """)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
            user_agent TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id);
        """)
        if conn.execute("SELECT COUNT(*) FROM canned_responses").fetchone()[0] == 0:
            stamp = now()
            default_canned = [
                ("Взяли в работу", "Здравствуйте! Взяли вашу задачу в работу. Сейчас проведём предварительный анализ и вернёмся с оценкой сроков.", "Статус"),
                ("Запрос деталей", "Для точной оценки и реализации уточните, пожалуйста: 1) В каких условиях воспроизводится? 2) Есть ли доступ/логи? 3) Какой ожидаемый результат?", "Уточнение"),
                ("Оценка готова", "Мы подготовили плановую оценку трудозатрат в карточке заявки. Пожалуйста, ознакомьтесь и нажмите «Одобрить», чтобы мы приступили к работе.", "Оценка"),
                ("Готово к проверке", "Работа по заявке выполнена. Пожалуйста, проверьте результат и сообщите, если всё в порядке, чтобы мы могли закрыть задачу.", "Завершение"),
                ("Запрос обратной связи", "Задача закрыта. Пожалуйста, оцените качество выполнения работы в карточке заявки. Ваша обратная связь помогает нам становиться лучше!", "Завершение"),
            ]
            conn.executemany("INSERT INTO canned_responses(title, body, category, created_at) VALUES(?,?,?,?)",
                             [(t, b, c, stamp) for t, b, c in default_canned])

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS kb_categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            icon TEXT NOT NULL DEFAULT 'folder',
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS kb_articles (
            id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES kb_categories(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            is_internal INTEGER NOT NULL DEFAULT 0,
            views_count INTEGER NOT NULL DEFAULT 0,
            helpful_yes INTEGER NOT NULL DEFAULT 0,
            helpful_no INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kb_articles_cat ON kb_articles(category_id);

        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            secret TEXT NOT NULL,
            events TEXT NOT NULL DEFAULT '["ticket.created","ticket.status_changed"]',
            is_active INTEGER NOT NULL DEFAULT 1,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS webhook_logs (
            id INTEGER PRIMARY KEY,
            webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            event TEXT NOT NULL,
            payload TEXT NOT NULL,
            status_code INTEGER,
            response_body TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_logs_wh ON webhook_logs(webhook_id, id);

        CREATE TABLE IF NOT EXISTS ticket_git_links (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            repo TEXT NOT NULL,
            ref_type TEXT NOT NULL CHECK(ref_type IN ('branch','commit','pr')),
            ref_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            author_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_git_links_ticket ON ticket_git_links(ticket_id, id);
        """)

        if conn.execute("SELECT COUNT(*) FROM kb_categories").fetchone()[0] == 0:
            stamp = now()
            conn.execute("INSERT INTO kb_categories (name, slug, icon, sort_order) VALUES (?, ?, ?, ?)",
                         ("Общие вопросы", "general", "help-circle", 1))
            cat_gen = conn.execute("SELECT id FROM kb_categories WHERE slug='general'").fetchone()[0]
            conn.execute("INSERT INTO kb_categories (name, slug, icon, sort_order) VALUES (?, ?, ?, ?)",
                         ("Оплата и часы", "billing", "credit-card", 2))
            cat_bill = conn.execute("SELECT id FROM kb_categories WHERE slug='billing'").fetchone()[0]
            conn.execute("INSERT INTO kb_categories (name, slug, icon, sort_order) VALUES (?, ?, ?, ?)",
                         ("Разработка и API", "dev", "code", 3))
            cat_dev = conn.execute("SELECT id FROM kb_categories WHERE slug='dev'").fetchone()[0]
            conn.execute("INSERT INTO kb_categories (name, slug, icon, sort_order) VALUES (?, ?, ?, ?)",
                         ("Внутренние регламенты", "runbooks", "lock", 4))
            cat_run = conn.execute("SELECT id FROM kb_categories WHERE slug='runbooks'").fetchone()[0]

            default_articles = [
                (cat_gen, "Как правильно составить заявку для быстрого решения",
                 "Чтобы инженер сразу приступил к работе без лишних утокновений, укажите:\n1. Краткую суть проблемы или задачи в названии.\n2. Шаги для воспроизведения (если это баг) или требования к результату (если доработка).\n3. Ссылки на окружение, тестовые учетные записи или логи.\n4. Прикрепите скриншоты или видео через блок прикрепления файлов.\nЗаявки с полным описанием оцениваются и берутся в работу в среднем на 40% быстрее.", 0),
                (cat_gen, "Уровни сервиса (SLA) и регламент первого ответа",
                 "Мы придерживаемся следующих стандартов обслуживания:\n- Первичный ответ инженера: до 4 рабочих часов с момента регистрации заявки.\n- Подготовка оценки трудозатрат: до 8 рабочих часов.\n- Экстренные инциденты (сервис недоступен): реакция до 30 минут.\nСтатус выполнения и таймеры дедлайнов всегда видны в карточке вашей заявки в режиме реального времени.", 0),
                (cat_bill, "Порядок согласования оценок и учета рабочего времени",
                 "Все работы ведутся по прозрачной схеме:\n1. Инженер готовит предварительную оценку трудозатрат (в часах/минутах) с подробным описанием состава работ.\n2. Вы получаете уведомление и можете одобрить оценку либо запросить корректировку прямо в карточке заявки.\n3. До вашего одобрения фактические списания не производятся.\n4. Если в процессе требуются дополнительные часы, инженер создаёт отдельный запрос с обоснованием, который также требует вашего подтверждения.", 0),
                (cat_dev, "Безопасная передача доступов, паролей и ключей API",
                 "Никогда не отправляйте постоянные пароли от боевых баз данных в открытом виде:\n1. По возможности создавайте временного пользователя с ограниченными правами на тестовом контуре (staging).\n2. Для передачи приватных ключей и токенов используйте защищённые хранилища (Bitwarden Send, 1Password или одноразовые ссылки).\n3. При необходимости наш инженер может подключиться совместно через защищённую сессию видеосвязи.", 0),
                (cat_run, "Регламент дежурного инженера: приём и triage заявок",
                 "Внутренняя инструкция для сотрудников поддержки:\n1. В течение 15 минут проверить входящую очередь.\n2. Проверить категорию услуги (service_type) и назначить ответственного.\n3. Оставить первое публичное сообщение («Взяли в работу») либо уточнить недостающие данные.\n4. Зафиксировать внутренние заметки (Internal Notes) по особенностям клиента или инфраструктуры.\n5. Для багов обязательно создать ветку в репозитории и привязать Git-ссылку к карточке заявки.", 1)
            ]
            conn.executemany(
                "INSERT INTO kb_articles (category_id, title, content, is_internal, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                [(cid, title, content, internal, stamp, stamp) for cid, title, content, internal in default_articles]
            )

        # Billing schema extensions
        org_columns = {row["name"] for row in conn.execute("PRAGMA table_info(organizations)")}
        for col, decl in {
            "hourly_rate_rub": "INTEGER NOT NULL DEFAULT 3000",
            "balance_minutes": "INTEGER NOT NULL DEFAULT 0",
            "inn": "TEXT NOT NULL DEFAULT ''",
            "kpp": "TEXT NOT NULL DEFAULT ''",
            "legal_address": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if col not in org_columns:
                conn.execute(f"ALTER TABLE organizations ADD COLUMN {col} {decl}")

        cust_columns = {row["name"] for row in conn.execute("PRAGMA table_info(customer_profiles)")}
        for col, decl in {
            "hourly_rate_rub": "INTEGER NOT NULL DEFAULT 3000",
            "balance_minutes": "INTEGER NOT NULL DEFAULT 0",
            "inn": "TEXT NOT NULL DEFAULT ''",
            "legal_address": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if col not in cust_columns:
                conn.execute(f"ALTER TABLE customer_profiles ADD COLUMN {col} {decl}")

        ticket_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
        if "act_invoice_id" not in ticket_columns:
            conn.execute("ALTER TABLE tickets ADD COLUMN act_invoice_id INTEGER REFERENCES invoices(id)")

        inv_check = {row["name"] for row in conn.execute("PRAGMA table_info(invoices)")} if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoices'").fetchone() else set()
        if inv_check and "customer_id" not in inv_check:
            conn.execute("DROP TABLE invoices")

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY,
            number TEXT NOT NULL UNIQUE,
            doc_type TEXT NOT NULL CHECK(doc_type IN ('invoice', 'act')),
            customer_id INTEGER NOT NULL REFERENCES users(id),
            organization_id INTEGER REFERENCES organizations(id),
            status TEXT NOT NULL DEFAULT 'issued' CHECK(status IN ('draft', 'issued', 'paid', 'cancelled')),
            total_rub INTEGER NOT NULL CHECK(total_rub >= 0),
            total_minutes INTEGER NOT NULL DEFAULT 0,
            hourly_rate_rub INTEGER NOT NULL DEFAULT 3000,
            period_start TEXT,
            period_end TEXT,
            items_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT NOT NULL DEFAULT '',
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            paid_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id, id);
        CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id, id);

        CREATE TABLE IF NOT EXISTS billing_transactions (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES users(id),
            organization_id INTEGER REFERENCES organizations(id),
            tx_type TEXT NOT NULL CHECK(tx_type IN ('deposit', 'charge', 'adjustment')),
            minutes INTEGER NOT NULL,
            amount_rub INTEGER NOT NULL,
            ticket_id INTEGER REFERENCES tickets(id),
            invoice_id INTEGER REFERENCES invoices(id),
            description TEXT NOT NULL,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_billing_tx_customer ON billing_transactions(customer_id, id);
        CREATE INDEX IF NOT EXISTS idx_billing_tx_org ON billing_transactions(organization_id, id);
        CREATE INDEX IF NOT EXISTS idx_tickets_act ON tickets(act_invoice_id);
        """)

        from bot.storage import init_bot_schema
        init_bot_schema(conn)


init_db()


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password, stored):
    try:
        salt, digest = stored.split(":")
        actual = password_hash(password, bytes.fromhex(salt)).split(":")[1]
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row):
    result = {key: row[key] for key in ("id", "name", "email", "role")}
    result["is_manager"] = bool(row["is_manager"])
    return result


def current_user(token):
    if not token:
        raise HTTPException(401, "Требуется вход")
    with db() as conn:
        row = conn.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""", (token_hash(token), now())).fetchone()
    if not row:
        raise HTTPException(401, "Сессия завершена")
    return row


def require_staff(user):
    if user["role"] not in ("employee", "admin"):
        raise HTTPException(403, "Недостаточно прав")


def require_admin(user):
    if user["role"] != "admin":
        raise HTTPException(403, "Недостаточно прав")


def require_dispatcher(user):
    if user["role"] != "admin" and not user["is_manager"]:
        raise HTTPException(403, "Недостаточно прав")


def ticket_for(conn, ticket_id, user):
    row = conn.execute("""SELECT t.*, c.name AS customer_name, COALESCE(o.name,cp.company_name) AS customer_company, a.name AS assignee_name,
        creator.name AS created_by_name
        FROM tickets t JOIN users c ON c.id=t.customer_id
        LEFT JOIN customer_profiles cp ON cp.user_id=c.id
        LEFT JOIN organizations o ON o.id=t.organization_id
        LEFT JOIN users a ON a.id=t.assignee_id
        LEFT JOIN users creator ON creator.id=t.created_by_id WHERE t.id=?""", (ticket_id,)).fetchone()
    if not row or (user["role"] == "customer" and not customer_can_view_ticket(conn, row, user)) or (
        user["role"] == "employee" and not user["is_manager"] and row["assignee_id"] != user["id"]
    ):
        raise HTTPException(404, "Заявка не найдена")
    return row


def customer_organization(conn, user_id):
    return conn.execute("""SELECT o.id,o.name,m.role FROM organization_members m
        JOIN organizations o ON o.id=m.organization_id WHERE m.user_id=?""", (user_id,)).fetchone()


def customer_can_view_ticket(conn, ticket, user):
    if ticket["visibility"] == "organization" and ticket["organization_id"] is not None:
        return bool(conn.execute("SELECT 1 FROM organization_members WHERE organization_id=? AND user_id=?",
                                 (ticket["organization_id"], user["id"])).fetchone())
    return ticket["customer_id"] == user["id"]


def customer_can_write_ticket(conn, ticket, user):
    if user["role"] != "customer":
        return True
    if ticket["visibility"] != "organization" or ticket["organization_id"] is None:
        return ticket["customer_id"] == user["id"]
    return bool(conn.execute("""SELECT 1 FROM organization_members WHERE organization_id=?
        AND user_id=? AND role IN ('owner','member')""", (ticket["organization_id"], user["id"])).fetchone())


def customer_can_decide(conn, ticket, user):
    if ticket["customer_id"] == user["id"] and customer_can_write_ticket(conn, ticket, user):
        return True
    return bool(ticket["visibility"] == "organization" and ticket["organization_id"] is not None and
                conn.execute("""SELECT 1 FROM organization_members WHERE organization_id=?
                    AND user_id=? AND role='owner'""", (ticket["organization_id"], user["id"])).fetchone())


def approved_minutes(conn, ticket_id):
    estimate = latest_estimate(conn, ticket_id)
    if not estimate or estimate["state"] != "approved" or estimate["effort_minutes"] is None:
        return 0
    extra = conn.execute("""SELECT COALESCE(SUM(minutes),0) FROM hour_requests
        WHERE ticket_id=? AND state='approved'""", (ticket_id,)).fetchone()[0]
    return estimate["effort_minutes"] + extra


def actual_minutes(conn, ticket_id):
    return conn.execute("SELECT COALESCE(SUM(minutes),0) FROM time_entries WHERE ticket_id=?",
                        (ticket_id,)).fetchone()[0]


def customer_recipients(conn, ticket):
    recipients = {ticket["customer_id"]} if ticket["visibility"] != "organization" else set()
    if ticket["visibility"] == "organization" and ticket["organization_id"] is not None:
        recipients.update(row["user_id"] for row in conn.execute(
            "SELECT user_id FROM organization_members WHERE organization_id=? AND (role='owner' OR user_id=?)",
            (ticket["organization_id"], ticket["customer_id"])))
    return recipients


def ticket_dict(row):
    return dict(row)


def customer_next_step(ticket, estimate):
    if ticket["status"] == "closed":
        return "Заявка закрыта"
    if ticket["status"] == "done":
        return "Проверьте результат"
    if ticket["status"] == "waiting":
        return "Нужен ваш ответ"
    if ticket["status"] == "working":
        if isinstance(ticket, dict) and ticket.get("pending_hour_request"):
            return "Согласуйте дополнительные часы"
        return "Работа идёт"
    if not ticket["assignee_id"]:
        return "Назначаем ответственного"
    if not estimate or estimate["effort_minutes"] is None:
        return "Сотрудник готовит оценку"
    return {
        "pending": "Одобрите оценку трудозатрат",
        "approved": "Работа согласована и скоро начнётся",
        "rejected": "Ожидаем новую оценку",
        "revision_requested": "Сотрудник пересчитывает трудозатраты",
    }.get(estimate["state"], "Сотрудник готовит оценку")


def latest_estimate(conn, ticket_id):
    return conn.execute("""SELECT e.*,u.name AS author_name FROM estimates e JOIN users u ON u.id=e.author_id
        WHERE e.ticket_id=? ORDER BY e.version DESC LIMIT 1""", (ticket_id,)).fetchone()


def notify(conn, user_id, ticket_id, kind, message):
    if user_id is None:
        return
    conn.execute("INSERT INTO notifications(user_id,ticket_id,kind,text,created_at) VALUES(?,?,?,?,?)",
                 (user_id, ticket_id, kind, message, now()))
    bot_engine.enqueue_notification(conn, user_id, "ticket", ticket_id, kind, message)
    realtime_bus.publish(user_id, {"type": "notification", "target": "ticket", "record_id": ticket_id, "kind": kind, "text": message})
    web_push.enqueue(user_id, {"title": f"Заявка №{ticket_id}", "body": message, "url": f"/#ticket/{ticket_id}", "tag": f"ticket-{ticket_id}"})


def chat_for(conn, chat_id, user):
    row = conn.execute("""SELECT c.*,u.name AS customer_name,a.name AS assignee_name
        FROM chats c JOIN users u ON u.id=c.customer_id
        LEFT JOIN users a ON a.id=c.assignee_id WHERE c.id=?""", (chat_id,)).fetchone()
    if not row or (user["role"] == "customer" and row["customer_id"] != user["id"]) or (
        user["role"] == "employee" and not user["is_manager"] and row["assignee_id"] != user["id"]
    ):
        raise HTTPException(404, "Чат не найден")
    return row


def notify_chat(conn, user_id, chat_id, kind, message):
    if user_id is not None:
        conn.execute("INSERT INTO chat_notifications(user_id,chat_id,kind,text,created_at) VALUES(?,?,?,?,?)",
                     (user_id, chat_id, kind, message, now()))
        bot_engine.enqueue_notification(conn, user_id, "chat", chat_id, kind, message)
        realtime_bus.publish(user_id, {"type": "notification", "target": "chat", "record_id": chat_id, "kind": kind, "text": message})
        web_push.enqueue(user_id, {"title": "Общий чат", "body": message, "url": f"/#chat/{chat_id}", "tag": f"chat-{chat_id}"})


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class Register(Credentials):
    name: str = Field(min_length=2, max_length=100)


class StaffCreate(Register):
    staff_role: Literal["employee", "manager"] = "employee"


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    job_title: str = Field(default="", max_length=100)
    bio: str = Field(default="", max_length=1000)


class CustomerProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    company_name: str = Field(default="", max_length=150)
    phone: str = Field(default="", max_length=40)


class AvatarUpload(BaseModel):
    data_url: str = Field(min_length=32, max_length=3_000_000)


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=10000)
    customer_id: int | None = None
    assignee_id: int | None = None
    visibility: Literal["private", "organization"] = "private"
    service_type: Literal["development", "integration", "support", "consultation", "other"] = "other"


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    request_id: str = Field(min_length=8, max_length=100)


class Assignment(BaseModel):
    assignee_id: int | None


class StatusChange(BaseModel):
    status: Literal["new", "working", "waiting", "done", "closed"]


class EstimateCreate(BaseModel):
    effort_minutes: int = Field(ge=1, le=100_000)
    assessment_minutes: int = Field(ge=1, le=100_000)
    note: str = Field(default="", max_length=3000)


class EstimateDecision(BaseModel):
    estimate_id: int
    action: Literal["approve", "reject", "request_revision"]
    comment: str = Field(default="", max_length=3000)
    proposed_effort_minutes: int | None = Field(default=None, ge=1, le=100_000)


class ChatTicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    message_id: int


class TimeEntryCreate(BaseModel):
    minutes: int = Field(ge=1, le=100_000)
    note: str = Field(min_length=3, max_length=2000)
    request_id: str | None = Field(default=None, min_length=8, max_length=100)


class HourRequestCreate(BaseModel):
    minutes: int = Field(ge=1, le=100_000)
    reason: str = Field(min_length=3, max_length=2000)
    request_id: str | None = Field(default=None, min_length=8, max_length=100)


class HourRequestDecision(BaseModel):
    action: Literal["approve", "reject"]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    owner_id: int


class OrganizationMemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["owner", "member", "viewer"] = "member"


class OrganizationMemberRole(BaseModel):
    role: Literal["owner", "member", "viewer"]


class DeliveryDeadline(BaseModel):
    due_at: datetime | None


class InternalNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CannedResponseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    body: str = Field(min_length=2, max_length=3000)
    category: str = Field(default="Общие", max_length=50)


class TicketRating(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)


class KbArticleCreate(BaseModel):
    category_id: int
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=5, max_length=50000)
    is_internal: bool = False


class KbArticleUpdate(BaseModel):
    category_id: int | None = None
    title: str | None = Field(default=None, min_length=3, max_length=200)
    content: str | None = Field(default=None, min_length=5, max_length=50000)
    is_internal: bool | None = None


class KbFeedback(BaseModel):
    helpful: bool


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    secret: str | None = Field(default=None, max_length=128)
    events: list[str] = Field(default_factory=lambda: ["ticket.created", "ticket.status_changed"])
    description: str = Field(default="", max_length=200)


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=500)
    secret: str | None = Field(default=None, max_length=128)
    events: list[str] | None = None
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=200)


class GitLinkCreate(BaseModel):
    repo: str = Field(min_length=1, max_length=200)
    ref_type: Literal["branch", "commit", "pr"]
    ref_id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=3, max_length=500)
    title: str = Field(default="", max_length=200)


class BillingRateUpdate(BaseModel):
    hourly_rate_rub: int = Field(ge=100, le=1_000_000)
    inn: str = Field(default="", max_length=20)
    kpp: str = Field(default="", max_length=20)
    legal_address: str = Field(default="", max_length=300)


class BillingDepositCreate(BaseModel):
    client_type: Literal["org", "user"]
    client_id: int
    minutes: int = Field(default=0, ge=0)
    amount_rub: int = Field(default=0, ge=0)
    description: str = Field(min_length=2, max_length=300)


class BillingDocumentCreate(BaseModel):
    doc_type: Literal["invoice", "act"]
    client_type: Literal["org", "user"]
    client_id: int
    hours: float | None = Field(default=None, ge=0.1, le=10_000)
    description: str | None = Field(default=None, max_length=300)
    period_start: str | None = None
    period_end: str | None = None
    ticket_ids: list[int] | None = None
    notes: str = Field(default="", max_length=500)


class BillingStatusUpdate(BaseModel):
    status: Literal["issued", "paid", "cancelled"]


def clean_email(email):
    email = email.strip().lower()
    if "@" not in email or " " in email:
        raise HTTPException(422, "Укажите корректный email")
    return email


def create_user(conn, name, email, password, role):
    try:
        cursor = conn.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                              (name.strip(), clean_email(email), password_hash(password), role, now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Email уже используется")
    return conn.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()


def issue_session(conn, user, response):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user["id"], expires))
    response.set_cookie(COOKIE, token, max_age=604800, httponly=True, samesite="lax",
                        secure=os.getenv("APP_SECURE_COOKIE") == "1")
    return public_user(user)


AUTH_RATE_LIMITS: dict[str, list[float]] = {}
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        if origin and origin != expected:
            return Response(status_code=403, content="Invalid origin")
        if not origin and request.headers.get("sec-fetch-site") == "cross-site":
            return Response(status_code=403, content="Cross-site request")

    # Rate limiting for auth endpoints (brute-force protection)
    if request.method == "POST" and request.url.path in ("/api/login", "/api/register"):
        client_ip = request.client.host if request.client else "127.0.0.1"
        is_test_env = (
            client_ip == "testclient"
            or "unittest" in sys.modules
            or "pytest" in sys.modules
            or os.getenv("TESTING") == "1"
        )
        if not is_test_env:
            current_ts = time.time()
            window_start = current_ts - 60.0
            timestamps = [t for t in AUTH_RATE_LIMITS.get(client_ip, []) if t > window_start]
            if len(timestamps) >= RATE_LIMIT_MAX:
                return Response(
                    status_code=429,
                    content=json.dumps({"detail": "Слишком много попыток входа. Попробуйте через минуту."}),
                    media_type="application/json",
                    headers={"Retry-After": "60"}
                )
            timestamps.append(current_ts)
            AUTH_RATE_LIMITS[client_ip] = timestamps

    response = await call_next(request)

    # Security headers for production
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"

    return response


def sign_webhook_payload(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def execute_webhook_sync(wh_id: int, url: str, secret: str, event: str, payload_dict: dict):
    payload_str = json.dumps(payload_dict, ensure_ascii=False)
    payload_bytes = payload_str.encode("utf-8")
    sig = sign_webhook_payload(payload_bytes, secret)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Signature-SHA256": sig,
        "X-Desk-Event": event,
        "User-Agent": "Desk-Webhook/1.0"
    }
    status_code = None
    response_body = ""
    start_time = datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, content=payload_bytes, headers=headers)
            status_code = resp.status_code
            response_body = resp.text[:2000]
    except Exception as exc:
        response_body = f"Error: {exc}"[:2000]
    duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO webhook_logs (webhook_id, event, payload, status_code, response_body, duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (wh_id, event, payload_str[:10000], status_code, response_body, duration_ms, now())
            )
            conn.execute("""
                DELETE FROM webhook_logs WHERE webhook_id=? AND id NOT IN (
                    SELECT id FROM webhook_logs WHERE webhook_id=? ORDER BY id DESC LIMIT 100
                )
            """, (wh_id, wh_id))
    except Exception:
        pass


def dispatch_webhooks(event: str, payload: dict):
    try:
        with db() as conn:
            rows = conn.execute("SELECT id, url, secret, events FROM webhooks WHERE is_active=1").fetchall()
        if not rows:
            return
        for row in rows:
            subscribed_events = []
            raw_ev = row["events"]
            try:
                subscribed_events = json.loads(raw_ev) if raw_ev.startswith("[") else [e.strip() for e in raw_ev.split(",")]
            except Exception:
                subscribed_events = [raw_ev]
            if "*" in subscribed_events or event in subscribed_events:
                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(None, execute_webhook_sync, row["id"], row["url"], row["secret"], event, payload)
                except RuntimeError:
                    import threading
                    t = threading.Thread(target=execute_webhook_sync, args=(row["id"], row["url"], row["secret"], event, payload), daemon=True)
                    t.start()
    except Exception:
        pass


# Браузер сверяет версию по ETag и не держит устаревшие скрипты и стили.
NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
def home(request: Request, desk_session: str | None = Cookie(default=None)):
    wants_cabinet = "login" in request.query_params or "register" in request.query_params
    if not wants_cabinet:
        try:
            current_user(desk_session)
        except HTTPException:
            return FileResponse(ROOT / "web" / "landing.html", headers=NO_CACHE)
    return FileResponse(ROOT / "web" / "index.html", headers=NO_CACHE)


@app.get("/api/public/settings")
def public_settings():
    return {"hourly_rate_rub": int(os.getenv("DEFAULT_HOURLY_RATE_RUB", "3000"))}


@app.get("/landing")
def landing():
    return FileResponse(ROOT / "web" / "landing.html", headers=NO_CACHE)


@app.get("/style.css")
def style():
    return FileResponse(ROOT / "web" / "style.css", media_type="text/css")


@app.get("/design.css")
def design():
    return FileResponse(ROOT / "web" / "design.css", media_type="text/css", headers=NO_CACHE)


@app.get("/design-concepts")
def design_concepts():
    return FileResponse(ROOT / "web" / "design-concepts.html")


@app.get("/main.js")
def script():
    return FileResponse(ROOT / "web" / "main.js", media_type="text/javascript", headers=NO_CACHE)


@app.get("/manifest.json")
def manifest():
    return FileResponse(ROOT / "web" / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(ROOT / "web" / "sw.js", media_type="application/javascript", headers=NO_CACHE)


PWA_ICONS = {"icon-192.png", "icon-512.png", "maskable-512.png", "apple-touch-icon.png", "badge-96.png"}


@app.get("/icons/{name}")
def pwa_png_icon(name: str):
    if name not in PWA_ICONS:
        raise HTTPException(404, "Не найдено")
    return FileResponse(ROOT / "web" / "icons" / name, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/icon.svg")
def pwa_icon():
    return FileResponse(ROOT / "web" / "icon.svg", media_type="image/svg+xml")


# Push-уведомления: сервер отправляет запросы только известным push-сервисам браузеров.
PUSH_HOSTS = ("fcm.googleapis.com", ".push.services.mozilla.com", ".notify.windows.com", "web.push.apple.com", ".push.apple.com")


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=120)
    auth: str = Field(min_length=16, max_length=40)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: PushKeys


class PushEndpoint(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)


def push_endpoint_allowed(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS)


@app.get("/api/push/key")
def push_key(desk_session: str | None = Cookie(default=None)):
    current_user(desk_session)
    return {"public_key": web_push.public_key}


@app.post("/api/push/subscribe")
def push_subscribe(data: PushSubscriptionIn, request: Request, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if not push_endpoint_allowed(data.endpoint):
        raise HTTPException(422, "Этот браузер не поддерживает уведомления")
    try:
        valid = len(b64url_decode(data.keys.p256dh)) == 65 and len(b64url_decode(data.keys.auth)) == 16
    except (ValueError, binascii.Error):
        valid = False
    if not valid:
        raise HTTPException(422, "Некорректная подписка на уведомления")
    with db() as conn:
        conn.execute("""INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,user_agent,created_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,p256dh=excluded.p256dh,auth=excluded.auth,user_agent=excluded.user_agent""",
                     (user["id"], data.endpoint, data.keys.p256dh, data.keys.auth, request.headers.get("user-agent", "")[:300], now()))
    return {"ok": True}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(data: PushEndpoint, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?", (data.endpoint, user["id"]))
    return {"ok": True}


@app.post("/api/push/test")
def push_test(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        devices = conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id=?", (user["id"],)).fetchone()[0]
    if devices:
        web_push.enqueue(user["id"], {"title": "Линия", "body": "Уведомления на этом устройстве работают", "url": "/", "tag": "push-test"})
    return {"devices": devices}


@app.get("/api/events")
async def events_stream(request: Request, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    q = realtime_bus.subscribe(user["id"])

    async def event_generator():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: update\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            realtime_bus.unsubscribe(user["id"], q)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    })


@app.post("/api/register")
def register(data: Register, response: Response):
    with db() as conn:
        user = create_user(conn, data.name, data.email, data.password, "customer")
        return issue_session(conn, user, response)


@app.post("/api/login")
def login(data: Credentials, response: Response):
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (clean_email(data.email),)).fetchone()
        if not user or not user["active"] or not verify_password(data.password, user["password_hash"]):
            raise HTTPException(401, "Неверный email или пароль")
        return issue_session(conn, user, response)


@app.post("/api/logout")
def logout(response: Response, desk_session: str | None = Cookie(default=None)):
    if desk_session:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(desk_session),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(desk_session: str | None = Cookie(default=None)):
    return public_user(current_user(desk_session))


def staff_profile(conn, user):
    row = conn.execute("SELECT job_title,bio,avatar_updated_at,updated_at FROM staff_profiles WHERE user_id=?", (user["id"],)).fetchone()
    avatar_url = f"/api/staff/{user['id']}/avatar?v={row['avatar_updated_at']}" if row and row["avatar_updated_at"] else None
    return {"id": user["id"], "name": user["name"], "role": user["role"],
            "is_manager": bool(user["is_manager"]), "job_title": row["job_title"] if row else "",
            "bio": row["bio"] if row else "", "avatar_url": avatar_url}


def visible_staff(conn, staff_id, viewer):
    person = conn.execute("SELECT * FROM users WHERE id=? AND role IN ('employee','admin') AND active=1", (staff_id,)).fetchone()
    if not person:
        raise HTTPException(404, "Сотрудник не найден")
    if viewer["role"] == "customer":
        allowed = conn.execute("""SELECT 1 FROM tickets t WHERE t.assignee_id=? AND
            ((t.visibility!='organization' AND t.customer_id=?) OR (t.visibility='organization' AND t.organization_id IN
            (SELECT organization_id FROM organization_members WHERE user_id=?)))
            UNION SELECT 1 FROM chats WHERE customer_id=? AND assignee_id=?""",
            (staff_id, viewer["id"], viewer["id"], viewer["id"], staff_id)).fetchone()
        if not allowed:
            raise HTTPException(404, "Сотрудник не найден")
    return person


@app.get("/api/profile/me")
def my_profile(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        return {**staff_profile(conn, user), "email": user["email"]}


@app.patch("/api/profile/me")
def update_profile(data: ProfileUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    name = " ".join(data.name.split())
    if len(name) < 2:
        raise HTTPException(422, "Укажите ФИО")
    title = " ".join(data.job_title.split())
    bio = data.bio.strip()
    stamp = now()
    with db() as conn:
        conn.execute("UPDATE users SET name=? WHERE id=?", (name, user["id"]))
        conn.execute("""INSERT INTO staff_profiles(user_id,job_title,bio,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET job_title=excluded.job_title,bio=excluded.bio,updated_at=excluded.updated_at""",
            (user["id"], title, bio, stamp))
        updated = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        return {**staff_profile(conn, updated), "email": updated["email"]}


def customer_profile(conn, user):
    row = conn.execute("SELECT company_name,phone FROM customer_profiles WHERE user_id=?", (user["id"],)).fetchone()
    return {"id": user["id"], "name": user["name"], "email": user["email"],
            "role": "customer", "company_name": row["company_name"] if row else "",
            "phone": row["phone"] if row else ""}


@app.get("/api/customer-profile/me")
def my_customer_profile(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if user["role"] != "customer":
        raise HTTPException(403, "Недостаточно прав")
    with db() as conn:
        return customer_profile(conn, user)


@app.patch("/api/customer-profile/me")
def update_customer_profile(data: CustomerProfileUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if user["role"] != "customer":
        raise HTTPException(403, "Недостаточно прав")
    name = " ".join(data.name.split())
    if len(name) < 2:
        raise HTTPException(422, "Укажите ваше имя")
    company = " ".join(data.company_name.split())
    phone = data.phone.strip()
    if phone and (len(phone) < 5 or any(c not in "+-() 0123456789" for c in phone)):
        raise HTTPException(422, "Укажите корректный телефон")
    with db() as conn:
        conn.execute("UPDATE users SET name=? WHERE id=?", (name, user["id"]))
        conn.execute("""INSERT INTO customer_profiles(user_id,company_name,phone,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET company_name=excluded.company_name,
            phone=excluded.phone,updated_at=excluded.updated_at""",
            (user["id"], company, phone, now()))
        updated = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        return customer_profile(conn, updated)


@app.post("/api/profile/me/avatar")
def upload_avatar(data: AvatarUpload, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    try:
        header, encoded = data.data_url.split(",", 1)
        formats = {"data:image/png;base64": "PNG", "data:image/jpeg;base64": "JPEG", "data:image/webp;base64": "WEBP"}
        if header not in formats:
            raise ValueError("Unsupported image type")
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2_000_000:
            raise ValueError("Image too large")
        with Image.open(BytesIO(raw)) as image:
            if image.format != formats[header] or image.width * image.height > 12_000_000:
                raise ValueError("Invalid image")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((512, 512))
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=84, method=5)
            avatar = output.getvalue()
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, "Загрузите изображение PNG, JPEG или WebP размером до 2 МБ")
    stamp = now()
    with db() as conn:
        conn.execute("""INSERT INTO staff_profiles(user_id,avatar_webp,avatar_updated_at,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET avatar_webp=excluded.avatar_webp,
            avatar_updated_at=excluded.avatar_updated_at,updated_at=excluded.updated_at""",
            (user["id"], avatar, stamp, stamp))
        return staff_profile(conn, user)


@app.delete("/api/profile/me/avatar")
def delete_avatar(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conn.execute("UPDATE staff_profiles SET avatar_webp=NULL,avatar_updated_at=NULL,updated_at=? WHERE user_id=?", (now(), user["id"]))
        return staff_profile(conn, user)


@app.get("/api/staff/{staff_id}/profile")
def read_staff_profile(staff_id: int, desk_session: str | None = Cookie(default=None)):
    viewer = current_user(desk_session)
    with db() as conn:
        return staff_profile(conn, visible_staff(conn, staff_id, viewer))


@app.get("/api/staff/{staff_id}/avatar")
def read_staff_avatar(staff_id: int, desk_session: str | None = Cookie(default=None)):
    viewer = current_user(desk_session)
    with db() as conn:
        visible_staff(conn, staff_id, viewer)
        row = conn.execute("SELECT avatar_webp FROM staff_profiles WHERE user_id=?", (staff_id,)).fetchone()
        if not row or not row["avatar_webp"]:
            raise HTTPException(404, "Аватар не найден")
        return Response(content=row["avatar_webp"], media_type="image/webp",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/notifications")
def notifications(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        rows = conn.execute("""SELECT n.id,n.ticket_id,n.kind,n.text,n.created_at,n.read_at
            FROM notifications n WHERE n.user_id=? ORDER BY n.id DESC LIMIT 100""", (user["id"],)).fetchall()
        visible = []
        for row in rows:
            try:
                ticket_for(conn, row["ticket_id"], user)
                visible.append(dict(row))
            except HTTPException:
                continue
    return visible


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        row = conn.execute("SELECT * FROM notifications WHERE id=? AND user_id=?",
                           (notification_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Уведомление не найдено")
        ticket_for(conn, row["ticket_id"], user)
        conn.execute("UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?", (now(), notification_id))
    return {"ok": True}


@app.get("/api/chat-notifications")
def chat_notifications(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        rows = conn.execute("""SELECT id,chat_id,kind,text,created_at,read_at FROM chat_notifications
            WHERE user_id=? ORDER BY id DESC LIMIT 100""", (user["id"],)).fetchall()
        visible = []
        for row in rows:
            try:
                chat_for(conn, row["chat_id"], user)
                visible.append(dict(row))
            except HTTPException:
                continue
    return visible


@app.post("/api/chat-notifications/{notification_id}/read")
def read_chat_notification(notification_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        row = conn.execute("SELECT * FROM chat_notifications WHERE id=? AND user_id=?",
                           (notification_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Уведомление не найдено")
        chat_for(conn, row["chat_id"], user)
        conn.execute("UPDATE chat_notifications SET read_at=COALESCE(read_at,?) WHERE id=?", (now(), notification_id))
    return {"ok": True}


@app.get("/api/chats")
def chats(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        sql = """SELECT c.*,u.name AS customer_name,a.name AS assignee_name,
            (SELECT body FROM chat_messages WHERE chat_id=c.id ORDER BY id DESC LIMIT 1) AS last_message
            FROM chats c JOIN users u ON u.id=c.customer_id LEFT JOIN users a ON a.id=c.assignee_id"""
        if user["role"] == "customer":
            rows = conn.execute(sql + " WHERE c.customer_id=? ORDER BY c.updated_at DESC", (user["id"],)).fetchall()
        elif user["role"] == "employee" and not user["is_manager"]:
            rows = conn.execute(sql + " WHERE c.assignee_id=? ORDER BY c.updated_at DESC", (user["id"],)).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY c.updated_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/chats", status_code=201)
def create_chat(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return create_chat_service(conn, user)


def create_chat_service(conn, user):
    if user["role"] != "customer":
        raise HTTPException(403, "Общий чат создаёт заказчик")
    existing = conn.execute("SELECT id FROM chats WHERE customer_id=?", (user["id"],)).fetchone()
    if existing:
        return dict(chat_for(conn, existing["id"], user))
    stamp = now()
    cursor = conn.execute("INSERT INTO chats(customer_id,created_at,updated_at) VALUES(?,?,?)",
                          (user["id"], stamp, stamp))
    for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
        notify_chat(conn, dispatcher["id"], cursor.lastrowid, "new_chat", f"Новый общий чат с {user['name']}")
    return dict(chat_for(conn, cursor.lastrowid, user))


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        chat = chat_for(conn, chat_id, user)
        messages = conn.execute("""SELECT m.id,m.body,m.created_at,m.author_id,u.name AS author_name
            FROM chat_messages m JOIN users u ON u.id=m.author_id
            WHERE m.chat_id=? ORDER BY m.id""", (chat_id,)).fetchall()
        linked = conn.execute("""SELECT l.source_message_id,t.id,t.title,t.status FROM chat_ticket_links l
            JOIN tickets t ON t.id=l.ticket_id WHERE l.chat_id=? ORDER BY l.id DESC""", (chat_id,)).fetchall()
        visible_links = []
        for row in linked:
            try:
                ticket_for(conn, row["id"], user)
                visible_links.append(dict(row))
            except HTTPException:
                continue
        files = conn.execute("""SELECT id,filename,size,content_type,author_id,chat_message_id,created_at
            FROM attachments WHERE chat_id=? ORDER BY id DESC""", (chat_id,)).fetchall()
    return {"chat": dict(chat), "messages": [dict(row) for row in messages],
            "linked_tickets": visible_links, "attachments": [dict(row) for row in files]}


@app.post("/api/chats/{chat_id}/tickets", status_code=201)
def ticket_from_chat(chat_id: int, data: ChatTicketCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        chat = chat_for(conn, chat_id, user)
        message = conn.execute("SELECT id,body,author_id FROM chat_messages WHERE id=? AND chat_id=?",
                               (data.message_id, chat_id)).fetchone()
        if not message:
            raise HTTPException(404, "Сообщение не найдено")
        if message["author_id"] != chat["customer_id"]:
            raise HTTPException(422, "Выберите сообщение заказчика")
        existing = conn.execute("SELECT ticket_id FROM chat_ticket_links WHERE chat_id=? AND source_message_id=?",
                                (chat_id, data.message_id)).fetchone()
        if existing:
            return ticket_dict(ticket_for(conn, existing["ticket_id"], user))
        title = data.title.strip()
        if not title:
            raise HTTPException(422, "Укажите тему")
        stamp = now()
        org = customer_organization(conn, chat["customer_id"])
        cursor = conn.execute("""INSERT INTO tickets(customer_id,assignee_id,created_by_id,title,description,status,
            created_at,updated_at,organization_id,visibility,response_due_at,estimate_due_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (chat["customer_id"], chat["assignee_id"], user["id"], title,
                message["body"], "new", stamp, stamp, org["id"] if org else None,
                "organization" if org else "private", (datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(),
                (datetime.now(timezone.utc)+timedelta(days=3)).isoformat()))
        conn.execute("""INSERT INTO attachments(ticket_id,author_id,filename,stored_name,content_type,size,created_at)
            SELECT ?,author_id,filename,stored_name,content_type,size,? FROM attachments
            WHERE chat_id=? AND chat_message_id=?""", (cursor.lastrowid, stamp, chat_id, data.message_id))
        conn.execute("""INSERT INTO chat_ticket_links(chat_id,ticket_id,source_message_id,created_by,created_at)
            VALUES(?,?,?,?,?)""", (chat_id, cursor.lastrowid, data.message_id, user["id"], stamp))
        notify_chat(conn, chat["customer_id"], chat_id, "ticket_created",
                    f"Из общего чата создана заявка №{cursor.lastrowid}: {title}")
        if chat["assignee_id"]:
            notify(conn, chat["assignee_id"], cursor.lastrowid, "new_ticket", f"Новая заявка №{cursor.lastrowid}: {title}")
        else:
            for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
                notify(conn, dispatcher["id"], cursor.lastrowid, "new_ticket", f"Новая заявка №{cursor.lastrowid}: {title}")
        return ticket_dict(ticket_for(conn, cursor.lastrowid, user))


@app.patch("/api/chats/{chat_id}/assignee")
def assign_chat(chat_id: int, data: Assignment, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        chat = chat_for(conn, chat_id, user)
        if data.assignee_id is not None:
            target = conn.execute("SELECT id FROM users WHERE id=? AND role IN ('employee','admin') AND active=1",
                                  (data.assignee_id,)).fetchone()
            if not target:
                raise HTTPException(422, "Сотрудник не найден")
        conn.execute("UPDATE chats SET assignee_id=?,updated_at=? WHERE id=?", (data.assignee_id, now(), chat_id))
        if data.assignee_id and data.assignee_id != chat["assignee_id"]:
            notify_chat(conn, data.assignee_id, chat_id, "assignment", f"Вам назначен общий чат с {chat['customer_name']}")
        return dict(chat_for(conn, chat_id, user))


@app.post("/api/chats/{chat_id}/messages", status_code=201)
def add_chat_message(chat_id: int, data: MessageCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return add_chat_message_service(conn, user, chat_id, data)


def add_chat_message_service(conn, user, chat_id: int, data: MessageCreate):
    body = data.body.strip()
    if not body:
        raise HTTPException(422, "Введите сообщение")
    chat = chat_for(conn, chat_id, user)
    existing = conn.execute("""SELECT m.id,m.body,m.created_at,m.author_id,u.name AS author_name
        FROM chat_messages m JOIN users u ON u.id=m.author_id
        WHERE m.chat_id=? AND m.author_id=? AND m.request_id=?""",
        (chat_id, user["id"], data.request_id)).fetchone()
    if existing:
        return dict(existing)
    stamp = now()
    cursor = conn.execute("INSERT INTO chat_messages(chat_id,author_id,body,request_id,created_at) VALUES(?,?,?,?,?)",
                          (chat_id, user["id"], body, data.request_id, stamp))
    conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (stamp, chat_id))
    if user["role"] == "customer":
        if chat["assignee_id"]:
            notify_chat(conn, chat["assignee_id"], chat_id, "message", f"Новое сообщение в общем чате с {user['name']}")
        else:
            for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
                notify_chat(conn, dispatcher["id"], chat_id, "message", f"Новое сообщение в общем чате с {user['name']}")
    else:
        notify_chat(conn, chat["customer_id"], chat_id, "message", "Новое сообщение в общем чате")
    message_payload = {"id": cursor.lastrowid, "body": body, "created_at": stamp,
                       "author_id": user["id"], "author_name": user["name"]}
    chat_participants = {chat["customer_id"]}
    if chat["assignee_id"]:
        chat_participants.add(chat["assignee_id"])
    for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
        chat_participants.add(dispatcher["id"])
    realtime_bus.broadcast(chat_participants, {
        "type": "chat_message", "chat_id": chat_id, "message": message_payload
    })
    return message_payload


@app.get("/api/staff")
def staff(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        if user["role"] == "admin" or user["is_manager"]:
            rows = conn.execute("SELECT id,name,email,role,is_manager FROM users WHERE role IN ('employee','admin') AND active=1 ORDER BY name").fetchall()
        else:
            rows = conn.execute("SELECT id,name,email,role,is_manager FROM users WHERE id=?", (user["id"],)).fetchall()
        return [{**dict(row), **staff_profile(conn, row)} for row in rows]


@app.post("/api/staff", status_code=201)
def add_staff(data: StaffCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        created = create_user(conn, data.name, data.email, data.password, "employee")
        if data.staff_role == "manager":
            conn.execute("UPDATE users SET is_manager=1 WHERE id=?", (created["id"],))
            created = conn.execute("SELECT * FROM users WHERE id=?", (created["id"],)).fetchone()
        return public_user(created)


@app.get("/api/customers")
def customers(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        if user["role"] == "admin" or user["is_manager"]:
            rows = conn.execute("SELECT id,name,email FROM users WHERE role='customer' AND active=1 ORDER BY name,email").fetchall()
        else:
            rows = conn.execute("""SELECT id,name,email FROM users WHERE role='customer' AND active=1
                AND (id IN (SELECT customer_id FROM tickets WHERE assignee_id=?)
                  OR id IN (SELECT customer_id FROM chats WHERE assignee_id=?)) ORDER BY name,email""",
                (user["id"], user["id"])).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/tickets")
def tickets(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        sql = """SELECT t.*, c.name AS customer_name, COALESCE(o.name,cp.company_name) AS customer_company, a.name AS assignee_name,
            creator.name AS created_by_name
            FROM tickets t JOIN users c ON c.id=t.customer_id
            LEFT JOIN customer_profiles cp ON cp.user_id=c.id
            LEFT JOIN organizations o ON o.id=t.organization_id
            LEFT JOIN users a ON a.id=t.assignee_id
            LEFT JOIN users creator ON creator.id=t.created_by_id"""
        if user["role"] == "customer":
            rows = conn.execute(sql + " WHERE (t.customer_id=? AND t.visibility!='organization') OR (t.visibility='organization' AND t.organization_id IN (SELECT organization_id FROM organization_members WHERE user_id=?)) ORDER BY t.updated_at DESC,t.id DESC", (user["id"], user["id"])).fetchall()
        elif user["role"] == "employee" and not user["is_manager"]:
            rows = conn.execute(sql + " WHERE t.assignee_id=? ORDER BY t.updated_at DESC,t.id DESC", (user["id"],)).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY t.updated_at DESC,t.id DESC").fetchall()
        result = []
        for row in rows:
            item = ticket_dict(row)
            estimate = latest_estimate(conn, row["id"])
            item["estimate_state"] = estimate["state"] if estimate else None
            item["effort_minutes"] = estimate["effort_minutes"] if estimate else None
            item["approved_minutes"] = approved_minutes(conn, row["id"])
            item["actual_minutes"] = actual_minutes(conn, row["id"])
            item["pending_hour_request"] = bool(conn.execute("SELECT 1 FROM hour_requests WHERE ticket_id=? AND state='pending'", (row["id"],)).fetchone())
            if user["role"] == "customer":
                item["next_step"] = customer_next_step(item, estimate)
            result.append(item)
    return result


@app.get("/api/work-queue")
def work_queue(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        ticket_rows = conn.execute("""SELECT t.id,t.title,t.status,t.customer_id,t.assignee_id,t.updated_at,
            t.response_due_at,t.estimate_due_at,t.delivery_due_at,t.first_staff_response_at,
            c.name AS customer_name,a.name AS assignee_name,
            (SELECT author_id FROM messages WHERE ticket_id=t.id ORDER BY id DESC LIMIT 1) AS last_author_id,
            (SELECT state FROM estimates WHERE ticket_id=t.id ORDER BY version DESC LIMIT 1) AS estimate_state,
            (SELECT effort_minutes FROM estimates WHERE ticket_id=t.id ORDER BY version DESC LIMIT 1) AS effort_minutes,
            (SELECT 1 FROM hour_requests WHERE ticket_id=t.id AND state='pending' LIMIT 1) AS pending_hours
            FROM tickets t JOIN users c ON c.id=t.customer_id LEFT JOIN users a ON a.id=t.assignee_id
            WHERE t.status!='closed' AND (?=1 OR t.assignee_id=?)""",
            (int(user["role"] == "admin" or user["is_manager"]), user["id"])).fetchall()
        chat_rows = conn.execute("""SELECT c.id,c.customer_id,c.assignee_id,c.updated_at,
            u.name AS customer_name,a.name AS assignee_name,
            (SELECT author_id FROM chat_messages WHERE chat_id=c.id ORDER BY id DESC LIMIT 1) AS last_author_id
            FROM chats c JOIN users u ON u.id=c.customer_id LEFT JOIN users a ON a.id=c.assignee_id
            WHERE (?=1 OR c.assignee_id=?)""",
            (int(user["role"] == "admin" or user["is_manager"]), user["id"])).fetchall()
    items = []
    for row in ticket_rows:
        if row["assignee_id"] is None:
            action, priority = "Назначить ответственного", 0
        elif row["last_author_id"] == row["customer_id"]:
            action, priority = "Ответить заказчику", 1
        elif row["estimate_state"] == "revision_requested":
            action, priority = "Пересчитать трудозатраты", 1
        elif row["pending_hours"]:
            action, priority = "Ожидаем согласования дополнительных часов", 3
        elif row["estimate_state"] == "pending" and row["effort_minutes"] is not None:
            action, priority = "Ожидаем решения заказчика", 3
        elif row["effort_minutes"] is None or row["estimate_state"] == "rejected":
            action, priority = "Оценить трудозатраты", 2
        elif row["status"] == "done":
            action, priority = "Ожидаем приёмки результата", 3
        else:
            action, priority = "Продолжить работу", 2
        due_candidates = []
        if row["first_staff_response_at"] is None and row["response_due_at"]:
            due_candidates.append((row["response_due_at"], "Ответить заказчику"))
        if row["effort_minutes"] is None and row["estimate_due_at"]:
            due_candidates.append((row["estimate_due_at"], "Подготовить оценку"))
        if row["delivery_due_at"] and row["status"] not in ("done", "closed"):
            due_candidates.append((row["delivery_due_at"], "Завершить работу"))
        deadline, deadline_action = min(due_candidates) if due_candidates else (None, None)
        overdue = bool(deadline and deadline < now())
        if overdue:
            action, priority = ("Просрочено: назначить ответственного" if row["assignee_id"] is None
                                else f"Просрочено: {deadline_action}"), 0
        items.append({"source":"ticket", "id":row["id"], "title":row["title"],
                      "customer_name":row["customer_name"], "assignee_name":row["assignee_name"],
                      "assignee_id":row["assignee_id"],
                      "updated_at":row["updated_at"], "next_action":action, "priority":priority,
                      "deadline":deadline, "overdue":overdue})
    for row in chat_rows:
        if row["assignee_id"] is None:
            action, priority = "Назначить ответственного", 0
        elif row["last_author_id"] == row["customer_id"]:
            action, priority = "Ответить заказчику", 1
        else:
            action, priority = "Ожидаем ответа заказчика", 3
        items.append({"source":"chat", "id":row["id"], "title":"Общий чат",
                      "customer_name":row["customer_name"], "assignee_name":row["assignee_name"],
                      "assignee_id":row["assignee_id"],
                      "updated_at":row["updated_at"], "next_action":action, "priority":priority})
    return sorted(items, key=lambda item: (item["priority"], -datetime.fromisoformat(item["updated_at"]).timestamp()))


@app.post("/api/tickets", status_code=201)
def add_ticket(data: TicketCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return add_ticket_service(conn, user, data)


def add_ticket_service(conn, user, data: TicketCreate):
    if not data.title.strip() or not data.description.strip():
        raise HTTPException(422, "Заполните тему и описание")
    if user["role"] == "customer":
        if data.customer_id is not None or data.assignee_id is not None:
            raise HTTPException(403, "Недостаточно прав")
        customer_id, assignee_id = user["id"], None
    else:
        if data.customer_id is None:
            raise HTTPException(422, "Выберите заказчика")
        customer = conn.execute("SELECT id FROM users WHERE id=? AND role='customer' AND active=1",
                                (data.customer_id,)).fetchone()
        if not customer:
            raise HTTPException(422, "Заказчик не найден")
        if user["role"] == "employee" and not user["is_manager"]:
            accessible = conn.execute("""SELECT 1 FROM tickets WHERE customer_id=? AND assignee_id=?
                UNION SELECT 1 FROM chats WHERE customer_id=? AND assignee_id=? LIMIT 1""",
                (data.customer_id, user["id"], data.customer_id, user["id"])).fetchone()
            if not accessible:
                raise HTTPException(403, "Нет доступа к этому заказчику")
            if data.assignee_id not in (None, user["id"]):
                raise HTTPException(403, "Сотрудник может назначить только себя")
            assignee_id = user["id"]
        else:
            assignee_id = data.assignee_id
            if assignee_id is not None and not conn.execute(
                "SELECT 1 FROM users WHERE id=? AND role IN ('employee','admin') AND active=1", (assignee_id,)
            ).fetchone():
                raise HTTPException(422, "Сотрудник не найден")
        customer_id = data.customer_id
    organization = customer_organization(conn, customer_id)
    if data.visibility == "organization" and not organization:
        raise HTTPException(422, "Заказчик не состоит в организации")
    if data.visibility == "organization" and user["role"] == "customer" and organization["role"] == "viewer":
        raise HTTPException(403, "Наблюдатель не может создавать общие заявки")
    stamp = now()
    response_due = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    estimate_due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    cursor = conn.execute("""INSERT INTO tickets(customer_id,assignee_id,created_by_id,title,description,status,
        created_at,updated_at,organization_id,visibility,response_due_at,estimate_due_at,service_type)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (customer_id, assignee_id, user["id"], data.title.strip(), data.description.strip(), "new", stamp, stamp,
         organization["id"] if organization else None, data.visibility, response_due, estimate_due, data.service_type))
    if user["role"] != "customer":
        conn.execute("UPDATE tickets SET first_staff_response_at=? WHERE id=?", (stamp, cursor.lastrowid))
    if user["role"] == "customer":
        for admin in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
            notify(conn, admin["id"], cursor.lastrowid, "new_ticket", f"Новая заявка №{cursor.lastrowid}: {data.title.strip()}")
    else:
        notify(conn, customer_id, cursor.lastrowid, "new_ticket",
               f"Для вас создана заявка №{cursor.lastrowid}: {data.title.strip()}")
        if assignee_id and assignee_id != user["id"]:
            notify(conn, assignee_id, cursor.lastrowid, "assignment", f"Вам назначена заявка №{cursor.lastrowid}")
        if assignee_id is None:
            for admin in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1 AND id!=?", (user["id"],)):
                notify(conn, admin["id"], cursor.lastrowid, "new_ticket", f"Новая заявка №{cursor.lastrowid}: {data.title.strip()}")
    result = ticket_dict(ticket_for(conn, cursor.lastrowid, user))
    dispatch_webhooks("ticket.created", {
        "event": "ticket.created",
        "ticket_id": cursor.lastrowid,
        "title": data.title.strip(),
        "customer_id": customer_id,
        "service_type": data.service_type,
        "status": "new",
        "timestamp": stamp
    })
    return result


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        messages = conn.execute("""SELECT m.id,m.body,m.created_at,m.author_id,u.name AS author_name,u.role AS author_role
            FROM messages m JOIN users u ON u.id=m.author_id WHERE ticket_id=? ORDER BY m.id""", (ticket_id,)).fetchall()
        events = conn.execute("""SELECT e.*,u.name AS actor_name FROM ticket_events e JOIN users u ON u.id=e.actor_id
            WHERE ticket_id=? ORDER BY e.id""", (ticket_id,)).fetchall()
        estimates = conn.execute("""SELECT e.*,u.name AS author_name FROM estimates e JOIN users u ON u.id=e.author_id
            WHERE e.ticket_id=? ORDER BY e.version DESC""", (ticket_id,)).fetchall()
        linked = conn.execute("SELECT chat_id,source_message_id FROM chat_ticket_links WHERE ticket_id=?", (ticket_id,)).fetchone()
        if linked:
            try:
                chat_for(conn, linked["chat_id"], user)
            except HTTPException:
                linked = None
        item = ticket_dict(ticket)
        item["approved_minutes"] = approved_minutes(conn, ticket_id)
        item["actual_minutes"] = actual_minutes(conn, ticket_id)
        item["pending_hour_request"] = bool(conn.execute("SELECT 1 FROM hour_requests WHERE ticket_id=? AND state='pending'", (ticket_id,)).fetchone())

        client_org = customer_organization(conn, ticket["customer_id"])
        rate_rub = 3000
        if client_org:
            org_row = conn.execute("SELECT hourly_rate_rub FROM organizations WHERE id=?", (client_org["id"],)).fetchone()
            if org_row and org_row["hourly_rate_rub"]:
                rate_rub = org_row["hourly_rate_rub"]
        else:
            p_row = conn.execute("SELECT hourly_rate_rub FROM customer_profiles WHERE user_id=?", (ticket["customer_id"],)).fetchone()
            if p_row and p_row["hourly_rate_rub"]:
                rate_rub = p_row["hourly_rate_rub"]

        item["hourly_rate_rub"] = rate_rub
        item["cost_rub"] = round(item["approved_minutes"] / 60.0 * rate_rub)
        act_info = None
        if "act_invoice_id" in ticket.keys() and ticket["act_invoice_id"]:
            act_row = conn.execute("SELECT id, number, status, created_at FROM invoices WHERE id=?", (ticket["act_invoice_id"],)).fetchone()
            if act_row:
                act_info = dict(act_row)
        item["act_invoice"] = act_info

        if user["role"] == "customer":
            item["next_step"] = customer_next_step(item, estimates[0] if estimates else None)
        time_rows = conn.execute("""SELECT w.*,u.name AS author_name FROM time_entries w JOIN users u ON u.id=w.author_id
            WHERE w.ticket_id=? ORDER BY w.id DESC""", (ticket_id,)).fetchall()
        hour_rows = conn.execute("""SELECT h.*,u.name AS author_name FROM hour_requests h JOIN users u ON u.id=h.author_id
            WHERE h.ticket_id=? ORDER BY h.id DESC""", (ticket_id,)).fetchall()
        file_rows = conn.execute("SELECT id,filename,size,content_type,author_id,created_at FROM attachments WHERE ticket_id=? ORDER BY id DESC", (ticket_id,)).fetchall()
    return {"ticket": item, "messages": [dict(x) for x in messages],
            "events": [dict(x) for x in events], "estimates": [dict(x) for x in estimates],
            "linked_chat": dict(linked) if linked else None,
            "time_entries": [dict(x) for x in time_rows], "hour_requests": [dict(x) for x in hour_rows],
            "attachments": [dict(x) for x in file_rows]}


@app.post("/api/tickets/{ticket_id}/estimates", status_code=201)
def create_estimate(ticket_id: int, data: EstimateCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        if ticket["assignee_id"] != user["id"]:
            raise HTTPException(403, "Оценку создаёт ответственный сотрудник")
        if ticket["status"] == "closed":
            raise HTTPException(409, "Заявка закрыта")
        previous = latest_estimate(conn, ticket_id)
        if previous and previous["effort_minutes"] is not None and previous["state"] in ("pending", "approved"):
            raise HTTPException(409, "Предыдущая оценка ожидает решения или уже одобрена")
        version = previous["version"] + 1 if previous else 1
        stamp = now()
        if previous and previous["effort_minutes"] is None:
            conn.execute("UPDATE estimates SET state='superseded' WHERE id=?", (previous["id"],))
        cursor = conn.execute("""INSERT INTO estimates(ticket_id,author_id,version,amount_minor,
            assessment_minutes,note,state,created_at,effort_minutes) VALUES(?,?,?,?,?,?,?,?,?)""",
            (ticket_id, user["id"], version, 0, data.assessment_minutes,
             data.note.strip(), "pending", stamp, data.effort_minutes))
        conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
        if ticket["first_staff_response_at"] is None:
            conn.execute("UPDATE tickets SET first_staff_response_at=? WHERE id=?", (stamp, ticket_id))
        for recipient in customer_recipients(conn, ticket):
            notify(conn, recipient, ticket_id, "estimate", f"Оценка заявки №{ticket_id} готова к рассмотрению")
        return dict(conn.execute("SELECT * FROM estimates WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.post("/api/tickets/{ticket_id}/estimates/decision")
def decide_estimate(ticket_id: int, data: EstimateDecision, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return decide_estimate_service(conn, user, ticket_id, data)


def decide_estimate_service(conn, user, ticket_id: int, data: EstimateDecision):
    if user["role"] != "customer":
        raise HTTPException(403, "Решение принимает заказчик")
    if data.action == "request_revision" and not data.comment.strip() and data.proposed_effort_minutes is None:
        raise HTTPException(422, "Укажите желаемые трудозатраты или комментарий")
    ticket = ticket_for(conn, ticket_id, user)
    if not customer_can_decide(conn, ticket, user):
        raise HTTPException(403, "Согласовать часы может автор заявки или владелец компании")
    if ticket["status"] == "closed":
        raise HTTPException(409, "Заявка закрыта")
    estimate = latest_estimate(conn, ticket_id)
    if not estimate or estimate["id"] != data.estimate_id or estimate["state"] != "pending" or estimate["effort_minutes"] is None:
        raise HTTPException(409, "Оценка уже изменена или рассмотрена")
    new_state = {"approve": "approved", "reject": "rejected", "request_revision": "revision_requested"}[data.action]
    stamp = now()
    conn.execute("""UPDATE estimates SET state=?,customer_comment=?,proposed_effort_minutes=?,decided_at=? WHERE id=?""",
                 (new_state, data.comment.strip() or None,
                  data.proposed_effort_minutes if data.action == "request_revision" else None, stamp, estimate["id"]))
    conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
    decision_text = {"approved":"одобрил", "rejected":"отклонил", "revision_requested":"запросил корректировку"}[new_state]
    notify(conn, ticket["assignee_id"], ticket_id, "estimate_decision",
           f"Заказчик {decision_text} оценку заявки №{ticket_id}")
    res = dict(conn.execute("SELECT * FROM estimates WHERE id=?", (estimate["id"],)).fetchone())
    dispatch_webhooks("estimate.decided", {
        "event": "estimate.decided",
        "ticket_id": ticket_id,
        "action": data.action,
        "new_state": new_state,
        "timestamp": stamp
    })
    return res


@app.post("/api/tickets/{ticket_id}/messages", status_code=201)
def add_message(ticket_id: int, data: MessageCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return add_message_service(conn, user, ticket_id, data)


def add_message_service(conn, user, ticket_id: int, data: MessageCreate):
    body = data.body.strip()
    if not body:
        raise HTTPException(422, "Введите сообщение")
    ticket = ticket_for(conn, ticket_id, user)
    if not customer_can_write_ticket(conn, ticket, user):
        raise HTTPException(403, "Наблюдатель может только читать заявку")
    existing = conn.execute("""SELECT m.id,m.body,m.created_at,m.author_id,u.name AS author_name,u.role AS author_role
        FROM messages m JOIN users u ON u.id=m.author_id WHERE m.ticket_id=? AND m.author_id=? AND m.request_id=?""",
        (ticket_id, user["id"], data.request_id)).fetchone()
    if existing:
        return dict(existing)
    if ticket["status"] == "closed":
        raise HTTPException(409, "Заявка закрыта")
    stamp = now()
    cursor = conn.execute("INSERT INTO messages(ticket_id,author_id,body,created_at,request_id) VALUES(?,?,?,?,?)",
                          (ticket_id, user["id"], body, stamp, data.request_id))
    conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
    if user["role"] != "customer" and ticket["first_staff_response_at"] is None:
        conn.execute("UPDATE tickets SET first_staff_response_at=? WHERE id=?", (stamp, ticket_id))
    recipient = ticket["assignee_id"] if user["role"] == "customer" else None
    if user["role"] != "customer":
        for customer_id in customer_recipients(conn, ticket):
            if customer_id != user["id"]:
                notify(conn, customer_id, ticket_id, "message", f"Новое сообщение в заявке №{ticket_id}")
    elif recipient:
        notify(conn, recipient, ticket_id, "message", f"Новое сообщение в заявке №{ticket_id}")
    else:
        for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
            notify(conn, dispatcher["id"], ticket_id, "message", f"Новое сообщение в заявке №{ticket_id}")
    message_payload = {"id": cursor.lastrowid, "body": body, "created_at": stamp,
                       "author_id": user["id"], "author_name": user["name"], "author_role": user["role"]}
    ticket_participants = set(customer_recipients(conn, ticket))
    if ticket["assignee_id"]:
        ticket_participants.add(ticket["assignee_id"])
    for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
        ticket_participants.add(dispatcher["id"])
    realtime_bus.broadcast(ticket_participants, {
        "type": "ticket_message", "ticket_id": ticket_id, "message": message_payload
    })
    return message_payload


@app.patch("/api/tickets/{ticket_id}/assignee")
def assign(ticket_id: int, data: Assignment, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        if data.assignee_id is not None:
            target = conn.execute("SELECT id FROM users WHERE id=? AND role IN ('employee','admin') AND active=1",
                                  (data.assignee_id,)).fetchone()
            if not target:
                raise HTTPException(422, "Сотрудник не найден")
        stamp = now()
        conn.execute("UPDATE tickets SET assignee_id=?,updated_at=? WHERE id=?", (data.assignee_id, stamp, ticket_id))
        conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                     (ticket_id, user["id"], "assignment", str(ticket["assignee_id"]) if ticket["assignee_id"] else None,
                      str(data.assignee_id) if data.assignee_id else None, stamp))
        if data.assignee_id and data.assignee_id != ticket["assignee_id"]:
            notify(conn, data.assignee_id, ticket_id, "assignment", f"Вам назначена заявка №{ticket_id}")
        return ticket_dict(ticket_for(conn, ticket_id, user))


@app.patch("/api/tickets/{ticket_id}/status")
def change_status(ticket_id: int, data: StatusChange, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if user["role"] != "admin" and ticket["assignee_id"] != user["id"]:
            raise HTTPException(403, "Статус меняет ответственный")
        if data.status in ("working", "done", "closed"):
            estimate = latest_estimate(conn, ticket_id)
            if not estimate or estimate["state"] != "approved" or estimate["effort_minutes"] is None:
                raise HTTPException(409, "Для выполнения нужно одобрение оценки заказчиком")
        if data.status in ("done", "closed") and conn.execute("SELECT 1 FROM hour_requests WHERE ticket_id=? AND state='pending'", (ticket_id,)).fetchone():
            raise HTTPException(409, "Дождитесь решения по дополнительным часам")
        if data.status in ("done", "closed") and not actual_minutes(conn, ticket_id):
            raise HTTPException(409, "Перед завершением внесите фактически потраченное время")
        stamp = now()
        conn.execute("UPDATE tickets SET status=?,updated_at=? WHERE id=?", (data.status, stamp, ticket_id))
        conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                     (ticket_id, user["id"], "status", ticket["status"], data.status, stamp))
        if ticket["customer_id"] != user["id"] and ticket["status"] != data.status:
            notify(conn, ticket["customer_id"], ticket_id, "status", f"Статус заявки №{ticket_id} изменён")
        res = ticket_dict(ticket_for(conn, ticket_id, user))
        dispatch_webhooks("ticket.status_changed", {
            "event": "ticket.status_changed",
            "ticket_id": ticket_id,
            "old_status": ticket["status"],
            "new_status": data.status,
            "timestamp": stamp
        })
        return res


@app.post("/api/tickets/{ticket_id}/time-entries", status_code=201)
def add_time_entry(ticket_id: int, data: TimeEntryCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if ticket["assignee_id"] != user["id"]:
            raise HTTPException(403, "Время вносит ответственный сотрудник")
        if data.request_id:
            existing = conn.execute("SELECT * FROM time_entries WHERE ticket_id=? AND author_id=? AND request_id=?",
                                    (ticket_id, user["id"], data.request_id)).fetchone()
            if existing:
                return dict(existing)
        if ticket["status"] not in ("working", "waiting", "done"):
            raise HTTPException(409, "Сначала переведите согласованную заявку в работу")
        if not data.note.strip():
            raise HTTPException(422, "Опишите выполненную работу")
        if actual_minutes(conn, ticket_id) + data.minutes > approved_minutes(conn, ticket_id):
            raise HTTPException(409, "Превышен согласованный лимит часов. Запросите дополнительные часы")
        stamp = now()
        cursor = conn.execute("INSERT INTO time_entries(ticket_id,author_id,minutes,note,created_at,request_id) VALUES(?,?,?,?,?,?)",
                              (ticket_id, user["id"], data.minutes, data.note.strip(), stamp, data.request_id))
        conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
        return dict(conn.execute("SELECT * FROM time_entries WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.post("/api/tickets/{ticket_id}/hour-requests", status_code=201)
def request_hours(ticket_id: int, data: HourRequestCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if ticket["assignee_id"] != user["id"]:
            raise HTTPException(403, "Дополнительные часы запрашивает ответственный")
        if data.request_id:
            existing = conn.execute("SELECT * FROM hour_requests WHERE ticket_id=? AND author_id=? AND request_id=?",
                                    (ticket_id, user["id"], data.request_id)).fetchone()
            if existing:
                return dict(existing)
        if ticket["status"] not in ("working", "waiting") or not approved_minutes(conn, ticket_id):
            raise HTTPException(409, "Работа ещё не согласована")
        if not data.reason.strip():
            raise HTTPException(422, "Объясните, зачем нужны дополнительные часы")
        if conn.execute("SELECT 1 FROM hour_requests WHERE ticket_id=? AND state='pending'", (ticket_id,)).fetchone():
            raise HTTPException(409, "Предыдущий запрос ещё рассматривается")
        stamp = now()
        cursor = conn.execute("INSERT INTO hour_requests(ticket_id,author_id,minutes,reason,created_at,request_id) VALUES(?,?,?,?,?,?)",
                              (ticket_id, user["id"], data.minutes, data.reason.strip(), stamp, data.request_id))
        conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
        for recipient in customer_recipients(conn, ticket):
            notify(conn, recipient, ticket_id, "extra_hours", f"Согласуйте дополнительные часы по заявке №{ticket_id}")
        return dict(conn.execute("SELECT * FROM hour_requests WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.post("/api/tickets/{ticket_id}/hour-requests/{request_id}/decision")
def decide_hours(ticket_id: int, request_id: int, data: HourRequestDecision,
                 desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if user["role"] != "customer":
        raise HTTPException(403, "Решение принимает заказчик")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if not customer_can_decide(conn, ticket, user):
            raise HTTPException(403, "Согласовать часы может автор заявки или владелец компании")
        row = conn.execute("SELECT * FROM hour_requests WHERE id=? AND ticket_id=?", (request_id, ticket_id)).fetchone()
        if not row or row["state"] != "pending":
            raise HTTPException(409, "Запрос уже рассмотрен или не найден")
        if ticket["status"] in ("done", "closed"):
            raise HTTPException(409, "Заявка уже завершена")
        stamp = now()
        state = "approved" if data.action == "approve" else "rejected"
        conn.execute("UPDATE hour_requests SET state=?,decided_by=?,decided_at=? WHERE id=?",
                     (state, user["id"], stamp, request_id))
        conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
        notify(conn, ticket["assignee_id"], ticket_id, "extra_hours_decision",
               f"Заказчик {'одобрил' if state == 'approved' else 'отклонил'} дополнительные часы по заявке №{ticket_id}")
        return dict(conn.execute("SELECT * FROM hour_requests WHERE id=?", (request_id,)).fetchone())


@app.patch("/api/tickets/{ticket_id}/deadline")
def set_delivery_deadline(ticket_id: int, data: DeliveryDeadline, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        ticket_for(conn, ticket_id, user)
        due = data.due_at.astimezone(timezone.utc).isoformat() if data.due_at else None
        conn.execute("UPDATE tickets SET delivery_due_at=?,updated_at=? WHERE id=?", (due, now(), ticket_id))
        return {"delivery_due_at": due}


@app.get("/api/organizations")
def organizations(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        if user["role"] == "admin" or user["is_manager"]:
            rows = conn.execute("SELECT * FROM organizations ORDER BY name").fetchall()
        elif user["role"] == "customer":
            rows = conn.execute("""SELECT o.* FROM organizations o JOIN organization_members m ON m.organization_id=o.id
                WHERE m.user_id=?""", (user["id"],)).fetchall()
        else:
            rows = []
        return [{**dict(row), "members": [dict(x) for x in conn.execute("""SELECT m.user_id,m.role,u.name,u.email
            FROM organization_members m JOIN users u ON u.id=m.user_id WHERE m.organization_id=? ORDER BY m.role,u.name""", (row["id"],))]} for row in rows]


@app.post("/api/organizations", status_code=201)
def create_organization(data: OrganizationCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        owner = conn.execute("SELECT id FROM users WHERE id=? AND role='customer' AND active=1", (data.owner_id,)).fetchone()
        if not owner:
            raise HTTPException(422, "Заказчик не найден")
        if customer_organization(conn, data.owner_id):
            raise HTTPException(409, "Заказчик уже состоит в компании")
        cursor = conn.execute("INSERT INTO organizations(name,created_at) VALUES(?,?)", (data.name.strip(), now()))
        conn.execute("INSERT INTO organization_members(organization_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                     (cursor.lastrowid, data.owner_id, "owner", now()))
        return {"id": cursor.lastrowid, "name": data.name.strip()}


@app.post("/api/organizations/{organization_id}/members", status_code=201)
def add_organization_member(organization_id: int, data: OrganizationMemberCreate,
                            desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM organizations WHERE id=?", (organization_id,)).fetchone():
            raise HTTPException(404, "Компания не найдена")
        member = conn.execute("SELECT id FROM users WHERE email=? AND role='customer' AND active=1", (clean_email(data.email),)).fetchone()
        if not member:
            raise HTTPException(422, "Пользователь с таким email не найден. Сначала он должен зарегистрироваться")
        if customer_organization(conn, member["id"]):
            raise HTTPException(409, "Пользователь уже состоит в компании")
        conn.execute("INSERT INTO organization_members(organization_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                     (organization_id, member["id"], data.role, now()))
        return {"organization_id": organization_id, "user_id": member["id"], "role": data.role}


def organization_member_to_edit(conn, organization_id, member_id):
    row = conn.execute("SELECT * FROM organization_members WHERE organization_id=? AND user_id=?",
                       (organization_id, member_id)).fetchone()
    if not row:
        raise HTTPException(404, "Участник не найден")
    if row["role"] == "owner" and conn.execute(
        "SELECT COUNT(*) FROM organization_members WHERE organization_id=? AND role='owner'",
        (organization_id,)).fetchone()[0] <= 1:
        raise HTTPException(409, "У компании должен остаться владелец")
    return row


@app.patch("/api/organizations/{organization_id}/members/{member_id}")
def update_organization_member(organization_id: int, member_id: int, data: OrganizationMemberRole,
                               desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM organization_members WHERE organization_id=? AND user_id=?",
                               (organization_id, member_id)).fetchone()
        if not current:
            raise HTTPException(404, "Участник не найден")
        if current["role"] == "owner" and data.role != "owner":
            organization_member_to_edit(conn, organization_id, member_id)
        conn.execute("UPDATE organization_members SET role=? WHERE organization_id=? AND user_id=?",
                     (data.role, organization_id, member_id))
        return {"organization_id": organization_id, "user_id": member_id, "role": data.role}


@app.delete("/api/organizations/{organization_id}/members/{member_id}")
def remove_organization_member(organization_id: int, member_id: int,
                               desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        organization_member_to_edit(conn, organization_id, member_id)
        conn.execute("DELETE FROM organization_members WHERE organization_id=? AND user_id=?",
                     (organization_id, member_id))
        return {"ok": True}


async def save_attachment(file: UploadFile):
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename or len(filename) > 180 or Path(filename).suffix.lower() not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(422, "Допустимы изображения, PDF, документы, таблицы, TXT, CSV и ZIP")
    contents = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(contents) > MAX_ATTACHMENT_BYTES or not contents:
        raise HTTPException(413, "Размер файла должен быть от 1 байта до 10 МБ")
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = secrets.token_hex(24)
    path = ATTACHMENT_DIR / stored_name
    path.write_bytes(contents)
    return filename, stored_name, file.content_type or "application/octet-stream", len(contents)


@app.post("/api/tickets/{ticket_id}/attachments", status_code=201)
async def add_ticket_attachment(ticket_id: int, file: UploadFile = File(...),
                                desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        if not customer_can_write_ticket(conn, ticket, user):
            raise HTTPException(403, "Наблюдатель может только читать заявку")
        if ticket["status"] == "closed":
            raise HTTPException(409, "Заявка закрыта")
    filename, stored_name, content_type, size = await save_attachment(file)
    try:
        with db() as conn:
            current_ticket = ticket_for(conn, ticket_id, user)
            if not customer_can_write_ticket(conn, current_ticket, user) or current_ticket["status"] == "closed":
                raise HTTPException(403, "Недостаточно прав для добавления файла")
            cursor = conn.execute("""INSERT INTO attachments(ticket_id,author_id,filename,stored_name,content_type,size,created_at)
                VALUES(?,?,?,?,?,?,?)""", (ticket_id, user["id"], filename, stored_name, content_type, size, now()))
            conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (now(), ticket_id))
            recipient = ticket["assignee_id"] if user["role"] == "customer" else ticket["customer_id"]
            if recipient and recipient != user["id"]:
                notify(conn, recipient, ticket_id, "attachment", f"Новый файл в заявке №{ticket_id}")
            return {"id": cursor.lastrowid, "filename": filename, "size": size}
    except Exception:
        (ATTACHMENT_DIR / stored_name).unlink(missing_ok=True)
        raise


@app.post("/api/chats/{chat_id}/attachments", status_code=201)
async def add_chat_attachment(chat_id: int, file: UploadFile = File(...),
                              message_id: int | None = Form(default=None),
                              desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        chat = chat_for(conn, chat_id, user)
        if message_id is not None and not conn.execute("""SELECT 1 FROM chat_messages WHERE id=? AND chat_id=?
            AND author_id=?""", (message_id, chat_id, user["id"])).fetchone():
            raise HTTPException(403, "Сообщение не найдено")
    filename, stored_name, content_type, size = await save_attachment(file)
    try:
        with db() as conn:
            chat_for(conn, chat_id, user)
            cursor = conn.execute("""INSERT INTO attachments(chat_id,chat_message_id,author_id,filename,stored_name,
                content_type,size,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (chat_id, message_id, user["id"], filename, stored_name, content_type, size, now()))
            conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (now(), chat_id))
            recipient = chat["assignee_id"] if user["role"] == "customer" else chat["customer_id"]
            if recipient and recipient != user["id"]:
                notify_chat(conn, recipient, chat_id, "attachment", "Новый файл в общем чате")
            return {"id": cursor.lastrowid, "filename": filename, "size": size}
    except Exception:
        (ATTACHMENT_DIR / stored_name).unlink(missing_ok=True)
        raise


@app.get("/api/attachments/{attachment_id}")
def download_attachment(attachment_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Файл не найден")
        if row["ticket_id"] is not None:
            ticket_for(conn, row["ticket_id"], user)
        else:
            chat_for(conn, row["chat_id"], user)
    path = ATTACHMENT_DIR / row["stored_name"]
    if not path.is_file():
        path = LEGACY_ATTACHMENT_DIR / row["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path, filename=row["filename"], media_type="application/octet-stream",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def calculate_analytics(conn):
    tickets = conn.execute("""
        SELECT t.*, u.name AS customer_name, a.name AS assignee_name
        FROM tickets t
        JOIN users u ON u.id = t.customer_id
        LEFT JOIN users a ON a.id = t.assignee_id
    """).fetchall()

    staff_rows = conn.execute("""
        SELECT u.id, u.name, u.role, sp.job_title
        FROM users u
        LEFT JOIN staff_profiles sp ON sp.user_id = u.id
        WHERE u.role IN ('employee', 'admin') AND u.active = 1
        ORDER BY u.name
    """).fetchall()

    time_rows = conn.execute("SELECT ticket_id, author_id, minutes FROM time_entries").fetchall()

    staff_stats = {}
    for s in staff_rows:
        staff_stats[s["id"]] = {
            "id": s["id"],
            "name": s["name"],
            "role": s["role"],
            "job_title": s["job_title"] or ("Администратор" if s["role"] == "admin" else "Специалист"),
            "active_tickets": 0,
            "closed_tickets": 0,
            "logged_minutes": 0,
            "ratings": [],
            "avg_rating": None
        }

    for tr in time_rows:
        if tr["author_id"] in staff_stats:
            staff_stats[tr["author_id"]]["logged_minutes"] += tr["minutes"]

    total = len(tickets)
    open_count = 0
    done_count = 0
    response_times = []
    resolution_times = []
    sla_response_total = 0
    sla_response_met = 0
    sla_estimate_total = 0
    sla_estimate_met = 0
    sla_delivery_total = 0
    sla_delivery_met = 0
    ratings = []
    recent_feedback = []
    service_breakdown = {}

    for t in tickets:
        st = t["service_type"] or "other"
        service_breakdown[st] = service_breakdown.get(st, 0) + 1

        if t["status"] in ("new", "working", "waiting"):
            open_count += 1
            if t["assignee_id"] in staff_stats:
                staff_stats[t["assignee_id"]]["active_tickets"] += 1
        else:
            done_count += 1
            if t["assignee_id"] in staff_stats:
                staff_stats[t["assignee_id"]]["closed_tickets"] += 1

        if t["rating"] is not None and t["rating"] > 0:
            ratings.append(t["rating"])
            if t["assignee_id"] in staff_stats:
                staff_stats[t["assignee_id"]]["ratings"].append(t["rating"])
            if t["rating_comment"]:
                recent_feedback.append({
                    "ticket_id": t["id"],
                    "title": t["title"],
                    "customer_name": t["customer_name"],
                    "rating": t["rating"],
                    "comment": t["rating_comment"],
                    "rated_at": t["rated_at"]
                })

        try:
            c_dt = datetime.fromisoformat(t["created_at"])
            if t["first_staff_response_at"]:
                r_dt = datetime.fromisoformat(t["first_staff_response_at"])
                diff_min = max(0, (r_dt - c_dt).total_seconds() / 60.0)
                response_times.append(diff_min)

            if t["response_due_at"]:
                sla_response_total += 1
                resp_target = datetime.fromisoformat(t["response_due_at"])
                if t["first_staff_response_at"] and datetime.fromisoformat(t["first_staff_response_at"]) <= resp_target:
                    sla_response_met += 1

            if t["estimate_due_at"]:
                sla_estimate_total += 1
                est_target = datetime.fromisoformat(t["estimate_due_at"])
                first_est = conn.execute("SELECT created_at FROM estimates WHERE ticket_id=? ORDER BY version ASC LIMIT 1", (t["id"],)).fetchone()
                if first_est and datetime.fromisoformat(first_est["created_at"]) <= est_target:
                    sla_estimate_met += 1

            if t["status"] in ("done", "closed") and t["delivery_due_at"]:
                sla_delivery_total += 1
                del_target = datetime.fromisoformat(t["delivery_due_at"])
                u_dt = datetime.fromisoformat(t["updated_at"])
                if u_dt <= del_target:
                    sla_delivery_met += 1

            if t["status"] in ("done", "closed"):
                u_dt = datetime.fromisoformat(t["updated_at"])
                resolution_times.append(max(0, (u_dt - c_dt).total_seconds() / 3600.0))
        except Exception:
            pass

    for s in staff_stats.values():
        if s["ratings"]:
            s["avg_rating"] = round(sum(s["ratings"]) / len(s["ratings"]), 1)
        del s["ratings"]

    csat_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in ratings:
        if r in csat_dist:
            csat_dist[r] += 1

    return {
        "total_tickets": total,
        "open_tickets": open_count,
        "done_tickets": done_count,
        "avg_response_minutes": round(sum(response_times) / len(response_times), 1) if response_times else 0,
        "avg_resolution_hours": round(sum(resolution_times) / len(resolution_times), 1) if resolution_times else 0,
        "sla_response_met_pct": round(sla_response_met / sla_response_total * 100, 1) if sla_response_total else 100,
        "sla_estimate_met_pct": round(sla_estimate_met / sla_estimate_total * 100, 1) if sla_estimate_total else 100,
        "sla_delivery_met_pct": round(sla_delivery_met / sla_delivery_total * 100, 1) if sla_delivery_total else 100,
        "avg_csat": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "total_ratings": len(ratings),
        "csat_distribution": csat_dist,
        "recent_feedback": sorted(recent_feedback, key=lambda x: x["rated_at"] or "", reverse=True)[:10],
        "staff_stats": list(staff_stats.values()),
        "service_breakdown": service_breakdown
    }


@app.get("/api/tickets/{ticket_id}/internal-notes")
def get_internal_notes(ticket_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        ticket_for(conn, ticket_id, user)
        rows = conn.execute("""
            SELECT n.*, u.name AS author_name, u.role AS author_role
            FROM ticket_internal_notes n
            JOIN users u ON u.id = n.author_id
            WHERE n.ticket_id = ?
            ORDER BY n.id ASC
        """, (ticket_id,)).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/tickets/{ticket_id}/internal-notes", status_code=201)
def add_internal_note(ticket_id: int, data: InternalNoteCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    body = data.body.strip()
    if not body:
        raise HTTPException(422, "Введите текст заметки")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        stamp = now()
        cursor = conn.execute(
            "INSERT INTO ticket_internal_notes(ticket_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, user["id"], body, stamp)
        )
        note_id = cursor.lastrowid
        note_payload = {
            "id": note_id, "ticket_id": ticket_id, "author_id": user["id"],
            "author_name": user["name"], "author_role": user["role"],
            "body": body, "created_at": stamp
        }
        staff_ids = [r["id"] for r in conn.execute("SELECT id FROM users WHERE role IN ('employee', 'admin') AND active=1").fetchall()]
        realtime_bus.broadcast(staff_ids, {
            "type": "internal_note", "ticket_id": ticket_id, "note": note_payload
        })
        dispatch_webhooks("internal_note.created", {
            "event": "internal_note.created",
            "ticket_id": ticket_id,
            "note_id": note_id,
            "author_id": user["id"],
            "timestamp": stamp
        })
        return note_payload


@app.get("/api/canned-responses")
def get_canned_responses(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        rows = conn.execute("SELECT * FROM canned_responses ORDER BY category, title").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/canned-responses", status_code=201)
def create_canned_response(data: CannedResponseCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    title = data.title.strip()
    body = data.body.strip()
    category = (data.category or "Общие").strip()
    if not title or not body:
        raise HTTPException(422, "Заполните название и текст шаблона")
    with db() as conn:
        stamp = now()
        cursor = conn.execute(
            "INSERT INTO canned_responses(title, body, category, created_at) VALUES (?, ?, ?, ?)",
            (title, body, category, stamp)
        )
        return {"id": cursor.lastrowid, "title": title, "body": body, "category": category, "created_at": stamp}


@app.post("/api/tickets/{ticket_id}/rate")
def rate_ticket(ticket_id: int, data: TicketRating, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if user["role"] != "customer":
        raise HTTPException(403, "Оценку оставляет заказчик")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if ticket["customer_id"] != user["id"]:
            raise HTTPException(403, "Оценку оставляет автор заявки")
        if ticket["status"] not in ("done", "closed"):
            raise HTTPException(409, "Оценить можно только выполненную или закрытую заявку")
        stamp = now()
        conn.execute(
            "UPDATE tickets SET rating=?, rating_comment=?, rated_at=? WHERE id=?",
            (data.rating, data.comment.strip() or None, stamp, ticket_id)
        )
        if ticket["assignee_id"]:
            notify(conn, ticket["assignee_id"], ticket_id, "rating", f"Клиент оценил заявку №{ticket_id}: {data.rating}/5")
        participants = set(customer_recipients(conn, ticket))
        if ticket["assignee_id"]:
            participants.add(ticket["assignee_id"])
        for d in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1").fetchall():
            participants.add(d["id"])
        realtime_bus.broadcast(participants, {
            "type": "ticket_rated", "ticket_id": ticket_id, "rating": data.rating
        })
        dispatch_webhooks("ticket.rated", {
            "event": "ticket.rated",
            "ticket_id": ticket_id,
            "rating": data.rating,
            "comment": data.comment.strip() or None,
            "timestamp": stamp
        })
        return {"ok": True, "rating": data.rating, "rating_comment": data.comment.strip() or None, "rated_at": stamp}


@app.get("/api/analytics/summary")
def get_analytics_summary(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        return calculate_analytics(conn)


@app.get("/api/analytics/export.csv")
def export_analytics_csv(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        rows = conn.execute("""
            SELECT t.id, t.title, u.name AS customer_name, o.name AS org_name,
                   a.name AS assignee_name, t.service_type, t.status,
                   t.created_at, t.first_staff_response_at, t.response_due_at,
                   t.estimate_due_at, t.delivery_due_at, t.rating, t.rating_comment,
                   COALESCE((SELECT SUM(te.minutes) FROM time_entries te WHERE te.ticket_id=t.id), 0) AS actual_minutes
            FROM tickets t
            JOIN users u ON u.id = t.customer_id
            LEFT JOIN users a ON a.id = t.assignee_id
            LEFT JOIN organizations o ON o.id = t.organization_id
            ORDER BY t.id DESC
        """).fetchall()

        buf = StringIO()
        buf.write("\ufeff")
        writer = csv.writer(buf, delimiter=";")
        writer.writerow([
            "ID", "Заголовок", "Клиент", "Компания", "Исполнитель", "Услуга",
            "Статус", "Создана", "Первый ответ", "Срок ответа", "Срок оценки",
            "Срок сдачи", "Фактические минуты", "Оценка CSAT", "Отзыв CSAT"
        ])
        for r in rows:
            writer.writerow([
                r["id"],
                r["title"],
                r["customer_name"],
                r["org_name"] or "—",
                r["assignee_name"] or "Не назначен",
                r["service_type"],
                r["status"],
                r["created_at"],
                r["first_staff_response_at"] or "",
                r["response_due_at"] or "",
                r["estimate_due_at"] or "",
                r["delivery_due_at"] or "",
                r["actual_minutes"],
                r["rating"] or "",
                r["rating_comment"] or ""
            ])
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="analytics-{datetime.now().strftime("%Y%m%d")}.csv"'}
        )


# ==============================================================================
# Knowledge Base (База знаний и регламенты)
# ==============================================================================

@app.get("/api/kb/categories")
def get_kb_categories(desk_session: str | None = Cookie(default=None)):
    user = None
    if desk_session:
        try:
            user = current_user(desk_session)
        except HTTPException:
            user = None
    is_staff = user and user["role"] in ("employee", "admin")
    with db() as conn:
        categories = conn.execute("SELECT * FROM kb_categories ORDER BY sort_order, id").fetchall()
        result = []
        for cat in categories:
            if is_staff:
                cnt = conn.execute("SELECT COUNT(*) FROM kb_articles WHERE category_id=?", (cat["id"],)).fetchone()[0]
            else:
                cnt = conn.execute("SELECT COUNT(*) FROM kb_articles WHERE category_id=? AND is_internal=0", (cat["id"],)).fetchone()[0]
            item = dict(cat)
            item["article_count"] = cnt
            result.append(item)
        return result


@app.get("/api/kb/articles")
def get_kb_articles(category_id: int | None = None, q: str | None = None, desk_session: str | None = Cookie(default=None)):
    user = None
    if desk_session:
        try:
            user = current_user(desk_session)
        except HTTPException:
            user = None
    is_staff = user and user["role"] in ("employee", "admin")

    query = """
        SELECT a.id, a.category_id, a.title, a.content, a.is_internal, a.views_count,
               a.helpful_yes, a.helpful_no, a.created_at, a.updated_at,
               c.name AS category_name, c.slug AS category_slug
        FROM kb_articles a
        JOIN kb_categories c ON c.id = a.category_id
        WHERE 1=1
    """
    params = []
    if not is_staff:
        query += " AND a.is_internal = 0"
    if category_id is not None:
        query += " AND a.category_id = ?"
        params.append(category_id)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        query += " AND (LOWER(a.title) LIKE ? OR LOWER(a.content) LIKE ?)"
        params.extend([term, term])
    query += " ORDER BY a.id DESC"

    with db() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["snippet"] = r["content"][:200]
            result.append(item)
        return result


@app.get("/api/kb/suggest")
def suggest_kb_articles(q: str):
    text = q.strip().lower()
    if len(text) < 3:
        return []
    tokens = [t for t in re.split(r"[\s,.-]+", text) if len(t) >= 3]
    if not tokens:
        tokens = [text]
    # Build search patterns (full tokens + 4-char prefixes/stems)
    patterns = set()
    for tok in tokens:
        patterns.add(tok)
        stem = re.sub(r"(иями|ями|иях|ях|ого|ему|ому|ыми|ими|ать|ить|еть|ение|ения|ению|ением|ении|ание|ания|анию|анием|ании|ов|ев|ей|ам|ям|ами|ях|ом|ем|ой|ей|ую|юю|ых|их|ый|ий|ая|яя|ое|ее|ые|ие|ть|ся|сь|[а-яё])$", "", tok)
        if len(stem) >= 3:
            patterns.add(stem)

    with db() as conn:
        all_articles = conn.execute("""
            SELECT a.id, a.title, a.content, c.name AS category_name, a.views_count
            FROM kb_articles a
            JOIN kb_categories c ON c.id = a.category_id
            WHERE a.is_internal = 0
            ORDER BY a.views_count DESC
        """).fetchall()

    scored = []
    for a in all_articles:
        t_lower = a["title"].lower()
        c_lower = a["content"].lower()
        score = 0
        for pat in patterns:
            if pat in t_lower:
                score += 10
            elif pat in c_lower:
                score += 2
        if score > 0:
            scored.append((score, a))

    scored.sort(key=lambda x: (x[0], x[1]["views_count"]), reverse=True)
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "category_name": r["category_name"],
            "snippet": r["content"][:160] + ("..." if len(r["content"]) > 160 else "")
        }
        for _, r in scored[:4]
    ]


@app.get("/api/kb/articles/{article_id}")
def get_kb_article(article_id: int, desk_session: str | None = Cookie(default=None)):
    user = None
    if desk_session:
        try:
            user = current_user(desk_session)
        except HTTPException:
            user = None
    is_staff = user and user["role"] in ("employee", "admin")

    with db() as conn:
        row = conn.execute("""
            SELECT a.*, c.name AS category_name, c.slug AS category_slug
            FROM kb_articles a
            JOIN kb_categories c ON c.id = a.category_id
            WHERE a.id = ?
        """, (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Статья не найдена")
        if row["is_internal"] and not is_staff:
            raise HTTPException(404, "Статья не найдена")
        conn.execute("UPDATE kb_articles SET views_count = views_count + 1 WHERE id = ?", (article_id,))
        return dict(row)


@app.post("/api/kb/articles/{article_id}/feedback")
def submit_kb_feedback(article_id: int, data: KbFeedback):
    with db() as conn:
        row = conn.execute("SELECT id FROM kb_articles WHERE id=?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Статья не найдена")
        if data.helpful:
            conn.execute("UPDATE kb_articles SET helpful_yes = helpful_yes + 1 WHERE id=?", (article_id,))
        else:
            conn.execute("UPDATE kb_articles SET helpful_no = helpful_no + 1 WHERE id=?", (article_id,))
        updated = conn.execute("SELECT helpful_yes, helpful_no FROM kb_articles WHERE id=?", (article_id,)).fetchone()
        return {"ok": True, "helpful_yes": updated["helpful_yes"], "helpful_no": updated["helpful_no"]}


@app.post("/api/kb/articles", status_code=201)
def create_kb_article(data: KbArticleCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    title = data.title.strip()
    content = data.content.strip()
    if not title or not content:
        raise HTTPException(422, "Заполните заголовок и текст статьи")
    stamp = now()
    with db() as conn:
        cat = conn.execute("SELECT id FROM kb_categories WHERE id=?", (data.category_id,)).fetchone()
        if not cat:
            raise HTTPException(422, "Категория не найдена")
        cursor = conn.execute("""
            INSERT INTO kb_articles (category_id, title, content, is_internal, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.category_id, title, content, int(data.is_internal), stamp, stamp))
        return {
            "id": cursor.lastrowid, "category_id": data.category_id, "title": title,
            "content": content, "is_internal": int(data.is_internal), "created_at": stamp, "updated_at": stamp
        }


@app.patch("/api/kb/articles/{article_id}")
def update_kb_article(article_id: int, data: KbArticleUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        article = conn.execute("SELECT * FROM kb_articles WHERE id=?", (article_id,)).fetchone()
        if not article:
            raise HTTPException(404, "Статья не найдена")
        updates = []
        params = []
        if data.category_id is not None:
            updates.append("category_id=?")
            params.append(data.category_id)
        if data.title is not None:
            t = data.title.strip()
            if not t:
                raise HTTPException(422, "Заголовок не может быть пустым")
            updates.append("title=?")
            params.append(t)
        if data.content is not None:
            c = data.content.strip()
            if not c:
                raise HTTPException(422, "Текст статьи не может быть пустым")
            updates.append("content=?")
            params.append(c)
        if data.is_internal is not None:
            updates.append("is_internal=?")
            params.append(int(data.is_internal))
        if updates:
            stamp = now()
            updates.append("updated_at=?")
            params.append(stamp)
            params.append(article_id)
            conn.execute(f"UPDATE kb_articles SET {', '.join(updates)} WHERE id=?", params)
        return dict(conn.execute("SELECT * FROM kb_articles WHERE id=?", (article_id,)).fetchone())


@app.delete("/api/kb/articles/{article_id}")
def delete_kb_article(article_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conn.execute("DELETE FROM kb_articles WHERE id=?", (article_id,))
        return {"ok": True}


# ==============================================================================
# Webhooks (DevOps Gateway & Интеграции)
# ==============================================================================

@app.get("/api/webhooks")
def list_webhooks(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        rows = conn.execute("SELECT * FROM webhooks ORDER BY id DESC").fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["is_active"] = bool(item["is_active"])
            try:
                item["events"] = json.loads(item["events"]) if item["events"].startswith("[") else [e.strip() for e in item["events"].split(",")]
            except Exception:
                item["events"] = [item["events"]]
            cnt = conn.execute("SELECT COUNT(*) FROM webhook_logs WHERE webhook_id=?", (r["id"],)).fetchone()[0]
            last_log = conn.execute("SELECT created_at, status_code FROM webhook_logs WHERE webhook_id=? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
            item["total_deliveries"] = cnt
            item["last_delivery_at"] = last_log["created_at"] if last_log else None
            item["last_status_code"] = last_log["status_code"] if last_log else None
            result.append(item)
        return result


@app.post("/api/webhooks", status_code=201)
def create_webhook(data: WebhookCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    url = data.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(422, "URL вебхука должен начинаться с http:// или https://")
    secret = (data.secret or "").strip() or secrets.token_hex(16)
    events_json = json.dumps(data.events, ensure_ascii=False)
    stamp = now()
    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO webhooks (url, secret, events, is_active, description, created_at) VALUES (?, ?, ?, 1, ?, ?)",
            (url, secret, events_json, data.description.strip(), stamp)
        )
        return {
            "id": cursor.lastrowid, "url": url, "secret": secret, "events": data.events,
            "is_active": True, "description": data.description.strip(), "created_at": stamp
        }


@app.patch("/api/webhooks/{webhook_id}")
def update_webhook(webhook_id: int, data: WebhookUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        wh = conn.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        if not wh:
            raise HTTPException(404, "Вебхук не найден")
        updates = []
        params = []
        if data.url is not None:
            u = data.url.strip()
            if not (u.startswith("http://") or u.startswith("https://")):
                raise HTTPException(422, "URL вебхука должен начинаться с http:// или https://")
            updates.append("url=?")
            params.append(u)
        if data.secret is not None:
            updates.append("secret=?")
            params.append(data.secret.strip() or secrets.token_hex(16))
        if data.events is not None:
            updates.append("events=?")
            params.append(json.dumps(data.events, ensure_ascii=False))
        if data.is_active is not None:
            updates.append("is_active=?")
            params.append(int(data.is_active))
        if data.description is not None:
            updates.append("description=?")
            params.append(data.description.strip())
        if updates:
            params.append(webhook_id)
            conn.execute(f"UPDATE webhooks SET {', '.join(updates)} WHERE id=?", params)
        updated = conn.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        item = dict(updated)
        item["is_active"] = bool(item["is_active"])
        try:
            item["events"] = json.loads(item["events"]) if item["events"].startswith("[") else [e.strip() for e in item["events"].split(",")]
        except Exception:
            item["events"] = [item["events"]]
        return item


@app.delete("/api/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        conn.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,))
        return {"ok": True}


@app.get("/api/webhooks/{webhook_id}/logs")
def get_webhook_logs(webhook_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        wh = conn.execute("SELECT id FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        if not wh:
            raise HTTPException(404, "Вебхук не найден")
        rows = conn.execute("""
            SELECT id, event, payload, status_code, response_body, duration_ms, created_at
            FROM webhook_logs
            WHERE webhook_id=?
            ORDER BY id DESC LIMIT 50
        """, (webhook_id,)).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        wh = conn.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        if not wh:
            raise HTTPException(404, "Вебхук не найден")
    test_payload = {
        "event": "webhook.test",
        "webhook_id": webhook_id,
        "triggered_by": user["name"],
        "timestamp": now(),
        "message": "Тестовое событие от сервиса заявок Линия"
    }
    execute_webhook_sync(wh["id"], wh["url"], wh["secret"], "webhook.test", test_payload)
    with db() as conn:
        last_log = conn.execute("SELECT * FROM webhook_logs WHERE webhook_id=? ORDER BY id DESC LIMIT 1", (webhook_id,)).fetchone()
        return {"ok": True, "log": dict(last_log) if last_log else None}


# ==============================================================================
# Git References (Git ссылки для тикетов)
# ==============================================================================

@app.get("/api/tickets/{ticket_id}/git-links")
def get_ticket_git_links(ticket_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        ticket_for(conn, ticket_id, user)
        rows = conn.execute("""
            SELECT g.*, u.name AS author_name
            FROM ticket_git_links g
            JOIN users u ON u.id = g.author_id
            WHERE g.ticket_id = ?
            ORDER BY g.id DESC
        """, (ticket_id,)).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/tickets/{ticket_id}/git-links", status_code=201)
def add_ticket_git_link(ticket_id: int, data: GitLinkCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    repo = data.repo.strip()
    ref_id = data.ref_id.strip()
    url = data.url.strip()
    title = data.title.strip()
    if not repo or not ref_id or not url:
        raise HTTPException(422, "Заполните репозиторий, идентификатор и URL ссылки")
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("git@")):
        raise HTTPException(422, "Укажите корректный URL ссылки")
    stamp = now()
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        cursor = conn.execute("""
            INSERT INTO ticket_git_links (ticket_id, repo, ref_type, ref_id, url, title, author_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticket_id, repo, data.ref_type, ref_id, url, title, user["id"], stamp))
        link_id = cursor.lastrowid
        link_payload = {
            "id": link_id, "ticket_id": ticket_id, "repo": repo, "ref_type": data.ref_type,
            "ref_id": ref_id, "url": url, "title": title, "author_id": user["id"],
            "author_name": user["name"], "created_at": stamp
        }
        staff_ids = [r["id"] for r in conn.execute("SELECT id FROM users WHERE role IN ('employee', 'admin') AND active=1").fetchall()]
        realtime_bus.broadcast(staff_ids, {"type": "git_link_added", "ticket_id": ticket_id, "link": link_payload})
        return link_payload


@app.delete("/api/tickets/{ticket_id}/git-links/{link_id}")
def delete_ticket_git_link(ticket_id: int, link_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        ticket_for(conn, ticket_id, user)
        conn.execute("DELETE FROM ticket_git_links WHERE id=? AND ticket_id=?", (link_id, ticket_id))
        return {"ok": True}


# ============================================================================
# TRACK 3: BILLING, INVOICING, ACTS, HOURLY RATES & BALANCE
# ============================================================================

def rubles_to_words(n: int) -> str:
    if n <= 0:
        return "Ноль рублей 00 копеек"

    units_m = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    units_f = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    teens = [
        "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
        "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"
    ]
    tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
    hundreds = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]

    def triplet_to_words(triplet: int, is_female: bool) -> str:
        words = []
        h = triplet // 100
        t = (triplet % 100) // 10
        u = triplet % 10
        if h > 0:
            words.append(hundreds[h])
        if t == 1:
            words.append(teens[u])
        else:
            if t > 1:
                words.append(tens[t])
            if u > 0:
                words.append(units_f[u] if is_female else units_m[u])
        return " ".join(words)

    def get_form(val: int, f1: str, f2: str, f5: str) -> str:
        v = val % 100
        if 11 <= v <= 19:
            return f5
        r = v % 10
        if r == 1:
            return f1
        if 2 <= r <= 4:
            return f2
        return f5

    parts = []
    millions = (n // 1_000_000) % 1000
    if millions > 0:
        parts.append(triplet_to_words(millions, False))
        parts.append(get_form(millions, "миллион", "миллиона", "миллионов"))

    thousands = (n // 1000) % 1000
    if thousands > 0:
        parts.append(triplet_to_words(thousands, True))
        parts.append(get_form(thousands, "тысяча", "тысячи", "тысяч"))

    rubs = n % 1000
    if rubs > 0 or not parts:
        parts.append(triplet_to_words(rubs, False))
    parts.append(get_form(n, "рубль", "рубля", "рублей"))

    result = " ".join(filter(None, parts)).strip()
    return result[0].upper() + result[1:] + " 00 копеек"


def format_ru_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        return f"{dt.day} {months[dt.month - 1]} {dt.year} г."
    except Exception:
        return iso_str[:10]


def get_client_billing_info(conn, client_type: str, client_id: int) -> dict:
    if client_type == "org":
        row = conn.execute("SELECT * FROM organizations WHERE id=?", (client_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Организация не найдена")
        owner = conn.execute("SELECT user_id FROM organization_members WHERE organization_id=? AND role='owner'", (client_id,)).fetchone()
        cust_id = owner["user_id"] if owner else None
        if not cust_id:
            m = conn.execute("SELECT user_id FROM organization_members WHERE organization_id=? LIMIT 1", (client_id,)).fetchone()
            cust_id = m["user_id"] if m else 1
        return {
            "client_type": "org",
            "client_id": row["id"],
            "name": row["name"],
            "inn": row["inn"] or "",
            "kpp": row["kpp"] or "",
            "legal_address": row["legal_address"] or "",
            "hourly_rate_rub": row["hourly_rate_rub"] or 3000,
            "balance_minutes": row["balance_minutes"] or 0,
            "organization_id": row["id"],
            "customer_id": cust_id
        }
    else:
        user = conn.execute("SELECT * FROM users WHERE id=? AND role='customer'", (client_id,)).fetchone()
        if not user:
            raise HTTPException(404, "Клиент не найден")
        p = conn.execute("SELECT * FROM customer_profiles WHERE user_id=?", (client_id,)).fetchone()
        company = p["company_name"] if p and p["company_name"] else user["name"]
        return {
            "client_type": "user",
            "client_id": user["id"],
            "name": company,
            "inn": p["inn"] if p and "inn" in p.keys() and p["inn"] else "",
            "kpp": "",
            "legal_address": p["legal_address"] if p and "legal_address" in p.keys() and p["legal_address"] else "",
            "hourly_rate_rub": p["hourly_rate_rub"] if p and "hourly_rate_rub" in p.keys() and p["hourly_rate_rub"] else 3000,
            "balance_minutes": p["balance_minutes"] if p and "balance_minutes" in p.keys() and p["balance_minutes"] else 0,
            "organization_id": None,
            "customer_id": user["id"]
        }


def generate_document_html(doc: dict, client: dict, items: list[dict]) -> str:
    is_act = doc["doc_type"] == "act"
    doc_date_formatted = format_ru_date(doc["created_at"])
    title_h1 = f"АКТ № {doc['number']}" if is_act else f"СЧЁТ НА ОПЛАТУ № {doc['number']}"
    sub_title = f"от {doc_date_formatted}"
    words_total = rubles_to_words(doc["total_rub"])

    rows_tr = ""
    for idx, it in enumerate(items, 1):
        name = html.escape(str(it.get("title", "")))
        hours_val = f"{it.get('hours', 0):.2f}".replace(".", ",")
        rate_val = f"{it.get('rate', 0):,}".replace(",", " ")
        line_sum = it.get('sum_rub') if it.get('sum_rub') is not None else (it.get('rub') if it.get('rub') is not None else round(it.get('hours', 0) * it.get('rate', 0)))
        sum_val = f"{line_sum:,}".replace(",", " ")
        rows_tr += f"""
        <tr>
            <td style="text-align:center;">{idx}</td>
            <td>{name}</td>
            <td style="text-align:right;">{hours_val}</td>
            <td style="text-align:center;">ч</td>
            <td style="text-align:right;">{rate_val} ₽</td>
            <td style="text-align:right;"><strong>{sum_val} ₽</strong></td>
        </tr>
        """

    total_rub_formatted = f"{doc['total_rub']:,}".replace(",", " ")

    period_str = ""
    if doc.get("period_start") and doc.get("period_end"):
        period_str = f"<p><strong>Отчетный период:</strong> с {format_ru_date(doc['period_start'])} по {format_ru_date(doc['period_end'])}</p>"

    bank_header = ""
    if not is_act:
        bank_header = """
        <table class="bank-table">
            <tr>
                <td colspan="2" rowspan="2" style="width:60%;">
                    АО "ТБанк" г. Москва<br>
                    <small style="color:#666;">Банк получателя</small>
                </td>
                <td style="width:15%;">БИК</td>
                <td style="width:25%;">044525974</td>
            </tr>
            <tr>
                <td>Сч. №</td>
                <td>30101810145250000974</td>
            </tr>
            <tr>
                <td>ИНН 7701234567</td>
                <td>КПП 770101001</td>
                <td rowspan="2">Сч. №</td>
                <td rowspan="2">40702810100000012345</td>
            </tr>
            <tr>
                <td colspan="2">
                    ООО "Линия Сервис"<br>
                    <small style="color:#666;">Получатель</small>
                </td>
            </tr>
        </table>
        <div style="margin-top:15px;"></div>
        """

    act_disclaimer = ""
    if is_act:
        act_disclaimer = """
        <p style="margin-top:16px; font-size:13px; line-height:1.4;">
            Вышеперечисленные работы (услуги) выполнены полностью и в срок. Заказчик претензий по объему, качеству и срокам оказания услуг не имеет.
        </p>
        """

    client_display_name = html.escape(str(client['name']))
    signatures = f"""
    <div class="signatures-grid">
        <div class="sig-block">
            <strong>Исполнитель:</strong><br>
            Директор ООО "Линия Сервис"<br><br><br>
            ______________________ /Иванов А.С./<br>
            <small>М.П.</small>
        </div>
        <div class="sig-block">
            <strong>Заказчик:</strong><br>
            {client_display_name}<br><br><br>
            ______________________ /{client_display_name}/<br>
            <small>М.П.</small>
        </div>
    </div>
    """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{title_h1} {sub_title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            font-size: 13px;
            color: #111;
            margin: 20px auto;
            max-width: 820px;
            padding: 20px;
            background: #f8fafc;
        }}
        .doc-sheet {{
            background: #fff;
            padding: 30px 40px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.08);
            border-radius: 4px;
        }}
        .no-print-bar {{
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            justify-content: flex-end;
        }}
        .btn {{
            padding: 8px 16px;
            font-size: 13px;
            font-weight: bold;
            border-radius: 6px;
            cursor: pointer;
            border: 1px solid #cbd5e1;
            background: #fff;
        }}
        .btn.primary {{
            background: #137b69;
            color: #fff;
            border-color: #137b69;
        }}
        h1 {{
            font-size: 20px;
            margin: 0 0 4px 0;
            border-bottom: 2px solid #000;
            padding-bottom: 8px;
        }}
        .bank-table, .items-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 14px 0;
        }}
        .bank-table td {{
            border: 1px solid #000;
            padding: 6px 8px;
            vertical-align: top;
        }}
        .items-table th, .items-table td {{
            border: 1px solid #000;
            padding: 6px 8px;
        }}
        .items-table th {{
            background: #f1f5f9;
        }}
        .parties p {{
            margin: 4px 0;
            line-height: 1.4;
        }}
        .totals-block {{
            margin-top: 10px;
            text-align: right;
        }}
        .totals-table {{
            float: right;
            border-collapse: collapse;
            margin-bottom: 12px;
        }}
        .totals-table td {{
            padding: 4px 10px;
        }}
        .clear {{
            clear: both;
        }}
        .words-block {{
            margin-top: 14px;
            padding-top: 10px;
            border-top: 1px solid #ddd;
        }}
        .signatures-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 40px;
            margin-top: 40px;
        }}
        @media print {{
            body {{
                background: #fff;
                margin: 0;
                padding: 0;
            }}
            .doc-sheet {{
                box-shadow: none;
                padding: 0;
            }}
            .no-print-bar {{
                display: none !important;
            }}
            @page {{
                size: A4;
                margin: 15mm;
            }}
        }}
    </style>
</head>
<body>
    <div class="no-print-bar">
        <button class="btn primary" onclick="window.print()">Распечатать / Сохранить в PDF</button>
        <button class="btn" onclick="window.close()">Закрыть окно</button>
    </div>

    <div class="doc-sheet">
        {bank_header}

        <h1>{title_h1} {sub_title}</h1>

        <div class="parties" style="margin-top:16px;">
            <p><strong>Исполнитель:</strong> ООО "Линия Сервис", ИНН 7701234567, КПП 770101001, 123112, г. Москва, Пресненская наб., д. 12, тел. +7 (495) 120-00-00</p>
            <p><strong>Заказчик:</strong> {client_display_name}{f", ИНН {client['inn']}" if client['inn'] else ""}{f", КПП {client['kpp']}" if client['kpp'] else ""}{f", Адрес: {html.escape(str(client['legal_address']))}" if client['legal_address'] else ""}</p>
            <p><strong>Основание:</strong> Договор оказания услуг технической поддержки и сопровождения</p>
            {period_str}
        </div>

        <table class="items-table">
            <thead>
                <tr>
                    <th style="width:30px;">№</th>
                    <th>Наименование работ (услуг)</th>
                    <th style="width:65px;">Кол-во</th>
                    <th style="width:35px;">Ед.</th>
                    <th style="width:90px;">Цена</th>
                    <th style="width:100px;">Сумма</th>
                </tr>
            </thead>
            <tbody>
                {rows_tr}
            </tbody>
        </table>

        <div class="totals-block">
            <table class="totals-table">
                <tr>
                    <td style="text-align:right;"><strong>Итого:</strong></td>
                    <td style="text-align:right; width:120px;">{total_rub_formatted} ₽</td>
                </tr>
                <tr>
                    <td style="text-align:right;"><strong>В том числе НДС:</strong></td>
                    <td style="text-align:right;">Без НДС</td>
                </tr>
                <tr>
                    <td style="text-align:right;"><strong>Всего к оплате:</strong></td>
                    <td style="text-align:right; font-size:15px;"><strong>{total_rub_formatted} ₽</strong></td>
                </tr>
            </table>
            <div class="clear"></div>
        </div>

        <div class="words-block">
            <p>Всего наименований <strong>{len(items)}</strong>, на сумму <strong>{total_rub_formatted} руб.</strong></p>
            <p><strong>Сумма прописью:</strong> {words_total}</p>
        </div>

        {act_disclaimer}

        {signatures}
    </div>
</body>
</html>"""


@app.get("/api/billing/overview")
def get_billing_overview(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        if user["role"] == "customer":
            org = customer_organization(conn, user["id"])
            if org:
                client_type = "org"
                client_id = org["id"]
                row = conn.execute("SELECT * FROM organizations WHERE id=?", (org["id"],)).fetchone()
                name = row["name"]
                inn = row["inn"] or ""
                hourly_rate_rub = row["hourly_rate_rub"] or 3000
                balance_minutes = row["balance_minutes"] or 0
                cond = "organization_id = ?"
                params = (org["id"],)
            else:
                client_type = "user"
                client_id = user["id"]
                p = conn.execute("SELECT * FROM customer_profiles WHERE user_id=?", (user["id"],)).fetchone()
                name = p["company_name"] if p and p["company_name"] else user["name"]
                inn = p["inn"] if p and "inn" in p.keys() and p["inn"] else ""
                hourly_rate_rub = p["hourly_rate_rub"] if p and "hourly_rate_rub" in p.keys() and p["hourly_rate_rub"] else 3000
                balance_minutes = p["balance_minutes"] if p and "balance_minutes" in p.keys() and p["balance_minutes"] else 0
                cond = "customer_id = ? AND organization_id IS NULL"
                params = (user["id"],)

            active_tickets = conn.execute(f"SELECT id FROM tickets WHERE {cond} AND status IN ('new','working','waiting')", params).fetchall()
            in_progress_minutes = sum(approved_minutes(conn, t["id"]) for t in active_tickets)

            unbilled_tickets = conn.execute(f"SELECT id FROM tickets WHERE {cond} AND status IN ('done','closed') AND act_invoice_id IS NULL", params).fetchall()
            unbilled_minutes = sum(approved_minutes(conn, t["id"]) for t in unbilled_tickets)

            invoices = conn.execute(f"SELECT * FROM invoices WHERE {cond} ORDER BY id DESC LIMIT 50", params).fetchall()
            transactions = conn.execute(f"SELECT * FROM billing_transactions WHERE {cond} ORDER BY id DESC LIMIT 50", params).fetchall()

            return {
                "role": "customer",
                "client_type": client_type,
                "client_id": client_id,
                "name": name,
                "inn": inn,
                "hourly_rate_rub": hourly_rate_rub,
                "balance_minutes": balance_minutes,
                "balance_rub": round(balance_minutes / 60.0 * hourly_rate_rub),
                "in_progress_minutes": in_progress_minutes,
                "in_progress_rub": round(in_progress_minutes / 60.0 * hourly_rate_rub),
                "unbilled_minutes": unbilled_minutes,
                "unbilled_rub": round(unbilled_minutes / 60.0 * hourly_rate_rub),
                "invoices": [dict(r) for r in invoices],
                "transactions": [dict(r) for r in transactions]
            }
        else:
            require_staff(user)
            paid_sum = conn.execute("SELECT COALESCE(SUM(total_rub), 0) FROM invoices WHERE status='paid'").fetchone()[0]

            active_tickets = conn.execute("SELECT id FROM tickets WHERE status IN ('new','working','waiting')").fetchall()
            total_active_mins = sum(approved_minutes(conn, t["id"]) for t in active_tickets)

            clients = []
            for o in conn.execute("SELECT * FROM organizations ORDER BY name").fetchall():
                unb = conn.execute("SELECT id FROM tickets WHERE organization_id=? AND status IN ('done','closed') AND act_invoice_id IS NULL", (o["id"],)).fetchall()
                unb_mins = sum(approved_minutes(conn, t["id"]) for t in unb)
                rate = o["hourly_rate_rub"] or 3000
                bal_m = o["balance_minutes"] or 0
                open_cnt = conn.execute("SELECT COUNT(*) FROM tickets WHERE organization_id=? AND status NOT IN ('closed')", (o["id"],)).fetchone()[0]
                clients.append({
                    "client_type": "org",
                    "client_id": o["id"],
                    "name": o["name"],
                    "inn": o["inn"] or "",
                    "hourly_rate_rub": rate,
                    "balance_minutes": bal_m,
                    "balance_rub": round(bal_m / 60.0 * rate),
                    "unbilled_minutes": unb_mins,
                    "unbilled_rub": round(unb_mins / 60.0 * rate),
                    "open_tickets": open_cnt
                })

            standalone = conn.execute("""
                SELECT u.id, u.name, u.email, p.company_name, p.inn, p.hourly_rate_rub, p.balance_minutes
                FROM users u
                LEFT JOIN organization_members m ON m.user_id = u.id
                LEFT JOIN customer_profiles p ON p.user_id = u.id
                WHERE u.role = 'customer' AND m.organization_id IS NULL
                ORDER BY u.name
            """).fetchall()

            for s in standalone:
                unb = conn.execute("SELECT id FROM tickets WHERE customer_id=? AND organization_id IS NULL AND status IN ('done','closed') AND act_invoice_id IS NULL", (s["id"],)).fetchall()
                unb_mins = sum(approved_minutes(conn, t["id"]) for t in unb)
                rate = s["hourly_rate_rub"] or 3000
                bal_m = s["balance_minutes"] or 0
                cname = s["company_name"] if s["company_name"] else s["name"]
                open_cnt = conn.execute("SELECT COUNT(*) FROM tickets WHERE customer_id=? AND organization_id IS NULL AND status NOT IN ('closed')", (s["id"],)).fetchone()[0]
                clients.append({
                    "client_type": "user",
                    "client_id": s["id"],
                    "name": cname,
                    "inn": s["inn"] or "",
                    "hourly_rate_rub": rate,
                    "balance_minutes": bal_m,
                    "balance_rub": round(bal_m / 60.0 * rate),
                    "unbilled_minutes": unb_mins,
                    "unbilled_rub": round(unb_mins / 60.0 * rate),
                    "open_tickets": open_cnt
                })

            invoices = conn.execute("""
                SELECT i.*, 
                       CASE WHEN i.organization_id IS NOT NULL THEN o.name ELSE u.name END AS client_name
                FROM invoices i
                LEFT JOIN organizations o ON o.id = i.organization_id
                LEFT JOIN users u ON u.id = i.customer_id
                ORDER BY i.id DESC LIMIT 50
            """).fetchall()

            transactions = conn.execute("""
                SELECT t.*,
                       CASE WHEN t.organization_id IS NOT NULL THEN o.name ELSE u.name END AS client_name
                FROM billing_transactions t
                LEFT JOIN organizations o ON o.id = t.organization_id
                LEFT JOIN users u ON u.id = t.customer_id
                ORDER BY t.id DESC LIMIT 50
            """).fetchall()

            return {
                "role": "staff",
                "total_paid_rub": paid_sum,
                "total_active_minutes": total_active_mins,
                "clients": clients,
                "invoices": [dict(r) for r in invoices],
                "transactions": [dict(r) for r in transactions]
            }


@app.get("/api/billing/clients")
def get_billing_clients(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        clients = []
        for o in conn.execute("SELECT * FROM organizations ORDER BY name").fetchall():
            clients.append({
                "client_type": "org",
                "client_id": o["id"],
                "name": o["name"],
                "inn": o["inn"] or "",
                "kpp": o["kpp"] or "",
                "legal_address": o["legal_address"] or "",
                "hourly_rate_rub": o["hourly_rate_rub"] or 3000,
                "balance_minutes": o["balance_minutes"] or 0,
            })
        for s in conn.execute("""
            SELECT u.id, u.name, p.company_name, p.inn, p.legal_address, p.hourly_rate_rub, p.balance_minutes
            FROM users u
            LEFT JOIN organization_members m ON m.user_id = u.id
            LEFT JOIN customer_profiles p ON p.user_id = u.id
            WHERE u.role = 'customer' AND m.organization_id IS NULL
            ORDER BY u.name
        """).fetchall():
            clients.append({
                "client_type": "user",
                "client_id": s["id"],
                "name": s["company_name"] if s["company_name"] else s["name"],
                "inn": s["inn"] or "",
                "kpp": "",
                "legal_address": s["legal_address"] or "",
                "hourly_rate_rub": s["hourly_rate_rub"] or 3000,
                "balance_minutes": s["balance_minutes"] or 0,
            })
        return clients


def update_client_balance(conn, client_type: str, client_id: int, new_balance_minutes: int):
    if client_type == "org":
        conn.execute("UPDATE organizations SET balance_minutes=? WHERE id=?", (new_balance_minutes, client_id))
    else:
        conn.execute("""
            INSERT INTO customer_profiles (user_id, balance_minutes, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance_minutes=excluded.balance_minutes, updated_at=excluded.updated_at
        """, (client_id, new_balance_minutes, now()))


@app.patch("/api/billing/clients/{client_type}/{client_id}")
def update_billing_client(client_type: str, client_id: int, data: BillingRateUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        if client_type == "org":
            conn.execute("""
                UPDATE organizations 
                SET hourly_rate_rub=?, inn=?, kpp=?, legal_address=?
                WHERE id=?
            """, (data.hourly_rate_rub, data.inn.strip(), data.kpp.strip(), data.legal_address.strip(), client_id))
        elif client_type == "user":
            conn.execute("""
                INSERT INTO customer_profiles (user_id, hourly_rate_rub, inn, legal_address, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    hourly_rate_rub=excluded.hourly_rate_rub,
                    inn=excluded.inn,
                    legal_address=excluded.legal_address,
                    updated_at=excluded.updated_at
            """, (client_id, data.hourly_rate_rub, data.inn.strip(), data.legal_address.strip(), now()))
        else:
            raise HTTPException(422, "Неверный тип клиента")
        return {"ok": True}


@app.post("/api/billing/deposit")
def create_billing_deposit(data: BillingDepositCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        client = get_client_billing_info(conn, data.client_type, data.client_id)
        rate = client["hourly_rate_rub"]
        mins = data.minutes
        amount = data.amount_rub
        if mins > 0 and amount == 0:
            amount = round(mins / 60.0 * rate)
        elif amount > 0 and mins == 0:
            mins = int(amount / rate * 60)
        if mins <= 0 and amount <= 0:
            raise HTTPException(422, "Укажите количество минут или сумму пополнения")

        new_bal = client["balance_minutes"] + mins
        update_client_balance(conn, data.client_type, data.client_id, new_bal)

        stamp = now()
        conn.execute("""
            INSERT INTO billing_transactions (customer_id, organization_id, tx_type, minutes, amount_rub, description, created_by, created_at)
            VALUES (?, ?, 'deposit', ?, ?, ?, ?, ?)
        """, (client["customer_id"], client["organization_id"], mins, amount, data.description.strip(), user["id"], stamp))

        return {"ok": True, "new_balance_minutes": new_bal, "new_balance_rub": round(new_bal / 60.0 * rate)}


@app.get("/api/billing/unbilled-tickets")
def get_unbilled_tickets(client_type: str, client_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        client = get_client_billing_info(conn, client_type, client_id)
        rate = client["hourly_rate_rub"]
        if client_type == "org":
            cond = "organization_id = ?"
            params = (client_id,)
        else:
            cond = "customer_id = ? AND organization_id IS NULL"
            params = (client_id,)

        rows = conn.execute(f"""
            SELECT id, title, status, created_at, updated_at
            FROM tickets
            WHERE {cond} AND status IN ('done', 'closed') AND act_invoice_id IS NULL
            ORDER BY id ASC
        """, params).fetchall()

        result = []
        for r in rows:
            app_mins = approved_minutes(conn, r["id"])
            if app_mins > 0:
                cost = round(app_mins / 60.0 * rate)
                result.append({
                    "id": r["id"],
                    "title": r["title"],
                    "status": r["status"],
                    "approved_minutes": app_mins,
                    "hours": round(app_mins / 60.0, 2),
                    "rate_rub": rate,
                    "cost_rub": cost,
                    "created_at": r["created_at"]
                })
        return result


@app.get("/api/billing/invoices")
def list_invoices(doc_type: str | None = None, status: str | None = None, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        query = "SELECT i.*, CASE WHEN i.organization_id IS NOT NULL THEN o.name ELSE u.name END AS client_name FROM invoices i LEFT JOIN organizations o ON o.id = i.organization_id LEFT JOIN users u ON u.id = i.customer_id"
        conds = []
        params = []
        if user["role"] == "customer":
            org = customer_organization(conn, user["id"])
            if org:
                conds.append("i.organization_id = ?")
                params.append(org["id"])
            else:
                conds.append("i.customer_id = ? AND i.organization_id IS NULL")
                params.append(user["id"])
        if doc_type:
            conds.append("i.doc_type = ?")
            params.append(doc_type)
        if status:
            conds.append("i.status = ?")
            params.append(status)

        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY i.id DESC"

        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/billing/invoices", status_code=201)
def create_invoice_document(data: BillingDocumentCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    with db() as conn:
        client = get_client_billing_info(conn, data.client_type, data.client_id)
        rate = client["hourly_rate_rub"]
        stamp = now()
        year = datetime.now(timezone.utc).year

        if data.doc_type == "act":
            if data.ticket_ids:
                placeholders = ",".join("?" * len(data.ticket_ids))
                tickets = conn.execute(f"SELECT * FROM tickets WHERE id IN ({placeholders}) AND act_invoice_id IS NULL", data.ticket_ids).fetchall()
            else:
                if data.client_type == "org":
                    tickets = conn.execute("SELECT * FROM tickets WHERE organization_id=? AND status IN ('done','closed') AND act_invoice_id IS NULL", (data.client_id,)).fetchall()
                else:
                    tickets = conn.execute("SELECT * FROM tickets WHERE customer_id=? AND organization_id IS NULL AND status IN ('done','closed') AND act_invoice_id IS NULL", (data.client_id,)).fetchall()

            if not tickets:
                raise HTTPException(422, "Не найдено завершенных задач с утвержденными часами для формирования акта")

            items = []
            total_mins = 0
            total_rub = 0
            ticket_ids_to_link = []
            for t in tickets:
                mins = approved_minutes(conn, t["id"])
                if mins <= 0:
                    continue
                cost = round(mins / 60.0 * rate)
                total_mins += mins
                total_rub += cost
                ticket_ids_to_link.append(t["id"])
                items.append({
                    "ticket_id": t["id"],
                    "title": f"Заявка №{t['id']}: {t['title']}",
                    "minutes": mins,
                    "hours": round(mins / 60.0, 2),
                    "rate": rate,
                    "sum_rub": cost
                })

            if not items:
                raise HTTPException(422, "Выбранные задачи не содержат согласованных часов")

            count = conn.execute("SELECT COUNT(*) FROM invoices WHERE doc_type='act'").fetchone()[0]
            number = f"АКТ-{year}-{count + 1:03d}"

            cursor = conn.execute("""
                INSERT INTO invoices (number, doc_type, customer_id, organization_id, status, total_rub, total_minutes, hourly_rate_rub, period_start, period_end, items_json, notes, created_by, created_at)
                VALUES (?, 'act', ?, ?, 'issued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (number, client["customer_id"], client["organization_id"], total_rub, total_mins, rate, data.period_start, data.period_end, json.dumps(items, ensure_ascii=False), data.notes, user["id"], stamp))
            act_id = cursor.lastrowid

            conn.execute(f"UPDATE tickets SET act_invoice_id=? WHERE id IN ({','.join('?'*len(ticket_ids_to_link))})", (act_id, *ticket_ids_to_link))

            new_bal = client["balance_minutes"] - total_mins
            update_client_balance(conn, data.client_type, data.client_id, new_bal)

            conn.execute("""
                INSERT INTO billing_transactions (customer_id, organization_id, tx_type, minutes, amount_rub, invoice_id, description, created_by, created_at)
                VALUES (?, ?, 'charge', ?, ?, ?, ?, ?, ?)
            """, (client["customer_id"], client["organization_id"], -total_mins, -total_rub, act_id, f"Списание по Акту {number}", user["id"], stamp))

            dispatch_webhooks("act.created", {"act_id": act_id, "number": number, "total_rub": total_rub, "total_minutes": total_mins, "client_name": client["name"]})

            return {"id": act_id, "number": number, "doc_type": "act", "total_rub": total_rub, "total_minutes": total_mins}

        else:
            hours = data.hours or 10.0
            total_mins = int(hours * 60)
            total_rub = round(hours * rate)
            desc = data.description or f"Пакет технической поддержки: {hours:g} ч"
            items = [{
                "title": desc,
                "minutes": total_mins,
                "hours": hours,
                "rate": rate,
                "sum_rub": total_rub
            }]
            count = conn.execute("SELECT COUNT(*) FROM invoices WHERE doc_type='invoice'").fetchone()[0]
            number = f"СЧ-{year}-{count + 1:03d}"

            cursor = conn.execute("""
                INSERT INTO invoices (number, doc_type, customer_id, organization_id, status, total_rub, total_minutes, hourly_rate_rub, items_json, notes, created_by, created_at)
                VALUES (?, 'invoice', ?, ?, 'issued', ?, ?, ?, ?, ?, ?, ?)
            """, (number, client["customer_id"], client["organization_id"], total_rub, total_mins, rate, json.dumps(items, ensure_ascii=False), data.notes, user["id"], stamp))
            inv_id = cursor.lastrowid

            dispatch_webhooks("invoice.created", {"invoice_id": inv_id, "number": number, "total_rub": total_rub, "hours": hours, "client_name": client["name"]})

            return {"id": inv_id, "number": number, "doc_type": "invoice", "total_rub": total_rub, "total_minutes": total_mins}


@app.get("/api/billing/invoices/{invoice_id}")
def get_invoice_detail(invoice_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Документ не найден")
        if user["role"] == "customer":
            org = customer_organization(conn, user["id"])
            if row["organization_id"]:
                if not org or org["id"] != row["organization_id"]:
                    raise HTTPException(403, "Нет доступа")
            elif row["customer_id"] != user["id"]:
                raise HTTPException(403, "Нет доступа")
        doc = dict(row)
        doc["items"] = json.loads(doc.get("items_json") or "[]")
        return doc


@app.get("/api/billing/invoices/{invoice_id}/print")
def print_invoice_document(invoice_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Документ не найден")
        if user["role"] == "customer":
            org = customer_organization(conn, user["id"])
            if row["organization_id"]:
                if not org or org["id"] != row["organization_id"]:
                    raise HTTPException(403, "Нет доступа")
            elif row["customer_id"] != user["id"]:
                raise HTTPException(403, "Нет доступа")
        doc = dict(row)
        items = json.loads(doc.get("items_json") or "[]")
        client_type = "org" if doc["organization_id"] else "user"
        client_id = doc["organization_id"] if doc["organization_id"] else doc["customer_id"]
        client = get_client_billing_info(conn, client_type, client_id)
        html_content = generate_document_html(doc, client, items)
        return HTMLResponse(content=html_content, status_code=200)


@app.patch("/api/billing/invoices/{invoice_id}/status")
def update_invoice_status(invoice_id: int, data: BillingStatusUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Документ не найден")

        if user["role"] == "customer":
            if data.status != "paid" or row["status"] != "issued":
                raise HTTPException(403, "Клиент может только подтвердить оплату выставленного счета")
            if row["organization_id"]:
                org = customer_organization(conn, user["id"])
                if not org or org["id"] != row["organization_id"]:
                    raise HTTPException(403, "Нет доступа")
            elif row["customer_id"] != user["id"]:
                raise HTTPException(403, "Нет доступа")
        else:
            require_dispatcher(user)

        old_status = row["status"]
        new_status = data.status
        stamp = now()

        if old_status != "paid" and new_status == "paid":
            if row["doc_type"] == "invoice":
                c_type = "org" if row["organization_id"] else "user"
                c_id = row["organization_id"] if row["organization_id"] else row["customer_id"]
                client = get_client_billing_info(conn, c_type, c_id)
                new_bal = client["balance_minutes"] + row["total_minutes"]
                update_client_balance(conn, c_type, c_id, new_bal)

                conn.execute("""
                    INSERT INTO billing_transactions (customer_id, organization_id, tx_type, minutes, amount_rub, invoice_id, description, created_by, created_at)
                    VALUES (?, ?, 'deposit', ?, ?, ?, ?, ?, ?)
                """, (row["customer_id"], row["organization_id"], row["total_minutes"], row["total_rub"], invoice_id, f"Оплата по Счёту {row['number']}", user["id"], stamp))

            conn.execute("UPDATE invoices SET status='paid', paid_at=? WHERE id=?", (stamp, invoice_id))
            dispatch_webhooks("invoice.paid", {"invoice_id": invoice_id, "number": row["number"], "total_rub": row["total_rub"]})

        elif new_status == "cancelled" and old_status != "cancelled":
            if row["doc_type"] == "act":
                conn.execute("UPDATE tickets SET act_invoice_id=NULL WHERE act_invoice_id=? ", (invoice_id,))
                c_type = "org" if row["organization_id"] else "user"
                c_id = row["organization_id"] if row["organization_id"] else row["customer_id"]
                client = get_client_billing_info(conn, c_type, c_id)
                new_bal = client["balance_minutes"] + row["total_minutes"]
                update_client_balance(conn, c_type, c_id, new_bal)

                conn.execute("""
                    INSERT INTO billing_transactions (customer_id, organization_id, tx_type, minutes, amount_rub, invoice_id, description, created_by, created_at)
                    VALUES (?, ?, 'adjustment', ?, ?, ?, ?, ?, ?)
                """, (row["customer_id"], row["organization_id"], row["total_minutes"], row["total_rub"], invoice_id, f"Отмена Акта {row['number']}: возврат баланса", user["id"], stamp))

            conn.execute("UPDATE invoices SET status='cancelled' WHERE id=?", (invoice_id,))
        else:
            conn.execute("UPDATE invoices SET status=? WHERE id=?", (new_status, invoice_id))

        return {"ok": True, "status": new_status}


def bootstrap_admin():
    name = os.getenv("ADMIN_NAME", "Администратор")
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password or len(password) < 8:
        raise SystemExit("Set ADMIN_EMAIL and ADMIN_PASSWORD (at least 8 characters)")
    with db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            raise SystemExit("Admin already exists")
        create_user(conn, name, email, password, "admin")
    print("Admin created")


from bot.service import BotEngine
from bot.routes import install_bot_routes

bot_engine = BotEngine(sys.modules[__name__])
install_bot_routes(app, bot_engine)


if __name__ == "__main__" and sys.argv[1:] == ["bootstrap-admin"]:
    bootstrap_admin()
