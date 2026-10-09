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

import mailer
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
        CREATE TABLE IF NOT EXISTS account_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('invite','reset')),
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL
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
        for name, declaration in {
            "team_role": "TEXT CHECK(team_role IN ('programmer','integrator','devops'))",
            "must_change_credentials": "INTEGER NOT NULL DEFAULT 0",
            "temporary_credentials_expires_at": "TEXT",
        }.items():
            if name not in user_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
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
            "auto_approve_minutes": "INTEGER NOT NULL DEFAULT 0",
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

        CREATE TABLE IF NOT EXISTS service_entries (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES users(id),
            organization_id INTEGER REFERENCES organizations(id),
            ticket_id INTEGER REFERENCES tickets(id),
            author_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL CHECK(kind IN ('chat','call','meeting','other')),
            minutes INTEGER NOT NULL CHECK(minutes>0),
            note TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            request_id TEXT,
            act_invoice_id INTEGER REFERENCES invoices(id)
        );
        CREATE INDEX IF NOT EXISTS idx_service_entries_customer ON service_entries(customer_id, id);
        CREATE INDEX IF NOT EXISTS idx_service_entries_org ON service_entries(organization_id, id);
        CREATE INDEX IF NOT EXISTS idx_service_entries_act ON service_entries(act_invoice_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_service_entries_request ON service_entries(author_id, request_id);
        """)
        invoice_columns = {row['name'] for row in conn.execute('PRAGMA table_info(invoices)')}
        for column, declaration in {'signed_at': 'TEXT', 'signed_by_id': 'INTEGER REFERENCES users(id)'}.items():
            if column not in invoice_columns:
                conn.execute(f'ALTER TABLE invoices ADD COLUMN {column} {declaration}')
        conn.execute("UPDATE invoices SET signed_at=COALESCE(paid_at,created_at),status='issued',paid_at=NULL WHERE doc_type='act' AND status='paid'")
        if 'service_limit_minutes' not in {row['name'] for row in conn.execute('PRAGMA table_info(tickets)')}:
            conn.execute('ALTER TABLE tickets ADD COLUMN service_limit_minutes INTEGER CHECK(service_limit_minutes>=0)')

        # Взаимодействие с клиентом: ответы на сообщения, прочтение, приёмка, итоги встреч, напоминания и почта.
        for table in ("messages", "chat_messages"):
            if "reply_to_id" not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN reply_to_id INTEGER")
        ticket_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
        for col, decl in {"accepted_at": "TEXT", "accepted_by_id": "INTEGER REFERENCES users(id)"}.items():
            if col not in ticket_columns:
                conn.execute(f"ALTER TABLE tickets ADD COLUMN {col} {decl}")
        service_columns = {row["name"] for row in conn.execute("PRAGMA table_info(service_entries)")}
        for col in ("client_summary", "client_next_steps", "shared_at"):
            if col not in service_columns:
                conn.execute(f"ALTER TABLE service_entries ADD COLUMN {col} TEXT")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticket_templates (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
            service_type TEXT NOT NULL DEFAULT 'other', effort_minutes INTEGER, estimate_note TEXT NOT NULL DEFAULT '',
            created_by_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS message_reads (
            kind TEXT NOT NULL CHECK(kind IN ('ticket','chat')), record_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            last_read_id INTEGER NOT NULL, read_at TEXT NOT NULL,
            PRIMARY KEY(kind, record_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS customer_reminders (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, ref_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0, last_sent_at TEXT NOT NULL,
            PRIMARY KEY(user_id, ticket_id, kind, ref_id)
        );
        CREATE TABLE IF NOT EXISTS email_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            notify INTEGER NOT NULL, digest INTEGER NOT NULL DEFAULT 1,
            digest_emails TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS email_outbox (
            id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            to_addr TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
            subject TEXT, text_body TEXT, html_body TEXT,
            state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL, lease_until REAL, lease_token TEXT,
            last_error TEXT, created_at TEXT NOT NULL, sent_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_email_outbox_pending ON email_outbox(state, available_at, id);
        CREATE TABLE IF NOT EXISTS email_tokens (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL CHECK(purpose IN ('action','reply')), action TEXT,
            ticket_id INTEGER, chat_id INTEGER, ref_id INTEGER,
            expires_at TEXT NOT NULL, used_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS email_inbound (
            message_id TEXT PRIMARY KEY, user_id INTEGER, kind TEXT, record_id INTEGER,
            result TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS digest_log (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            period TEXT NOT NULL, sent_at TEXT NOT NULL, PRIMARY KEY(user_id, period)
        );
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
    result["team_role"] = row["team_role"]
    result["must_change_credentials"] = bool(row["must_change_credentials"])
    return result


def current_user(token, allow_temporary=False):
    if not token:
        raise HTTPException(401, "Требуется вход")
    with db() as conn:
        row = conn.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""", (token_hash(token), now())).fetchone()
    if not row:
        raise HTTPException(401, "Сессия завершена")
    if row["must_change_credentials"]:
        if row["temporary_credentials_expires_at"] <= now():
            raise HTTPException(401, "Временный доступ истёк. Обратитесь к менеджеру")
        if not allow_temporary:
            raise HTTPException(403, "Сначала замените временные логин и пароль")
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


def customer_can_decline(conn, ticket, user):
    """Заявку, которую за заказчика создала команда, он может отклонить, пока работа не согласована."""
    if ticket["status"] != "new" or not customer_can_decide(conn, ticket, user):
        return False
    creator = conn.execute("SELECT role FROM users WHERE id=?", (ticket["created_by_id"],)).fetchone()
    if not creator or creator["role"] == "customer":
        return False
    return not conn.execute("SELECT 1 FROM estimates WHERE ticket_id=? AND state='approved'", (ticket["id"],)).fetchone()


def customer_can_decide(conn, ticket, user):
    if user["role"] != "customer":
        return False
    if ticket["visibility"] != "organization" or ticket["organization_id"] is None:
        return ticket["customer_id"] == user["id"]
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


SERVICE_KIND_NAMES = {"chat": "переписка", "call": "созвон", "meeting": "встреча", "other": "прочее"}
# Клиент не видит отдельные записи сопровождения: в акте они сворачиваются в одну строку.
SERVICE_ACT_TITLE = "Консультационное сопровождение и координация работ"

SERVICE_ENTRY_SELECT = """SELECT s.*, a.name AS author_name, t.title AS ticket_title,
    COALESCE(o.name, NULLIF(cp.company_name,''), c.name) AS client_name, i.number AS act_number
    FROM service_entries s JOIN users a ON a.id=s.author_id JOIN users c ON c.id=s.customer_id
    LEFT JOIN customer_profiles cp ON cp.user_id=s.customer_id
    LEFT JOIN organizations o ON o.id=s.organization_id
    LEFT JOIN tickets t ON t.id=s.ticket_id
    LEFT JOIN invoices i ON i.id=s.act_invoice_id"""


MESSAGE_SELECT = """SELECT m.id,m.body,m.created_at,m.author_id,u.name AS author_name,u.role AS author_role,
    m.reply_to_id,r.body AS reply_body,ru.name AS reply_author_name
    FROM {table} m JOIN users u ON u.id=m.author_id
    LEFT JOIN {table} r ON r.id=m.reply_to_id LEFT JOIN users ru ON ru.id=r.author_id"""
TICKET_MESSAGE_SELECT = MESSAGE_SELECT.format(table="messages")
CHAT_MESSAGE_SELECT = MESSAGE_SELECT.format(table="chat_messages")
# Клиенту видны только дата, вид и итоги встречи — без минут и внутренней заметки.
MEETING_SUMMARY_SELECT = """SELECT s.id,s.kind,s.ticket_id,s.occurred_at,s.shared_at,s.client_summary,s.client_next_steps,
    a.name AS author_name FROM service_entries s JOIN users a ON a.id=s.author_id"""


def message_dict(row):
    item = dict(row)
    if item.get("reply_body") and len(item["reply_body"]) > 240:
        item["reply_body"] = item["reply_body"][:240].rstrip() + "…"
    return item


def checked_reply(conn, table, key, record_id, reply_to_id):
    if reply_to_id is None:
        return None
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id=? AND {key}=?", (reply_to_id, record_id)).fetchone():
        raise HTTPException(422, "Сообщение для ответа не найдено")
    return reply_to_id


def mark_read(conn, kind, record_id, user_id, last_id):
    conn.execute("""INSERT INTO message_reads(kind,record_id,user_id,last_read_id,read_at) VALUES(?,?,?,?,?)
        ON CONFLICT(kind,record_id,user_id) DO UPDATE SET last_read_id=MAX(last_read_id,excluded.last_read_id),
        read_at=excluded.read_at""", (kind, record_id, user_id, last_id, now()))


def read_state(conn, kind, record_id):
    """Сколько прочитала каждая сторона: заказчик видит отметку «прочитано командой», команда — «прочитано заказчиком»."""
    rows = conn.execute("""SELECT u.role='customer' AS customer, MAX(r.last_read_id) AS last_id FROM message_reads r
        JOIN users u ON u.id=r.user_id WHERE r.kind=? AND r.record_id=? GROUP BY u.role='customer'""", (kind, record_id)).fetchall()
    result = {"customer_read_id": 0, "team_read_id": 0}
    for row in rows:
        result["customer_read_id" if row["customer"] else "team_read_id"] = row["last_id"] or 0
    return result


def client_condition(client_type, client_id, prefix=""):
    if client_type == "org":
        return f"{prefix}organization_id = ?", (client_id,)
    return f"{prefix}customer_id = ? AND {prefix}organization_id IS NULL", (client_id,)


def unbilled_service_minutes(conn, client_type, client_id):
    cond, params = client_condition(client_type, client_id)
    return conn.execute(f"SELECT COALESCE(SUM(minutes),0) FROM service_entries WHERE {cond} AND act_invoice_id IS NULL",
                        params).fetchone()[0]


def customer_recipients(conn, ticket):
    recipients = {ticket["customer_id"]} if ticket["visibility"] != "organization" else set()
    if ticket["visibility"] == "organization" and ticket["organization_id"] is not None:
        recipients.update(row["user_id"] for row in conn.execute(
            "SELECT user_id FROM organization_members WHERE organization_id=? AND (role='owner' OR user_id=?)",
            (ticket["organization_id"], ticket["customer_id"])))
    return recipients


def customer_decision_recipients(conn, ticket):
    if ticket["visibility"] == "organization" and ticket["organization_id"] is not None:
        return {row["id"] for row in available_owners(conn, ticket["organization_id"])}
    return {ticket["customer_id"]}


def ticket_dict(row):
    return dict(row)


def available_owners(conn, organization_id, exclude_id=0):
    return conn.execute("""SELECT u.id,u.name FROM organization_members m JOIN users u ON u.id=m.user_id
        WHERE m.organization_id=? AND m.role='owner' AND u.active=1 AND u.id!=?
        AND (u.must_change_credentials=0 OR u.temporary_credentials_expires_at>?)
        AND NOT EXISTS (SELECT 1 FROM account_tokens a WHERE a.user_id=u.id AND a.kind='invite')""",
        (organization_id, exclude_id, now())).fetchall()


def customer_next_step(ticket, estimate, conn=None, user=None):
    if conn is not None and user is not None:
        can_decide = customer_can_decide(conn, ticket, user)
        decision_pending = ticket["status"] == "done" or (isinstance(ticket, dict) and ticket.get("pending_hour_request")) or (estimate and estimate["state"] == "pending")
        if decision_pending and ticket["visibility"] == "organization":
            owners = available_owners(conn, ticket["organization_id"])
            if not owners:
                return "Нет доступного владельца — обратитесь к менеджеру"
            if not can_decide:
                return "Ожидаем решения владельца: " + ", ".join(x["name"] for x in owners)
        if ticket["status"] == "waiting" and not customer_can_write_ticket(conn, ticket, user):
            return "Ожидаем ответа участника компании"
    if ticket["status"] == "closed":
        return "Заявка закрыта"
    if ticket["status"] == "done":
        return "Проверьте и примите работу"
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


def auto_approve_estimate(conn, ticket_id, customer_id, estimate_id, effort_minutes):
    """Оценку в пределах лимита заказчика одобряем сразу — его не дёргаем по мелким задачам."""
    ticket = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    customer = conn.execute("SELECT * FROM users WHERE id=?", (customer_id,)).fetchone()
    if not customer or not customer_can_decide(conn, ticket, customer):
        return False
    row = conn.execute("SELECT auto_approve_minutes FROM customer_profiles WHERE user_id=?", (customer_id,)).fetchone()
    if not row or not row["auto_approve_minutes"] or effort_minutes > row["auto_approve_minutes"]:
        return False
    stamp = now()
    conn.execute("UPDATE estimates SET state='approved',customer_comment=?,decided_at=? WHERE id=?",
                 (f"Одобрено автоматически: в пределах лимита {fmt_hours(row['auto_approve_minutes'])}", stamp, estimate_id))
    dispatch_webhooks("estimate.decided", {"event": "estimate.decided", "ticket_id": ticket_id, "action": "approve",
                                           "new_state": "approved", "auto": True, "timestamp": stamp})
    return True


def latest_estimate(conn, ticket_id):
    return conn.execute("""SELECT e.*,u.name AS author_name FROM estimates e JOIN users u ON u.id=e.author_id
        WHERE e.ticket_id=? ORDER BY e.version DESC LIMIT 1""", (ticket_id,)).fetchone()


def notify(conn, user_id, ticket_id, kind, message):
    if user_id is None:
        return
    cursor = conn.execute("INSERT INTO notifications(user_id,ticket_id,kind,text,created_at) VALUES(?,?,?,?,?)",
                          (user_id, ticket_id, kind, message, now()))
    bot_engine.enqueue_notification(conn, user_id, "ticket", ticket_id, kind, message)
    realtime_bus.publish(user_id, {"type": "notification", "target": "ticket", "record_id": ticket_id, "kind": kind, "text": message})
    web_push.enqueue(user_id, {"title": f"Заявка №{ticket_id}", "body": message, "url": f"/#ticket/{ticket_id}", "tag": f"ticket-{ticket_id}"})
    queue_notification_email(conn, user_id, "ticket", ticket_id, kind, message, cursor.lastrowid)


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
        cursor = conn.execute("INSERT INTO chat_notifications(user_id,chat_id,kind,text,created_at) VALUES(?,?,?,?,?)",
                              (user_id, chat_id, kind, message, now()))
        bot_engine.enqueue_notification(conn, user_id, "chat", chat_id, kind, message)
        realtime_bus.publish(user_id, {"type": "notification", "target": "chat", "record_id": chat_id, "kind": kind, "text": message})
        web_push.enqueue(user_id, {"title": "Общий чат", "body": message, "url": f"/#chat/{chat_id}", "tag": f"chat-{chat_id}"})
        queue_notification_email(conn, user_id, "chat", chat_id, kind, message, cursor.lastrowid)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class Register(Credentials):
    name: str = Field(min_length=2, max_length=100)


class StaffCreate(Register):
    staff_role: Literal["employee", "manager"] = "employee"
    team_role: Literal["programmer", "integrator", "devops"] | None = None


class StaffTeamRoleUpdate(BaseModel):
    team_role: Literal["programmer", "integrator", "devops"] | None


class StaffAvailability(BaseModel):
    active: bool
    replacement_id: int | None = None


class AccountInvitation(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    organization_id: int | None = None
    role: Literal["owner", "member", "viewer"] = "member"
    company_name: str | None = Field(default=None, min_length=2, max_length=150)


class AccountEmail(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class AccountTokenPassword(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class ReopenTicket(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    job_title: str = Field(default="", max_length=100)
    bio: str = Field(default="", max_length=1000)


class CustomerProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    company_name: str = Field(default="", max_length=150)
    phone: str = Field(default="", max_length=40)
    # None — не менять. 0 — всегда спрашивать заказчика.
    auto_approve_minutes: int | None = Field(default=None, ge=0, le=100_000)


class AvatarUpload(BaseModel):
    data_url: str = Field(min_length=32, max_length=3_000_000)


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=10000)
    customer_id: int | None = None
    assignee_id: int | None = None
    visibility: Literal["private", "organization"] = "private"
    service_type: Literal["development", "integration", "support", "consultation", "other"] = "other"
    # Сотрудник может сразу приложить оценку: заказчику останется только согласовать её.
    effort_minutes: int | None = Field(default=None, ge=1, le=100_000)
    assessment_minutes: int | None = Field(default=None, ge=1, le=100_000)
    estimate_note: str = Field(default="", max_length=3000)


class TicketDecline(BaseModel):
    comment: str = Field(default="", max_length=3000)


class TicketTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=10000)
    service_type: Literal["development", "integration", "support", "consultation", "other"] = "other"
    effort_minutes: int | None = Field(default=None, ge=1, le=100_000)
    estimate_note: str = Field(default="", max_length=3000)


class BulkEstimateApproval(BaseModel):
    estimate_ids: list[int] = Field(min_length=1, max_length=100)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    request_id: str = Field(min_length=8, max_length=100)
    reply_to_id: int | None = None


class ReadMark(BaseModel):
    last_id: int | None = None


class AcceptanceDecision(BaseModel):
    action: Literal["accept", "return"]
    comment: str = Field(default="", max_length=3000)


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


class ServiceEntryCreate(BaseModel):
    customer_id: int
    ticket_id: int | None = None
    kind: Literal["chat", "call", "meeting", "other"]
    minutes: int = Field(ge=1, le=24 * 60)
    note: str = Field(min_length=3, max_length=2000)
    occurred_at: datetime | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=100)
    summary: str = Field(default="", max_length=3000)
    next_steps: str = Field(default="", max_length=2000)
    share: bool = False


class MeetingSummaryUpdate(BaseModel):
    summary: str = Field(min_length=3, max_length=3000)
    next_steps: str = Field(default="", max_length=2000)
    share: bool = True


class EmailPreferencesUpdate(BaseModel):
    notify: bool
    digest: bool = True
    digest_emails: list[str] = Field(default_factory=list, max_length=3)


class HourRequestCreate(BaseModel):
    minutes: int = Field(ge=1, le=100_000)
    reason: str = Field(min_length=3, max_length=2000)
    request_id: str | None = Field(default=None, min_length=8, max_length=100)


class HourRequestDecision(BaseModel):
    action: Literal["approve", "reject"]


class CompanyOwnerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    organization_id: int | None = Field(default=None, gt=0)
    company_name: str = Field(default="", max_length=150)


class PermanentCredentials(Credentials):
    current_password: str = Field(min_length=8, max_length=128)


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
    service_entry_ids: list[int] | None = None
    notes: str = Field(default="", max_length=500)


class BillingStatusUpdate(BaseModel):
    status: Literal["issued", "paid", "cancelled", "signed"]


class ServiceBudgetUpdate(BaseModel):
    limit_minutes: int | None = Field(default=None, ge=0, le=100000)


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


def billing_enabled() -> bool:
    """Раздел биллинга включается флагом BILLING_ENABLED=1, пока он не готов — выключен."""
    return os.getenv("BILLING_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


AUTH_RATE_LIMITS: dict[str, list[float]] = {}
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    if request.url.path.startswith("/api/billing") and not billing_enabled():
        return Response(status_code=404, content=json.dumps({"detail": "Раздел биллинга отключён"}, ensure_ascii=False), media_type="application/json")
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
    wants_cabinet = any(key in request.query_params for key in ("login", "register", "invite", "reset"))
    if not wants_cabinet:
        try:
            current_user(desk_session)
        except HTTPException:
            return FileResponse(ROOT / "web" / "landing.html", headers=NO_CACHE)
    return FileResponse(ROOT / "web" / "index.html", headers=NO_CACHE)


@app.get("/api/public/settings")
def public_settings():
    return {"hourly_rate_rub": int(os.getenv("DEFAULT_HOURLY_RATE_RUB", "3000")), "billing_enabled": billing_enabled()}


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
        if user["must_change_credentials"] and user["temporary_credentials_expires_at"] <= now():
            raise HTTPException(401, "Временный доступ истёк. Обратитесь к менеджеру")
        response.headers["Cache-Control"] = "no-store"
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
    return public_user(current_user(desk_session, allow_temporary=True))


def staff_profile(conn, user):
    row = conn.execute("SELECT job_title,bio,avatar_updated_at,updated_at FROM staff_profiles WHERE user_id=?", (user["id"],)).fetchone()
    avatar_url = f"/api/staff/{user['id']}/avatar?v={row['avatar_updated_at']}" if row and row["avatar_updated_at"] else None
    return {"id": user["id"], "name": user["name"], "role": user["role"],
            "is_manager": bool(user["is_manager"]), "team_role": conn.execute("SELECT team_role FROM users WHERE id=?", (user["id"],)).fetchone()["team_role"], "job_title": row["job_title"] if row else "",
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
    row = conn.execute("SELECT company_name,phone,auto_approve_minutes FROM customer_profiles WHERE user_id=?", (user["id"],)).fetchone()
    return {"id": user["id"], "name": user["name"], "email": user["email"],
            "role": "customer", "company_name": row["company_name"] if row else "",
            "phone": row["phone"] if row else "", "auto_approve_minutes": row["auto_approve_minutes"] if row else 0}


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
        if data.auto_approve_minutes is not None:
            conn.execute("UPDATE customer_profiles SET auto_approve_minutes=? WHERE user_id=?", (data.auto_approve_minutes, user["id"]))
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
        messages = conn.execute(f"{CHAT_MESSAGE_SELECT} WHERE m.chat_id=? ORDER BY m.id", (chat_id,)).fetchall()
        summaries = conn.execute(f"""{MEETING_SUMMARY_SELECT} WHERE s.customer_id=? AND s.ticket_id IS NULL
            AND s.shared_at IS NOT NULL ORDER BY s.shared_at""", (chat["customer_id"],)).fetchall()
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
        service = []
        if user["role"] != "customer":
            service = conn.execute(f"{SERVICE_ENTRY_SELECT} WHERE s.customer_id=? ORDER BY s.occurred_at DESC, s.id DESC LIMIT 30",
                                   (chat["customer_id"],)).fetchall()
        reads = read_state(conn, "chat", chat_id)
    return {"chat": dict(chat), "messages": [message_dict(row) for row in messages],
            "linked_tickets": visible_links, "attachments": [dict(row) for row in files],
            "service_entries": [dict(row) for row in service],
            "meeting_summaries": [dict(row) for row in summaries], "read_state": reads}


@app.post("/api/service-entries", status_code=201)
def add_service_entry(data: ServiceEntryCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if data.request_id:
            existing = conn.execute(f"{SERVICE_ENTRY_SELECT} WHERE s.author_id=? AND s.request_id=?",
                                    (user["id"], data.request_id)).fetchone()
            if existing:
                return dict(existing)
        customer = conn.execute("SELECT id FROM users WHERE id=? AND role='customer'", (data.customer_id,)).fetchone()
        if not customer:
            raise HTTPException(404, "Клиент не найден")
        org = customer_organization(conn, data.customer_id)
        if data.ticket_id is not None:
            ticket = conn.execute("SELECT customer_id,organization_id,service_limit_minutes FROM tickets WHERE id=?", (data.ticket_id,)).fetchone()
            same_client = ticket and (ticket["customer_id"] == data.customer_id or
                                      (org is not None and ticket["organization_id"] == org["id"]))
            if not same_client:
                raise HTTPException(422, "Заявка не относится к этому клиенту")
            if ticket["service_limit_minutes"] is not None:
                used = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM service_entries WHERE ticket_id=?", (data.ticket_id,)).fetchone()[0]
                if used + data.minutes > ticket["service_limit_minutes"]:
                    raise HTTPException(409, "Превышен лимит сопровождения. Согласуйте увеличение с клиентом")
        note = data.note.strip()
        if len(note) < 3:
            raise HTTPException(422, "Опишите, что обсуждали")
        stamp = now()
        occurred = data.occurred_at.astimezone(timezone.utc).isoformat() if data.occurred_at else stamp
        if occurred > stamp:
            raise HTTPException(422, "Нельзя внести время за будущую дату")
        summary, next_steps = data.summary.strip(), data.next_steps.strip()
        if data.share and len(summary) < 3:
            raise HTTPException(422, "Напишите, о чём договорились, чтобы отправить итоги клиенту")
        cursor = conn.execute("""INSERT INTO service_entries(customer_id,organization_id,ticket_id,author_id,kind,minutes,
            note,occurred_at,created_at,request_id,client_summary,client_next_steps) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.customer_id, org["id"] if org else None, data.ticket_id, user["id"], data.kind, data.minutes,
             note, occurred, stamp, data.request_id, summary or None, next_steps or None))
        if data.share:
            share_meeting_summary(conn, cursor.lastrowid)
        return dict(conn.execute(f"{SERVICE_ENTRY_SELECT} WHERE s.id=?", (cursor.lastrowid,)).fetchone())


def share_meeting_summary(conn, entry_id):
    """Публикует итоги встречи клиенту: в заявке, если запись к ней привязана, иначе в общем чате."""
    entry = conn.execute("SELECT * FROM service_entries WHERE id=?", (entry_id,)).fetchone()
    stamp = now()
    first_time = entry["shared_at"] is None
    conn.execute("UPDATE service_entries SET shared_at=COALESCE(shared_at,?) WHERE id=?", (stamp, entry_id))
    if not first_time:
        return
    when = format_ru_date(entry["occurred_at"]).removesuffix(" г.")
    label = {"call": "созвона", "meeting": "встречи"}.get(entry["kind"], "обсуждения")
    if entry["ticket_id"] is not None:
        ticket = conn.execute("SELECT * FROM tickets WHERE id=?", (entry["ticket_id"],)).fetchone()
        for recipient in customer_recipients(conn, ticket):
            notify(conn, recipient, ticket["id"], "meeting_summary", f"Итоги {label} {when} по заявке №{ticket['id']}")
        realtime_bus.broadcast(customer_recipients(conn, ticket), {"type": "meeting_summary", "ticket_id": ticket["id"]})
        return
    chat = conn.execute("SELECT id FROM chats WHERE customer_id=?", (entry["customer_id"],)).fetchone()
    chat_id = chat["id"] if chat else conn.execute("INSERT INTO chats(customer_id,created_at,updated_at) VALUES(?,?,?)",
                                                   (entry["customer_id"], stamp, stamp)).lastrowid
    conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (stamp, chat_id))
    notify_chat(conn, entry["customer_id"], chat_id, "meeting_summary", f"Итоги {label} {when}")
    realtime_bus.publish(entry["customer_id"], {"type": "meeting_summary", "chat_id": chat_id})


@app.patch("/api/service-entries/{entry_id}/summary")
def update_meeting_summary(entry_id: int, data: MeetingSummaryUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    summary = data.summary.strip()
    if len(summary) < 3:
        raise HTTPException(422, "Напишите, о чём договорились")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT author_id FROM service_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Запись не найдена")
        if row["author_id"] != user["id"] and user["role"] != "admin" and not user["is_manager"]:
            raise HTTPException(403, "Итоги добавляет автор записи или руководитель")
        conn.execute("UPDATE service_entries SET client_summary=?,client_next_steps=? WHERE id=?",
                     (summary, data.next_steps.strip() or None, entry_id))
        if data.share:
            share_meeting_summary(conn, entry_id)
        return dict(conn.execute(f"{SERVICE_ENTRY_SELECT} WHERE s.id=?", (entry_id,)).fetchone())


@app.get("/api/service-entries")
def list_service_entries(client_type: Literal["org", "user"] | None = None, client_id: int | None = None,
                         unbilled: bool = False, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        conds, params = [], []
        if client_type and client_id is not None:
            cond, cond_params = client_condition(client_type, client_id, "s.")
            conds.append(cond)
            params.extend(cond_params)
        if unbilled:
            conds.append("s.act_invoice_id IS NULL")
        where = f" WHERE {' AND '.join(conds)}" if conds else ""
        rows = conn.execute(f"{SERVICE_ENTRY_SELECT}{where} ORDER BY s.occurred_at DESC, s.id DESC LIMIT 200",
                            params).fetchall()
        return [dict(row) for row in rows]


@app.delete("/api/service-entries/{entry_id}")
def delete_service_entry(entry_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        row = conn.execute("SELECT author_id,act_invoice_id FROM service_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Запись не найдена")
        if row["author_id"] != user["id"] and user["role"] != "admin" and not user["is_manager"]:
            raise HTTPException(403, "Удалить запись может её автор или руководитель")
        if row["act_invoice_id"] is not None:
            raise HTTPException(409, "Запись уже включена в акт")
        conn.execute("DELETE FROM service_entries WHERE id=?", (entry_id,))
        return {"ok": True}


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
    existing = conn.execute(f"{CHAT_MESSAGE_SELECT} WHERE m.chat_id=? AND m.author_id=? AND m.request_id=?",
                            (chat_id, user["id"], data.request_id)).fetchone()
    if existing:
        return message_dict(existing)
    reply_to = checked_reply(conn, "chat_messages", "chat_id", chat_id, data.reply_to_id)
    stamp = now()
    cursor = conn.execute("INSERT INTO chat_messages(chat_id,author_id,body,request_id,created_at,reply_to_id) VALUES(?,?,?,?,?,?)",
                          (chat_id, user["id"], body, data.request_id, stamp, reply_to))
    conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (stamp, chat_id))
    mark_read(conn, "chat", chat_id, user["id"], cursor.lastrowid)
    if user["role"] == "customer":
        if chat["assignee_id"]:
            notify_chat(conn, chat["assignee_id"], chat_id, "message", f"Новое сообщение в общем чате с {user['name']}")
        else:
            for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
                notify_chat(conn, dispatcher["id"], chat_id, "message", f"Новое сообщение в общем чате с {user['name']}")
    else:
        notify_chat(conn, chat["customer_id"], chat_id, "message", "Новое сообщение в общем чате")
    message_payload = message_dict(conn.execute(f"{CHAT_MESSAGE_SELECT} WHERE m.id=?", (cursor.lastrowid,)).fetchone())
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
def staff(desk_session: str | None = Cookie(default=None), include_inactive: bool = False):
    user = current_user(desk_session)
    require_staff(user)
    if include_inactive:
        require_admin(user)
    with db() as conn:
        if user["role"] == "admin" or user["is_manager"]:
            rows = conn.execute("SELECT id,name,email,role,is_manager,active FROM users WHERE role IN ('employee','admin') AND (active=1 OR ?) ORDER BY name", (include_inactive,)).fetchall()
        else:
            rows = conn.execute("SELECT id,name,email,role,is_manager FROM users WHERE id=?", (user["id"],)).fetchall()
        return [{**dict(row), **staff_profile(conn, row)} for row in rows]


@app.post("/api/staff", status_code=201)
def add_staff(data: StaffCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        created = create_user(conn, data.name, data.email, data.password, "employee")
        conn.execute("UPDATE users SET team_role=? WHERE id=?", (data.team_role, created["id"]))
        if data.staff_role == "manager":
            conn.execute("UPDATE users SET is_manager=1 WHERE id=?", (created["id"],))
        created = conn.execute("SELECT * FROM users WHERE id=?", (created["id"],)).fetchone()
    return public_user(created)


@app.patch("/api/staff/{staff_id}/team-role")
def update_staff_team_role(staff_id: int, data: StaffTeamRoleUpdate, desk_session: str | None = Cookie(default=None)):
    require_admin(current_user(desk_session))
    with db() as conn:
        person = conn.execute("SELECT * FROM users WHERE id=? AND role IN ('employee','admin')", (staff_id,)).fetchone()
        if not person:
            raise HTTPException(404, "Сотрудник не найден")
        conn.execute("UPDATE users SET team_role=? WHERE id=?", (data.team_role, staff_id))
        person = conn.execute("SELECT * FROM users WHERE id=?", (staff_id,)).fetchone()
        return {**public_user(person), **staff_profile(conn, person)}


@app.patch("/api/staff/{staff_id}/availability")
def change_staff_availability(staff_id: int, data: StaffAvailability, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_admin(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute("SELECT * FROM users WHERE id=? AND role IN ('employee','admin')", (staff_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Сотрудник не найден")
        if not data.active and staff_id == user["id"]:
            raise HTTPException(409, "Нельзя отключить собственный доступ")
        if data.replacement_id is not None and (data.replacement_id == staff_id or not conn.execute(
            "SELECT 1 FROM users WHERE id=? AND role IN ('employee','admin') AND active=1", (data.replacement_id,)).fetchone()):
            raise HTTPException(422, "Выберите другого активного сотрудника")
        moved = 0
        moved_chats = 0
        if not data.active:
            tickets = conn.execute("SELECT id FROM tickets WHERE assignee_id=? AND status!='closed'", (staff_id,)).fetchall()
            for ticket in tickets:
                conn.execute("UPDATE tickets SET assignee_id=?,updated_at=? WHERE id=?", (data.replacement_id, now(), ticket["id"]))
                conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                             (ticket["id"], user["id"], "assignment", str(staff_id), str(data.replacement_id or ""), now()))
                for recipient in ({data.replacement_id} if data.replacement_id else dispatcher_ids(conn)) - {staff_id}:
                    notify(conn, recipient, ticket["id"], "assignment", f"Заявка №{ticket['id']} передана после отключения сотрудника")
            moved = len(tickets)
            chats = conn.execute("SELECT id FROM chats WHERE assignee_id=?", (staff_id,)).fetchall()
            conn.execute("UPDATE chats SET assignee_id=?,updated_at=? WHERE assignee_id=?", (data.replacement_id, now(), staff_id))
            for chat in chats:
                for recipient in ({data.replacement_id} if data.replacement_id else dispatcher_ids(conn)) - {staff_id}:
                    notify_chat(conn, recipient, chat["id"], "assignment", "Общий чат передан после отключения сотрудника")
            moved_chats = len(chats)
            conn.execute("DELETE FROM sessions WHERE user_id=?", (staff_id,))
        conn.execute("UPDATE users SET active=? WHERE id=?", (data.active, staff_id))
        return {"id": staff_id, "active": data.active, "transferred_tickets": moved, "transferred_chats": moved_chats}


@app.get("/api/customers")
def customers(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        select = """SELECT id,name,email,
            (NOT EXISTS (SELECT 1 FROM organization_members m WHERE m.user_id=users.id)
             AND (must_change_credentials=0 OR temporary_credentials_expires_at>?)
             AND NOT EXISTS (SELECT 1 FROM account_tokens a WHERE a.user_id=users.id AND a.kind='invite')) AS can_own_company
             FROM users WHERE role='customer' AND active=1"""
        if user["role"] == "admin" or user["is_manager"]:
            rows = conn.execute(select + " ORDER BY name,email", (now(),)).fetchall()
        else:
            rows = conn.execute(select + """ AND (id IN (SELECT customer_id FROM tickets WHERE assignee_id=?)
                  OR id IN (SELECT customer_id FROM chats WHERE assignee_id=?)) ORDER BY name,email""",
                (now(), user["id"], user["id"])).fetchall()
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
            item["has_available_owner"] = bool(available_owners(conn, row["organization_id"])) if row["organization_id"] else None
            if user["role"] == "customer":
                item["next_step"] = customer_next_step(item, estimate, conn, user)
                item["can_decide"] = customer_can_decide(conn, row, user)
                item["can_write"] = customer_can_write_ticket(conn, row, user)
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
            (SELECT 1 FROM hour_requests WHERE ticket_id=t.id AND state='pending' LIMIT 1) AS pending_hours,
            (SELECT MAX(count) FROM customer_reminders WHERE ticket_id=t.id
                AND kind=CASE t.status WHEN 'waiting' THEN 'answer' WHEN 'done' THEN 'acceptance' END) AS reminders_sent
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
        if priority >= 2 and (row["reminders_sent"] or 0) >= reminder_settings()["max"]:
            action = ("Заказчик не принимает работу — уточните или закройте" if row["status"] == "done"
                      else "Заказчик молчит — предложите закрыть заявку")
            priority = 2
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
        if data.customer_id is not None or data.assignee_id is not None or data.effort_minutes is not None:
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
        if data.effort_minutes is not None and assignee_id is None:
            raise HTTPException(422, "Чтобы сразу отправить оценку, назначьте ответственного")
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
    auto_approved = False
    if data.effort_minutes is not None:
        estimate = conn.execute("""INSERT INTO estimates(ticket_id,author_id,version,amount_minor,
            assessment_minutes,note,state,created_at,effort_minutes) VALUES(?,?,?,?,?,?,?,?,?)""",
            (cursor.lastrowid, user["id"], 1, 0, data.assessment_minutes or 1,
             data.estimate_note.strip(), "pending", stamp, data.effort_minutes))
        auto_approved = auto_approve_estimate(conn, cursor.lastrowid, customer_id, estimate.lastrowid, data.effort_minutes)
    if user["role"] == "customer":
        for admin in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
            notify(conn, admin["id"], cursor.lastrowid, "new_ticket", f"Новая заявка №{cursor.lastrowid}: {data.title.strip()}")
    else:
        text = f"Для вас создана заявка №{cursor.lastrowid}: {data.title.strip()}"
        if auto_approved:
            text += f". Оценка {fmt_hours(data.effort_minutes)} одобрена автоматически по вашему лимиту"
        elif data.effort_minutes is not None:
            text += f". Согласуйте оценку: {fmt_hours(data.effort_minutes)}"
        notify(conn, customer_id, cursor.lastrowid, "estimate" if data.effort_minutes is not None else "new_ticket", text)
        if assignee_id and assignee_id != user["id"]:
            notify(conn, assignee_id, cursor.lastrowid, "assignment", f"Вам назначена заявка №{cursor.lastrowid}"
                   + (" — оценка уже одобрена, можно начинать" if auto_approved else ""))
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


@app.patch("/api/tickets/{ticket_id}/service-budget")
def update_service_budget(ticket_id: int, data: ServiceBudgetUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if user["role"] != "customer" or not customer_can_decide(conn, ticket, user):
            raise HTTPException(403, "Лимит сопровождения устанавливает заказчик, согласующий работу")
        if ticket["status"] == "closed":
            raise HTTPException(409, "Заявка закрыта")
        used = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM service_entries WHERE ticket_id=?", (ticket_id,)).fetchone()[0]
        if data.limit_minutes is not None and data.limit_minutes < used:
            raise HTTPException(409, "Лимит не может быть меньше уже учтённого сопровождения")
        conn.execute("UPDATE tickets SET service_limit_minutes=? WHERE id=?", (data.limit_minutes, ticket_id))
        conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,new_value,created_at) VALUES(?,?,?,?,?)", (ticket_id,user["id"],"service_budget",str(data.limit_minutes) if data.limit_minutes is not None else "unlimited",now()))
        if ticket["assignee_id"]:
            notify(conn, ticket["assignee_id"], ticket_id, "budget", "Заказчик изменил лимит сопровождения")
        return {"limit_minutes": data.limit_minutes}


@app.post("/api/tickets/{ticket_id}/owner-help")
def request_owner_help(ticket_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if ticket["visibility"] != "organization" or available_owners(conn, ticket["organization_id"]):
            raise HTTPException(409, "Для заявки доступно согласование")
        recent = conn.execute("SELECT 1 FROM ticket_events WHERE ticket_id=? AND kind='owner_help' AND created_at>?", (ticket_id,(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat())).fetchone()
        if not recent:
            for dispatcher in conn.execute("SELECT id FROM users WHERE active=1 AND (role='admin' OR is_manager=1)"):
                notify(conn,dispatcher['id'],ticket_id,'owner_help',f"Нужно восстановить владельца компании для заявки №{ticket_id}")
            conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,created_at) VALUES(?,?,?,?)", (ticket_id,user['id'],'owner_help',now()))
        return {"message": "Запрос передан менеджеру. Он назначит владельца или восстановит его доступ"}


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        messages = conn.execute(f"{TICKET_MESSAGE_SELECT} WHERE m.ticket_id=? ORDER BY m.id", (ticket_id,)).fetchall()
        summaries = conn.execute(f"{MEETING_SUMMARY_SELECT} WHERE s.ticket_id=? AND s.shared_at IS NOT NULL ORDER BY s.shared_at",
                                 (ticket_id,)).fetchall()
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
        item["estimate_state"] = estimates[0]["state"] if estimates else None
        item["effort_minutes"] = estimates[0]["effort_minutes"] if estimates else None
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
        item["has_available_owner"] = bool(available_owners(conn, ticket["organization_id"])) if ticket["organization_id"] else None

        if user["role"] == "customer":
            item["pending_hour_request"] = bool(conn.execute("SELECT 1 FROM hour_requests WHERE ticket_id=? AND state='pending'", (ticket_id,)).fetchone())
            item["next_step"] = customer_next_step(item, estimates[0] if estimates else None, conn, user)
        time_rows = conn.execute("""SELECT w.*,u.name AS author_name FROM time_entries w JOIN users u ON u.id=w.author_id
            WHERE w.ticket_id=? ORDER BY w.id DESC""", (ticket_id,)).fetchall()
        hour_rows = conn.execute("""SELECT h.*,u.name AS author_name FROM hour_requests h JOIN users u ON u.id=h.author_id
            WHERE h.ticket_id=? ORDER BY h.id DESC""", (ticket_id,)).fetchall()
        file_rows = conn.execute("SELECT id,filename,size,content_type,author_id,created_at FROM attachments WHERE ticket_id=? ORDER BY id DESC", (ticket_id,)).fetchall()
        service_rows = []
        item["service_minutes"] = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM service_entries WHERE ticket_id=?", (ticket_id,)).fetchone()[0]
        item["service_cost_rub"] = round(item["service_minutes"] / 60.0 * rate_rub)
        item["total_cost_rub"] = item["cost_rub"] + item["service_cost_rub"]
        if user["role"] != "customer":
            service_rows = conn.execute(f"{SERVICE_ENTRY_SELECT} WHERE s.ticket_id=? ORDER BY s.occurred_at DESC, s.id DESC",
                                        (ticket_id,)).fetchall()
            item["service_minutes"] = sum(row["minutes"] for row in service_rows)
            item["service_cost_rub"] = round(item["service_minutes"] / 60.0 * rate_rub)
            item["total_cost_rub"] = item["cost_rub"] + item["service_cost_rub"]
        latest_reopen = max((e["id"] for e in events if e["kind"] == "reopen"), default=0)
        item["declined"] = any(e["kind"] == "decline" and e["id"] > latest_reopen for e in events)
        if user["role"] == "customer":
            item["can_decide"] = customer_can_decide(conn, ticket, user)
            item["can_write"] = customer_can_write_ticket(conn, ticket, user)
            item["can_decline"] = customer_can_decline(conn, ticket, user)
        reads = read_state(conn, "ticket", ticket_id)
    return {"ticket": item, "messages": [message_dict(x) for x in messages],
            "meeting_summaries": [dict(x) for x in summaries], "read_state": reads,
            "service_entries": [dict(x) for x in service_rows],
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
        if auto_approve_estimate(conn, ticket_id, ticket["customer_id"], cursor.lastrowid, data.effort_minutes):
            text = f"Оценка заявки №{ticket_id} ({fmt_hours(data.effort_minutes)}) одобрена автоматически по вашему лимиту"
        else:
            text = f"Оценка заявки №{ticket_id} готова к рассмотрению"
        for recipient in customer_recipients(conn, ticket):
            notify(conn, recipient, ticket_id, "estimate", text)
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
        raise HTTPException(403, "Личную заявку согласует автор, общую — владелец компании")
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
    existing = conn.execute(f"{TICKET_MESSAGE_SELECT} WHERE m.ticket_id=? AND m.author_id=? AND m.request_id=?",
                            (ticket_id, user["id"], data.request_id)).fetchone()
    if existing:
        return message_dict(existing)
    if ticket["status"] == "closed":
        raise HTTPException(409, "Заявка закрыта")
    reply_to = checked_reply(conn, "messages", "ticket_id", ticket_id, data.reply_to_id)
    stamp = now()
    cursor = conn.execute("INSERT INTO messages(ticket_id,author_id,body,created_at,request_id,reply_to_id) VALUES(?,?,?,?,?,?)",
                          (ticket_id, user["id"], body, stamp, data.request_id, reply_to))
    conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, ticket_id))
    mark_read(conn, "ticket", ticket_id, user["id"], cursor.lastrowid)
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
    message_payload = message_dict(conn.execute(f"{TICKET_MESSAGE_SELECT} WHERE m.id=?", (cursor.lastrowid,)).fetchone())
    ticket_participants = set(customer_recipients(conn, ticket))
    if ticket["assignee_id"]:
        ticket_participants.add(ticket["assignee_id"])
    for dispatcher in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1"):
        ticket_participants.add(dispatcher["id"])
    realtime_bus.broadcast(ticket_participants, {
        "type": "ticket_message", "ticket_id": ticket_id, "message": message_payload
    })
    return message_payload


def dispatcher_ids(conn):
    return {row["id"] for row in conn.execute("SELECT id FROM users WHERE (role='admin' OR is_manager=1) AND active=1")}


def mark_record_read(conn, user, kind, record_id, last_id, participants):
    """Отмечает переписку прочитанной и гасит уведомления по ней; другой стороне уходит новая отметка."""
    table, key = ("messages", "ticket_id") if kind == "ticket" else ("chat_messages", "chat_id")
    top = conn.execute(f"SELECT MAX(id) FROM {table} WHERE {key}=?", (record_id,)).fetchone()[0] or 0
    last = min(last_id, top) if last_id else top
    before = read_state(conn, kind, record_id)
    if last:
        mark_read(conn, kind, record_id, user["id"], last)
    notifications = "notifications" if kind == "ticket" else "chat_notifications"
    conn.execute(f"UPDATE {notifications} SET read_at=? WHERE user_id=? AND {key}=? AND read_at IS NULL",
                 (now(), user["id"], record_id))
    after = read_state(conn, kind, record_id)
    if after != before:
        realtime_bus.broadcast(participants, {"type": "read", "target": kind, "record_id": record_id, **after})
    return after


@app.post("/api/tickets/{ticket_id}/read")
def read_ticket(ticket_id: int, data: ReadMark, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        ticket = ticket_for(conn, ticket_id, user)
        participants = customer_recipients(conn, ticket) | dispatcher_ids(conn) | ({ticket["assignee_id"]} - {None})
        return mark_record_read(conn, user, "ticket", ticket_id, data.last_id, participants)


@app.post("/api/chats/{chat_id}/read")
def read_chat(chat_id: int, data: ReadMark, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        chat = chat_for(conn, chat_id, user)
        participants = {chat["customer_id"]} | dispatcher_ids(conn) | ({chat["assignee_id"]} - {None})
        return mark_record_read(conn, user, "chat", chat_id, data.last_id, participants)


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
        if ticket["status"] == "closed" and data.status != "closed":
            raise HTTPException(409, "Закрытую заявку возвращает в работу менеджер с указанием причины")
        if ticket["status"] == data.status:
            return ticket_dict(ticket)
        dispatcher = user["role"] == "admin" or bool(user["is_manager"])
        if user["role"] != "admin" and ticket["assignee_id"] != user["id"] and not (dispatcher and data.status == "closed"):
            raise HTTPException(403, "Статус меняет ответственный")
        # Закрытие — это приёмка работы заказчиком. Без неё закрыть может только руководитель.
        if data.status == "closed" and ticket["status"] != "closed" and not dispatcher:
            raise HTTPException(403, "Отправьте работу на проверку: заявку закроет заказчик после приёмки")
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
        if ticket["status"] != data.status:
            if data.status == "done":
                for recipient in customer_decision_recipients(conn, ticket):
                    notify(conn, recipient, ticket_id, "review", f"Работа по заявке №{ticket_id} готова — проверьте и примите результат")
            elif ticket["customer_id"] != user["id"]:
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


def accept_work_service(conn, user, ticket_id: int, data: AcceptanceDecision):
    """Заказчик принимает результат (заявка закрывается) или возвращает его на доработку с комментарием."""
    if user["role"] != "customer":
        raise HTTPException(403, "Работу принимает заказчик")
    ticket = ticket_for(conn, ticket_id, user)
    if not customer_can_decide(conn, ticket, user):
        raise HTTPException(403, "Личную работу принимает автор заявки, общую — владелец компании")
    if ticket["status"] != "done":
        raise HTTPException(409, "Работа уже принята или ещё не отправлена на проверку")
    comment = data.comment.strip()
    if data.action == "return" and len(comment) < 3:
        raise HTTPException(422, "Напишите, что нужно доработать")
    stamp = now()
    new_status = "closed" if data.action == "accept" else "working"
    conn.execute("UPDATE tickets SET status=?,updated_at=?,accepted_at=?,accepted_by_id=? WHERE id=?",
                 (new_status, stamp, stamp if data.action == "accept" else None,
                  user["id"] if data.action == "accept" else None, ticket_id))
    conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                 (ticket_id, user["id"], "acceptance", "done", "accepted" if data.action == "accept" else "returned", stamp))
    if comment:
        # Комментарий остаётся в переписке; отдельное уведомление о сообщении не нужно — его заменяет уведомление о приёмке.
        prefix = "Работа принята" if data.action == "accept" else "Возврат на доработку"
        cursor = conn.execute("INSERT INTO messages(ticket_id,author_id,body,created_at,request_id) VALUES(?,?,?,?,?)",
                              (ticket_id, user["id"], f"{prefix}: {comment}", stamp, f"acceptance-{secrets.token_hex(8)}"))
        mark_read(conn, "ticket", ticket_id, user["id"], cursor.lastrowid)
    if data.action == "accept":
        text = f"Заказчик принял работу по заявке №{ticket_id}"
    else:
        text = f"Заказчик вернул заявку №{ticket_id} на доработку" + (f": {comment[:200]}" if comment else "")
    recipients = {ticket["assignee_id"]} - {None} or dispatcher_ids(conn)
    for recipient in recipients:
        notify(conn, recipient, ticket_id, "acceptance", text)
    dispatch_webhooks("ticket.status_changed", {"event": "ticket.status_changed", "ticket_id": ticket_id,
                                                "old_status": "done", "new_status": new_status, "timestamp": stamp})
    return ticket_dict(ticket_for(conn, ticket_id, user))


@app.post("/api/tickets/{ticket_id}/acceptance")
def accept_work(ticket_id: int, data: AcceptanceDecision, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return accept_work_service(conn, user, ticket_id, data)


@app.post("/api/tickets/{ticket_id}/reopen")
def reopen_ticket(ticket_id: int, data: ReopenTicket, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    if len(data.reason.strip()) < 3:
        raise HTTPException(422, "Укажите причину возврата в работу")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ticket = ticket_for(conn, ticket_id, user)
        if ticket["status"] != "closed":
            raise HTTPException(409, "Заявка уже открыта")
        if ticket["act_invoice_id"]:
            raise HTTPException(409, "Работа включена в акт. Сначала согласуйте корректировку акта")
        estimate = latest_estimate(conn, ticket_id)
        status = "working" if estimate and estimate["state"] == "approved" else "new"
        conn.execute("UPDATE tickets SET status=?,accepted_at=NULL,accepted_by_id=NULL,updated_at=? WHERE id=?", (status, now(), ticket_id))
        if ticket["assignee_id"] and not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (ticket["assignee_id"],)).fetchone():
            conn.execute("UPDATE tickets SET assignee_id=NULL WHERE id=?", (ticket_id,))
        conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                     (ticket_id, user["id"], "reopen", "closed", data.reason.strip(), now()))
        for recipient in customer_recipients(conn, ticket) | ({ticket["assignee_id"]} - {None}):
            notify(conn, recipient, ticket_id, "status", f"Заявка №{ticket_id} возвращена в работу: {data.reason.strip()}")
        return ticket_dict(ticket_for(conn, ticket_id, user))


def decline_ticket_service(conn, user, ticket_id: int, data: TicketDecline):
    """Заказчик отказывается от заявки, созданной за него командой: заявка закрывается без работы."""
    if user["role"] != "customer":
        raise HTTPException(403, "Отказаться от заявки может заказчик")
    ticket = ticket_for(conn, ticket_id, user)
    if not customer_can_decline(conn, ticket, user):
        raise HTTPException(409, "От этой заявки уже нельзя отказаться")
    comment = data.comment.strip()
    stamp = now()
    conn.execute("UPDATE estimates SET state='rejected',customer_comment=?,decided_at=? WHERE ticket_id=? AND state='pending'",
                 (comment or None, stamp, ticket_id))
    conn.execute("UPDATE tickets SET status='closed',updated_at=? WHERE id=?", (stamp, ticket_id))
    conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                 (ticket_id, user["id"], "decline", ticket["status"], "closed", stamp))
    if comment:
        cursor = conn.execute("INSERT INTO messages(ticket_id,author_id,body,created_at,request_id) VALUES(?,?,?,?,?)",
                              (ticket_id, user["id"], f"Заявка не нужна: {comment}", stamp, f"decline-{secrets.token_hex(8)}"))
        mark_read(conn, "ticket", ticket_id, user["id"], cursor.lastrowid)
    text = f"Заказчик отказался от заявки №{ticket_id}" + (f": {comment[:200]}" if comment else "")
    for recipient in {ticket["assignee_id"], ticket["created_by_id"]} - {None, user["id"]} or dispatcher_ids(conn):
        notify(conn, recipient, ticket_id, "decline", text)
    dispatch_webhooks("ticket.status_changed", {"event": "ticket.status_changed", "ticket_id": ticket_id,
                                                "old_status": ticket["status"], "new_status": "closed", "timestamp": stamp})
    return ticket_dict(ticket_for(conn, ticket_id, user))


@app.post("/api/tickets/{ticket_id}/decline")
def decline_ticket(ticket_id: int, data: TicketDecline, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return decline_ticket_service(conn, user, ticket_id, data)


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
        for recipient in customer_decision_recipients(conn, ticket):
            notify(conn, recipient, ticket_id, "extra_hours", f"Согласуйте дополнительные часы по заявке №{ticket_id}")
        return dict(conn.execute("SELECT * FROM hour_requests WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.post("/api/tickets/{ticket_id}/hour-requests/{request_id}/decision")
def decide_hours(ticket_id: int, request_id: int, data: HourRequestDecision,
                 desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return decide_hours_service(conn, user, ticket_id, request_id, data)


def decide_hours_service(conn, user, ticket_id: int, request_id: int, data: HourRequestDecision):
    if user["role"] != "customer":
        raise HTTPException(403, "Решение принимает заказчик")
    ticket = ticket_for(conn, ticket_id, user)
    if not customer_can_decide(conn, ticket, user):
        raise HTTPException(403, "Личную заявку согласует автор, общую — владелец компании")
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


@app.post("/api/company-owners", status_code=201)
def create_company_owner(data: CompanyOwnerCreate, response: Response,
                         desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    name = data.name.strip()
    company_name = data.company_name.strip()
    if len(name) < 2 or (data.organization_id is None and len(company_name) < 2):
        raise HTTPException(422, "Укажите имя владельца и название компании")
    login = f"owner-{secrets.token_hex(10)}@access.local"
    password = secrets.token_urlsafe(18)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if data.organization_id is not None:
            organization = conn.execute("SELECT * FROM organizations WHERE id=?", (data.organization_id,)).fetchone()
            if not organization:
                raise HTTPException(404, "Компания не найдена")
            organization_id = organization["id"]
            company_name = organization["name"]
        else:
            organization_id = conn.execute("INSERT INTO organizations(name,created_at) VALUES(?,?)",
                                           (company_name, now())).lastrowid
        owner = create_user(conn, name, login, password, "customer")
        conn.execute("UPDATE users SET must_change_credentials=1,temporary_credentials_expires_at=? WHERE id=?",
                     (expires, owner["id"]))
        conn.execute("INSERT INTO organization_members(organization_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                     (organization_id, owner["id"], "owner", now()))
    response.headers["Cache-Control"] = "no-store"
    return {"id": owner["id"], "organization_id": organization_id, "company_name": company_name,
            "login": login, "temporary_password": password, "expires_at": expires}


@app.post("/api/account/credentials")
def replace_temporary_credentials(data: PermanentCredentials, response: Response,
                                  desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session, allow_temporary=True)
    email = clean_email(data.email)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if not user["must_change_credentials"]:
            raise HTTPException(409, "Временные данные уже заменены")
        if user["temporary_credentials_expires_at"] <= now():
            raise HTTPException(401, "Временный доступ истёк")
        if not verify_password(data.current_password, user["password_hash"]):
            raise HTTPException(403, "Неверный временный пароль")
        if email == user["email"] or email.endswith("@access.local"):
            raise HTTPException(422, "Укажите свой постоянный email")
        if verify_password(data.password, user["password_hash"]):
            raise HTTPException(422, "Новый пароль должен отличаться от временного")
        try:
            conn.execute("UPDATE users SET email=?,password_hash=?,must_change_credentials=0,temporary_credentials_expires_at=NULL WHERE id=?",
                         (email, password_hash(data.password), user["id"]))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Email уже используется")
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        user = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        response.headers["Cache-Control"] = "no-store"
        return issue_session(conn, user, response)


def issue_account_link(conn, user, kind):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=1 if kind == "reset" else 72)).isoformat()
    conn.execute("UPDATE email_outbox SET state='superseded' WHERE user_id=? AND kind=? AND state='pending'", (user["id"], kind))
    conn.execute("DELETE FROM account_tokens WHERE user_id=? AND kind=?", (user["id"], kind))
    conn.execute("INSERT INTO account_tokens VALUES(?,?,?,?,?)", (token_hash(token), user["id"], kind, expires, now()))
    link = f"{public_base()}/?{kind}={token}"
    subject = "Восстановление доступа" if kind == "reset" else "Приглашение в кабинет заказчика"
    body = f"{subject}. Откройте ссылку и задайте пароль: {link}\nСсылка действует до {expires}. Если вы не запрашивали доступ, проигнорируйте письмо."
    queue_email(conn, user["id"], user["email"], kind, subject, body,
                f'<p>{html.escape(subject)}</p><p><a href="{html.escape(link, quote=True)}">Открыть кабинет и задать пароль</a></p><p>Ссылка действует до {html.escape(expires)}.</p><p>Если вы не запрашивали доступ, проигнорируйте письмо.</p>')
    return {"url": link, "expires_at": expires}


def require_company_manager(conn, user, organization_id):
    if user["role"] == "admin" or user["is_manager"]:
        return
    member = conn.execute("SELECT role FROM organization_members WHERE organization_id=? AND user_id=?", (organization_id, user["id"])).fetchone()
    if user["role"] != "customer" or not member or member["role"] != "owner":
        raise HTTPException(403, "Участниками управляет владелец компании или менеджер")


@app.get("/api/customer-invitations")
def customer_invitations(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        manager = user["role"] == "admin" or bool(user["is_manager"])
        org = customer_organization(conn, user["id"]) if user["role"] == "customer" else None
        if not manager:
            if not org:
                raise HTTPException(403, "Доступно владельцу компании")
            require_company_manager(conn, user, org["id"])
        rows = conn.execute("""SELECT u.id AS customer_id,u.name,u.email,u.must_change_credentials,
            m.organization_id,m.role,a.expires_at,a.created_at,
            (SELECT state FROM email_outbox e WHERE e.user_id=u.id AND e.kind='invite' ORDER BY e.id DESC LIMIT 1) AS delivery_state
            FROM users u LEFT JOIN organization_members m ON m.user_id=u.id
            LEFT JOIN account_tokens a ON a.user_id=u.id AND a.kind='invite'
            WHERE u.role='customer' AND (? OR m.organization_id=?)
            AND (a.token_hash IS NOT NULL OR EXISTS(SELECT 1 FROM email_outbox e WHERE e.user_id=u.id AND e.kind='invite'))
            ORDER BY u.name""", (manager, org["id"] if org else None)).fetchall()
        return [{**dict(row), "status": "activated" if not row["must_change_credentials"] else
                 "expired" if not row["expires_at"] or row["expires_at"] <= now() else "pending"} for row in rows]


@app.post("/api/customer-invitations", status_code=201)
def invite_customer(data: AccountInvitation, response: Response, desk_session: str | None = Cookie(default=None)):
    manager = current_user(desk_session)
    email = clean_email(data.email)
    if data.company_name is not None and len(data.company_name.strip()) < 2:
        raise HTTPException(422, "Укажите название компании из двух или более символов")
    if len(data.name.strip()) < 2 or email.endswith("@access.local"):
        raise HTTPException(422, "Укажите имя и постоянный email заказчика")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if data.organization_id:
            require_company_manager(conn, manager, data.organization_id)
        else:
            require_dispatcher(manager)
        if data.company_name and data.organization_id:
            raise HTTPException(422, "Выберите существующую компанию или название новой")
        if data.organization_id and not conn.execute("SELECT 1 FROM organizations WHERE id=?", (data.organization_id,)).fetchone():
            raise HTTPException(404, "Компания не найдена")
        customer = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if customer and (customer["role"] != "customer" or not customer["active"]):
            raise HTTPException(409, "Этот email нельзя использовать для приглашения заказчика")
        registered = bool(customer and not customer["must_change_credentials"])
        if not customer:
            customer = create_user(conn, data.name, email, secrets.token_urlsafe(32), "customer")
            conn.execute("UPDATE users SET must_change_credentials=1,temporary_credentials_expires_at=? WHERE id=?",
                         ((datetime.now(timezone.utc)+timedelta(hours=72)).isoformat(), customer["id"]))
        if data.company_name:
            if customer_organization(conn, customer["id"]):
                raise HTTPException(409, "Заказчик уже состоит в компании")
            created_org = conn.execute("INSERT INTO organizations(name,created_at) VALUES(?,?)", (data.company_name.strip(), now()))
            data.organization_id = created_org.lastrowid
            data.role = "owner"
        existing_org = customer_organization(conn, customer["id"])
        if existing_org and data.organization_id is None:
            data.organization_id = existing_org["id"]
        if existing_org and existing_org["id"] != data.organization_id:
            raise HTTPException(409, "Заказчик уже состоит в другой компании")
        if data.organization_id and not existing_org:
            conn.execute("INSERT INTO organization_members(organization_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                         (data.organization_id, customer["id"], data.role, now()))
        if registered:
            return {"customer_id": customer["id"], "email": email, "organization_id": data.organization_id, "registered": True}
        conn.execute("UPDATE users SET temporary_credentials_expires_at=? WHERE id=?", ((datetime.now(timezone.utc)+timedelta(hours=72)).isoformat(), customer["id"]))
        access = issue_account_link(conn, customer, "invite")
        response.headers["Cache-Control"] = "no-store"
        return {"customer_id": customer["id"], "email": email, "organization_id": data.organization_id, "registered": False, **access}


@app.post("/api/account/reset-request")
def request_password_reset(data: AccountEmail):
    email = clean_email(data.email)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT * FROM users WHERE email=? AND active=1 AND must_change_credentials=0", (email,)).fetchone()
        if user and not email.endswith("@access.local"):
            recent = conn.execute("SELECT 1 FROM account_tokens WHERE user_id=? AND kind='reset' AND created_at>?",
                                  (user["id"], (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat())).fetchone()
            if not recent:
                issue_account_link(conn, user, "reset")
    return {"message": "Если этот email зарегистрирован, мы отправили ссылку для восстановления доступа"}


@app.post("/api/account/activate/{kind}")
def activate_account(kind: Literal["invite", "reset"], data: AccountTokenPassword, response: Response):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        token = conn.execute("SELECT * FROM account_tokens WHERE token_hash=? AND kind=? AND expires_at>?", (token_hash(data.token), kind, now())).fetchone()
        if not token:
            raise HTTPException(409, "Приглашение недействительно или истекло. Попросите менеджера прислать новое" if kind == "invite" else "Ссылка недействительна или истекла. Запросите новую ссылку через «Забыли пароль?»")
        user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (token["user_id"],)).fetchone()
        if not user or (kind == "invite" and not user["must_change_credentials"]):
            raise HTTPException(409, "Приглашение уже использовано или доступ отключён")
        conn.execute("UPDATE users SET password_hash=?,must_change_credentials=0,temporary_credentials_expires_at=NULL WHERE id=?", (password_hash(data.password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        conn.execute("DELETE FROM account_tokens WHERE user_id=?", (user["id"],))
        response.headers["Cache-Control"] = "no-store"
        return issue_session(conn, conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone(), response)


@app.post("/api/company-owners/{owner_id}/temporary-access")
def renew_temporary_owner_access(owner_id: int, response: Response, desk_session: str | None = Cookie(default=None)):
    manager = current_user(desk_session)
    require_dispatcher(manager)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        owner = conn.execute("SELECT * FROM users WHERE id=? AND role='customer' AND active=1 AND must_change_credentials=1", (owner_id,)).fetchone()
        if not owner or not owner["email"].endswith("@access.local"):
            raise HTTPException(409, "Перевыпуск доступен только владельцу с временным логином")
        password = secrets.token_urlsafe(18)
        expires = (datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
        conn.execute("UPDATE users SET password_hash=?,temporary_credentials_expires_at=? WHERE id=?", (password_hash(password), expires, owner_id))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (owner_id,))
        response.headers["Cache-Control"] = "no-store"
        return {"id": owner_id, "login": owner["email"], "temporary_password": password, "expires_at": expires}


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
        return [{**dict(row), "has_available_owner": bool(available_owners(conn, row["id"])), "members": [dict(x) for x in conn.execute("""SELECT m.user_id,m.role,u.name,u.email,u.active,u.must_change_credentials,u.temporary_credentials_expires_at
            FROM organization_members m JOIN users u ON u.id=m.user_id WHERE m.organization_id=? ORDER BY m.role,u.name""", (row["id"],))]} for row in rows]


@app.post("/api/organizations", status_code=201)
def create_organization(data: OrganizationCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_dispatcher(user)
    if len(data.name.strip()) < 2:
        raise HTTPException(422, "Укажите название компании: минимум 2 символа")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        owner = conn.execute("""SELECT id FROM users WHERE id=? AND role='customer' AND active=1
            AND (must_change_credentials=0 OR temporary_credentials_expires_at>?)
            AND NOT EXISTS (SELECT 1 FROM account_tokens a WHERE a.user_id=users.id AND a.kind='invite')""", (data.owner_id, now())).fetchone()
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
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_company_manager(conn, user, organization_id)
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
    if row["role"] == "owner" and not available_owners(conn, organization_id, member_id):
        raise HTTPException(409, "Сначала назначьте другого активного владельца с действующим доступом")
    return row


@app.patch("/api/organizations/{organization_id}/members/{member_id}")
def update_organization_member(organization_id: int, member_id: int, data: OrganizationMemberRole,
                               desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_company_manager(conn, user, organization_id)
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
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_company_manager(conn, user, organization_id)
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
            unbilled_service = unbilled_service_minutes(conn, client_type, client_id)
            unbilled_minutes = sum(approved_minutes(conn, t["id"]) for t in unbilled_tickets) + unbilled_service

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
            paid_sum = conn.execute("SELECT COALESCE(SUM(total_rub), 0) FROM invoices WHERE status='paid' AND doc_type='invoice'").fetchone()[0]

            active_tickets = conn.execute("SELECT id FROM tickets WHERE status IN ('new','working','waiting')").fetchall()
            total_active_mins = sum(approved_minutes(conn, t["id"]) for t in active_tickets)

            clients = []
            for o in conn.execute("SELECT * FROM organizations ORDER BY name").fetchall():
                unb = conn.execute("SELECT id FROM tickets WHERE organization_id=? AND status IN ('done','closed') AND act_invoice_id IS NULL", (o["id"],)).fetchall()
                service_mins = unbilled_service_minutes(conn, "org", o["id"])
                unb_mins = sum(approved_minutes(conn, t["id"]) for t in unb) + service_mins
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
                    "unbilled_service_minutes": service_mins,
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
                service_mins = unbilled_service_minutes(conn, "user", s["id"])
                unb_mins = sum(approved_minutes(conn, t["id"]) for t in unb) + service_mins
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
                    "unbilled_service_minutes": service_mins,
                    "open_tickets": open_cnt
                })

            service_entries = conn.execute(f"{SERVICE_ENTRY_SELECT} ORDER BY s.occurred_at DESC, s.id DESC LIMIT 100").fetchall()

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
                "service_entries": [dict(r) for r in service_entries],
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
            if data.ticket_ids is not None:
                placeholders = ",".join("?" * len(data.ticket_ids))
                tickets = conn.execute(f"SELECT * FROM tickets WHERE id IN ({placeholders}) AND act_invoice_id IS NULL", data.ticket_ids).fetchall() if data.ticket_ids else []
            else:
                if data.client_type == "org":
                    tickets = conn.execute("SELECT * FROM tickets WHERE organization_id=? AND status IN ('done','closed') AND act_invoice_id IS NULL", (data.client_id,)).fetchall()
                else:
                    tickets = conn.execute("SELECT * FROM tickets WHERE customer_id=? AND organization_id IS NULL AND status IN ('done','closed') AND act_invoice_id IS NULL", (data.client_id,)).fetchall()

            service_cond, service_params = client_condition(data.client_type, data.client_id)
            if data.service_entry_ids is not None:
                ids = data.service_entry_ids or [0]
                service_cond += f" AND id IN ({','.join('?' * len(ids))})"
                service_params += tuple(ids)
            services = conn.execute(f"""SELECT * FROM service_entries WHERE {service_cond} AND act_invoice_id IS NULL
                ORDER BY occurred_at, id""", service_params).fetchall()

            if not tickets and not services:
                raise HTTPException(422, "Не найдено завершенных задач или часов сопровождения для формирования акта")

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

            service_mins = sum(s["minutes"] for s in services)
            if service_mins:
                cost = round(service_mins / 60.0 * rate)
                total_mins += service_mins
                total_rub += cost
                items.append({
                    "title": SERVICE_ACT_TITLE,
                    "minutes": service_mins,
                    "hours": round(service_mins / 60.0, 2),
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

            if ticket_ids_to_link:
                conn.execute(f"UPDATE tickets SET act_invoice_id=? WHERE id IN ({','.join('?'*len(ticket_ids_to_link))})", (act_id, *ticket_ids_to_link))
            if services:
                conn.execute(f"UPDATE service_entries SET act_invoice_id=? WHERE id IN ({','.join('?'*len(services))})",
                             (act_id, *(s["id"] for s in services)))

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
    require_dispatcher(user)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Документ не найден")

        if data.status == 'paid' and row['doc_type'] != 'invoice':
            raise HTTPException(422, "Акт нужно подписать, а не отмечать оплаченным")
        if data.status == 'signed':
            if row['doc_type'] != 'act' or row['status'] != 'issued':
                raise HTTPException(409, "Подписать можно только действующий акт")
            conn.execute("UPDATE invoices SET signed_at=COALESCE(signed_at,?),signed_by_id=COALESCE(signed_by_id,?) WHERE id=?", (now(),user['id'],invoice_id))
            return {"ok": True, "status": "issued", "signature_status": "signed"}
        if row['status'] == data.status:
            return {"ok": True, "status": row['status']}
        if row['status'] == 'cancelled' or data.status == 'issued':
            raise HTTPException(409, "Завершённый документ нельзя выставить повторно. Создайте новый")
        if row['doc_type'] == 'invoice' and row['status'] == 'paid':
            raise HTTPException(409, "Оплаченный счёт нельзя аннулировать без возврата платежа")

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
                conn.execute("UPDATE service_entries SET act_invoice_id=NULL WHERE act_invoice_id=?", (invoice_id,))
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


# ==============================================================================
# Взаимодействие с клиентом: «Ждём от вас», напоминания, почта и ежемесячная сводка
# ==============================================================================

def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def reminder_settings():
    return {"first_hours": env_int("REMINDER_FIRST_HOURS", 48), "repeat_hours": env_int("REMINDER_REPEAT_HOURS", 72),
            "max": env_int("REMINDER_MAX", 3)}


def local_tz():
    return timezone(timedelta(hours=env_int("APP_UTC_OFFSET", 3)))


def public_base():
    return os.getenv("APP_PUBLIC_URL", "").rstrip("/") or "http://localhost:8000"


def ru_plural(n, one, few, many):
    a, b = abs(n) % 100, abs(n) % 10
    return many if 10 < a < 20 else one if b == 1 else few if 2 <= b <= 4 else many


def fmt_hours(minutes):
    return f"{minutes / 60:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " ч"


def snippet(text, limit=160):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def customer_visible_tickets(conn, user, extra=""):
    return conn.execute(f"""SELECT t.* FROM tickets t WHERE ((t.customer_id=? AND t.visibility!='organization')
        OR (t.visibility='organization' AND t.organization_id IN (SELECT organization_id FROM organization_members WHERE user_id=?)))
        {extra} ORDER BY t.updated_at DESC, t.id DESC""", (user["id"], user["id"])).fetchall()


def last_status_event(conn, ticket_id, status):
    return conn.execute("""SELECT id,created_at FROM ticket_events WHERE ticket_id=? AND kind='status' AND new_value=?
        ORDER BY id DESC LIMIT 1""", (ticket_id, status)).fetchone()


def customer_pending_actions(conn, user):
    """Всё, что тормозит работу по вине клиента: решения по оценкам и часам, приёмка и ответы на вопросы команды."""
    if user["role"] != "customer":
        return []
    items = []
    for t in customer_visible_tickets(conn, user, "AND t.status!='closed'"):
        base = {"ticket_id": t["id"], "title": t["title"]}
        if customer_can_decide(conn, t, user):
            estimate = latest_estimate(conn, t["id"])
            if estimate and estimate["state"] == "pending" and estimate["effort_minutes"] is not None:
                items.append({**base, "kind": "estimate", "ref_id": estimate["id"], "since": estimate["created_at"],
                              "effort_minutes": estimate["effort_minutes"],
                              "action": "Одобрите оценку",
                              "detail": f"Версия {estimate['version']} · {fmt_hours(estimate['effort_minutes'])}"})
            for request in conn.execute("SELECT * FROM hour_requests WHERE ticket_id=? AND state='pending'", (t["id"],)):
                items.append({**base, "kind": "hours", "ref_id": request["id"], "since": request["created_at"],
                              "action": "Согласуйте дополнительные часы",
                              "detail": f"+{fmt_hours(request['minutes'])}: {snippet(request['reason'], 120)}"})
            if t["status"] == "done":
                event = last_status_event(conn, t["id"], "done")
                items.append({**base, "kind": "acceptance", "ref_id": event["id"] if event else 0,
                              "since": event["created_at"] if event else t["updated_at"],
                              "action": "Проверьте и примите работу", "detail": "Работа выполнена и ждёт вашей приёмки"})
        if t["status"] == "waiting" and customer_can_write_ticket(conn, t, user):
            event = last_status_event(conn, t["id"], "waiting")
            since = event["created_at"] if event else t["updated_at"]
            answered = conn.execute("""SELECT 1 FROM messages m JOIN users u ON u.id=m.author_id
                WHERE m.ticket_id=? AND u.role='customer' AND m.created_at>?""", (t["id"], since)).fetchone()
            if not answered:
                question = conn.execute("""SELECT m.body FROM messages m JOIN users u ON u.id=m.author_id
                    WHERE m.ticket_id=? AND u.role!='customer' ORDER BY m.id DESC LIMIT 1""", (t["id"],)).fetchone()
                items.append({**base, "kind": "answer", "ref_id": event["id"] if event else 0, "since": since,
                              "action": "Ответьте на вопрос команды",
                              "detail": snippet(question["body"]) if question else "Команде нужна информация от вас"})
    return sorted(items, key=lambda item: item["since"])


@app.post("/api/estimates/approve")
def approve_estimates(data: BulkEstimateApproval, desk_session: str | None = Cookie(default=None)):
    """Одобрить сразу несколько оценок. Всё или ничего: если одна уже изменилась, клиент увидит актуальный список."""
    user = current_user(desk_session)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        approved = []
        for estimate_id in dict.fromkeys(data.estimate_ids):
            row = conn.execute("SELECT ticket_id FROM estimates WHERE id=?", (estimate_id,)).fetchone()
            if not row:
                raise HTTPException(409, "Оценка уже изменена или рассмотрена")
            decide_estimate_service(conn, user, row["ticket_id"], EstimateDecision(estimate_id=estimate_id, action="approve"))
            approved.append(row["ticket_id"])
        return {"approved": len(approved), "ticket_ids": approved}


@app.get("/api/ticket-templates")
def ticket_templates(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM ticket_templates ORDER BY name COLLATE NOCASE, id")]


@app.post("/api/ticket-templates", status_code=201)
def create_ticket_template(data: TicketTemplateCreate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        cursor = conn.execute("""INSERT INTO ticket_templates(name,title,description,service_type,effort_minutes,
            estimate_note,created_by_id,created_at) VALUES(?,?,?,?,?,?,?,?)""",
            (" ".join(data.name.split()), data.title.strip(), data.description.strip(), data.service_type,
             data.effort_minutes, data.estimate_note.strip(), user["id"], now()))
        return dict(conn.execute("SELECT * FROM ticket_templates WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.delete("/api/ticket-templates/{template_id}")
def delete_ticket_template(template_id: int, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    require_staff(user)
    with db() as conn:
        row = conn.execute("SELECT created_by_id FROM ticket_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Шаблон не найден")
        if row["created_by_id"] != user["id"] and user["role"] != "admin" and not user["is_manager"]:
            raise HTTPException(403, "Удалить шаблон может автор или руководитель")
        conn.execute("DELETE FROM ticket_templates WHERE id=?", (template_id,))
        return {"deleted": template_id}


@app.get("/api/waiting-on-me")
def waiting_on_me(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        return customer_pending_actions(conn, user)


REMINDER_TEXT = {"estimate": "ждёт вашего решения по оценке", "hours": "ждёт согласования дополнительных часов",
                 "acceptance": "ждёт приёмки работы", "answer": "ждёт вашего ответа"}


def run_reminders(at: datetime | None = None) -> int:
    """Напоминает клиенту о его шагах: первый раз через REMINDER_FIRST_HOURS, затем не чаще REMINDER_REPEAT_HOURS.

    После последнего напоминания ответственный узнаёт, что клиент молчит, и может предложить закрыть заявку.
    """
    at = at or datetime.now(timezone.utc)
    cfg = reminder_settings()
    if cfg["max"] <= 0:
        return 0
    sent = 0
    with db() as conn:
        customers = conn.execute("SELECT * FROM users WHERE role='customer' AND active=1").fetchall()
    for user in customers:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for item in customer_pending_actions(conn, user):
                age_hours = (at - datetime.fromisoformat(item["since"])).total_seconds() / 3600
                key = (user["id"], item["ticket_id"], item["kind"], item["ref_id"])
                row = conn.execute("""SELECT count,last_sent_at FROM customer_reminders
                    WHERE user_id=? AND ticket_id=? AND kind=? AND ref_id=?""", key).fetchone()
                if row:
                    since_last = (at - datetime.fromisoformat(row["last_sent_at"])).total_seconds() / 3600
                    if row["count"] >= cfg["max"] or since_last < cfg["repeat_hours"]:
                        continue
                elif age_hours < cfg["first_hours"]:
                    continue
                count = (row["count"] if row else 0) + 1
                days = max(1, int(age_hours // 24))
                waited = f"{days} {ru_plural(days, 'день', 'дня', 'дней')}"
                final = count >= cfg["max"]
                text = f"Напоминание: заявка №{item['ticket_id']} {REMINDER_TEXT[item['kind']]} уже {waited}"
                if final and item["kind"] == "answer":
                    text += ". Если задача уже неактуальна, напишите — закроем заявку"
                notify(conn, user["id"], item["ticket_id"], "reminder", text)
                conn.execute("""INSERT INTO customer_reminders(user_id,ticket_id,kind,ref_id,count,last_sent_at) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(user_id,ticket_id,kind,ref_id) DO UPDATE SET count=excluded.count,last_sent_at=excluded.last_sent_at""",
                             (*key, count, at.isoformat()))
                if final and item["kind"] in ("answer", "acceptance"):
                    ticket = conn.execute("SELECT assignee_id FROM tickets WHERE id=?", (item["ticket_id"],)).fetchone()
                    silent = (f"Заказчик не принимает работу по заявке №{item['ticket_id']} уже {waited} — уточните или закройте заявку"
                              if item["kind"] == "acceptance" else
                              f"Заказчик не отвечает по заявке №{item['ticket_id']} уже {waited} — можно предложить закрыть заявку")
                    for recipient in ({ticket["assignee_id"]} - {None}) or dispatcher_ids(conn):
                        notify(conn, recipient, item["ticket_id"], "customer_silent", silent)
                sent += 1
    return sent


# ---------- Почта: настройки ----------

def email_preferences(conn, user):
    row = conn.execute("SELECT * FROM email_preferences WHERE user_id=?", (user["id"],)).fetchone()
    customer = user["role"] == "customer"
    # По умолчанию письма получают заказчики: команда работает в кабинете и получает push.
    return {"notify": bool(row["notify"]) if row else customer,
            "digest": bool(row["digest"]) if row and customer else customer,
            "digest_emails": [e for e in (row["digest_emails"] if row else "").split(",") if e] if customer else [],
            "email": user["email"], "available": mailer.enabled(), "replies": inbound_enabled()}


def inbound_enabled():
    return mailer.imap_configured() or bool(os.getenv("EMAIL_INBOUND_SECRET", "").strip())


@app.get("/api/email/preferences")
def get_email_preferences(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    with db() as conn:
        return email_preferences(conn, user)


@app.put("/api/email/preferences")
def update_email_preferences(data: EmailPreferencesUpdate, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    customer = user["role"] == "customer"
    extra = []
    for raw in data.digest_emails if customer else []:
        if raw.strip():
            address = clean_email(raw)
            if address != user["email"] and address not in extra:
                extra.append(address)
    with db() as conn:
        conn.execute("""INSERT INTO email_preferences(user_id,notify,digest,digest_emails,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET notify=excluded.notify,digest=excluded.digest,
            digest_emails=excluded.digest_emails,updated_at=excluded.updated_at""",
                     (user["id"], int(data.notify), int(data.digest and customer), ",".join(extra), now()))
        return email_preferences(conn, user)


@app.post("/api/email/test")
def send_test_email(desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if not mailer.enabled():
        raise HTTPException(409, "Почта пока не настроена администратором")
    body = "Письма от кабинета доходят до вас. Уведомления о заявках будут приходить на этот адрес."
    with db() as conn:
        queue_email(conn, user["id"], user["email"], "test", "Проверка почты",
                    body, email_layout("Почта работает", f"<p>{html.escape(body)}</p>", [("Открыть кабинет", public_base() + "/")]))
    return {"ok": True, "email": user["email"]}


# ---------- Почта: очередь ----------

def queue_email(conn, user_id, to_addr, kind, subject, text_body, html_body, delay=0):
    conn.execute("""INSERT INTO email_outbox(user_id,to_addr,kind,subject,text_body,html_body,available_at,created_at)
        VALUES(?,?,?,?,?,?,?,?)""", (user_id, to_addr, kind, subject, text_body, html_body, time.time() + delay, now()))


def queue_notification_email(conn, user_id, target, record_id, kind, text, notification_id):
    """Письмо о событии уходит с задержкой и только если человек не увидел событие в кабинете.

    События одной переписки, пришедшие за время задержки, собираются в одно письмо.
    """
    if not mailer.enabled():
        return
    user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
    if not user or not email_preferences(conn, user)["notify"]:
        return
    event = {"kind": kind, "text": text, "notification_id": notification_id}
    pending = conn.execute("""SELECT id,payload FROM email_outbox WHERE user_id=? AND kind='notification' AND state='pending'
        AND json_extract(payload,'$.target')=? AND json_extract(payload,'$.record_id')=? ORDER BY id DESC LIMIT 1""",
                           (user_id, target, record_id)).fetchone()
    if pending:
        payload = json.loads(pending["payload"])
        payload["events"] = (payload["events"] + [event])[-20:]
        conn.execute("UPDATE email_outbox SET payload=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), pending["id"]))
        return
    payload = {"target": target, "record_id": record_id, "events": [event]}
    conn.execute("""INSERT INTO email_outbox(user_id,to_addr,kind,payload,available_at,created_at) VALUES(?,?,?,?,?,?)""",
                 (user_id, user["email"], "notification", json.dumps(payload, ensure_ascii=False),
                  time.time() + env_int("EMAIL_DELAY_SECONDS", 120), now()))


def claim_email():
    stamp = time.time()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE email_outbox SET state='pending',lease_token=NULL WHERE state='sending' AND lease_until<?", (stamp,))
        row = conn.execute("SELECT * FROM email_outbox WHERE state='pending' AND available_at<=? ORDER BY id LIMIT 1",
                           (stamp,)).fetchone()
        if not row:
            return None
        lease = secrets.token_hex(12)
        conn.execute("UPDATE email_outbox SET state='sending',lease_until=?,lease_token=?,attempts=attempts+1 WHERE id=?",
                     (stamp + 120, lease, row["id"]))
        return {**dict(row), "lease_token": lease, "attempts": row["attempts"] + 1}


def finish_email(job, state, error=None, retry_in=0):
    with db() as conn:
        conn.execute("""UPDATE email_outbox SET state=?,last_error=?,lease_token=NULL,available_at=?,
            sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END WHERE id=? AND lease_token=?""",
                     (state, error, time.time() + retry_in, state, now(), job["id"], job["lease_token"]))


def deliver_emails(limit=20) -> int:
    processed = 0
    while processed < limit:
        job = claim_email()
        if not job:
            break
        processed += 1
        try:
            with db() as conn:
                message = render_outbox_email(conn, job)
            if message is None:
                finish_email(job, "skipped")
                continue
            mailer.send(message, DB_PATH.parent / "mail_outbox")
            finish_email(job, "sent")
        except Exception as exc:
            terminal = mailer.permanent_error(exc) or job["attempts"] >= 6
            finish_email(job, "failed" if terminal else "pending", f"{type(exc).__name__}: {exc}"[:300],
                         min(60 * 2 ** job["attempts"], 3600))
    return processed


# ---------- Почта: оформление писем ----------

def email_layout(title, body_html, buttons=(), footer=""):
    links = "".join(
        f'<a href="{html.escape(url)}" style="display:inline-block;margin:4px 8px 4px 0;padding:11px 18px;border-radius:9px;'
        f'background:{"#137b69" if index == 0 else "#e8f1ee"};color:{"#ffffff" if index == 0 else "#123b36"};'
        f'font-weight:600;text-decoration:none">{html.escape(label)}</a>'
        for index, (label, url) in enumerate(buttons))
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light"><title>{html.escape(title)}</title></head>
<body style="margin:0;background:#f3f6f5;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#17302c">
<div style="max-width:600px;margin:0 auto;padding:24px 16px">
<div style="font-weight:800;font-size:18px;margin-bottom:16px;color:#122527">Линия<span style="color:#137b69">.</span></div>
<div style="background:#ffffff;border:1px solid #dbe5e2;border-radius:14px;padding:24px">
<h1 style="font-size:20px;line-height:1.3;margin:0 0 14px">{html.escape(title)}</h1>
<div style="font-size:15px;line-height:1.55">{body_html}</div>
{f'<div style="margin-top:20px">{links}</div>' if links else ''}
</div>
<div style="font-size:12px;line-height:1.5;color:#6b7f7a;margin-top:16px">{footer}</div>
</div></body></html>"""


def quote_html(author, body):
    text = html.escape(snippet(body, 1200)).replace("\n", "<br>")
    return (f'<div style="margin:12px 0;padding:10px 14px;border-left:3px solid #137b69;background:#f3f8f6;border-radius:6px">'
            f'<div style="font-size:12px;color:#5c716c;margin-bottom:4px">{html.escape(author)}</div>{text}</div>')


def email_token(conn, user_id, purpose, action=None, ticket_id=None, chat_id=None, ref_id=None, days=14):
    raw = secrets.token_urlsafe(24)
    conn.execute("""INSERT INTO email_tokens(token_hash,user_id,purpose,action,ticket_id,chat_id,ref_id,expires_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""", (token_hash(raw), user_id, purpose, action, ticket_id, chat_id, ref_id,
                                       (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(), now()))
    return raw


def action_url(conn, user_id, action, **target):
    return f"{public_base()}/email/a/{email_token(conn, user_id, 'action', action, **target)}"


def render_outbox_email(conn, job):
    if job["kind"] != "notification":
        unsubscribe = None
        if job["kind"] == "digest" and job["user_id"]:
            unsubscribe = action_url(conn, job["user_id"], "unsubscribe_digest", days=60)
        headers = {"List-Unsubscribe": f"<{unsubscribe}>"} if unsubscribe else {}
        return mailer.build([job["to_addr"]], job["subject"], job["text_body"], job["html_body"], headers=headers)
    user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (job["user_id"],)).fetchone()
    if not user or not email_preferences(conn, user)["notify"]:
        return None
    payload = json.loads(job["payload"])
    target, record_id = payload["target"], payload["record_id"]
    table = "notifications" if target == "ticket" else "chat_notifications"
    events = [e for e in payload["events"] if conn.execute(f"SELECT 1 FROM {table} WHERE id=? AND read_at IS NULL",
                                                           (e["notification_id"],)).fetchone()]
    if not events:
        return None
    try:
        record = ticket_for(conn, record_id, user) if target == "ticket" else chat_for(conn, record_id, user)
    except HTTPException:
        return None
    customer = user["role"] == "customer"
    if target == "ticket":
        heading = f"Заявка №{record_id}: {record['title']}"
        can_write = record["status"] != "closed" and customer_can_write_ticket(conn, record, user)
        open_url = f"{public_base()}/#ticket/{record_id}"
        messages_sql = f"{TICKET_MESSAGE_SELECT} WHERE m.ticket_id=? AND m.author_id!=? AND m.id>? ORDER BY m.id DESC LIMIT 5"
    else:
        heading = "Общий чат с командой" if customer else f"Общий чат: {record['customer_name']}"
        can_write = True
        open_url = f"{public_base()}/#chat/{record_id}"
        messages_sql = f"{CHAT_MESSAGE_SELECT} WHERE m.chat_id=? AND m.author_id!=? AND m.id>? ORDER BY m.id DESC LIMIT 5"
    read = conn.execute("SELECT last_read_id FROM message_reads WHERE kind=? AND record_id=? AND user_id=?",
                        (target, record_id, user["id"])).fetchone()
    unread = list(reversed(conn.execute(messages_sql, (record_id, user["id"], read["last_read_id"] if read else 0)).fetchall()))
    if not any(e["kind"] == "message" for e in events):
        unread = []
    text_lines = [heading, ""] + [f"• {e['text']}" for e in events]
    body = "".join(f"<p style=\"margin:0 0 6px\">• {html.escape(e['text'])}</p>" for e in events)
    for message in unread:
        body += quote_html(f"{message['author_name']} · {format_ru_date(message['created_at']).removesuffix(' г.')}", message["body"])
        text_lines += ["", f"{message['author_name']}:", message["body"]]
    buttons = []
    if customer and target == "ticket" and customer_can_decide(conn, record, user):
        estimate = latest_estimate(conn, record_id)
        if estimate and estimate["state"] == "pending" and estimate["effort_minutes"] is not None and record["status"] != "closed":
            body += (f"<p>Оценка, версия {estimate['version']}: <strong>{fmt_hours(estimate['effort_minutes'])}</strong>"
                     f"{'<br>' + html.escape(snippet(estimate['note'], 600)) if estimate['note'] else ''}</p>")
            buttons.append(("Одобрить оценку", action_url(conn, user["id"], "approve_estimate", ticket_id=record_id, ref_id=estimate["id"])))
        hours_request = conn.execute("SELECT * FROM hour_requests WHERE ticket_id=? AND state='pending' ORDER BY id DESC LIMIT 1",
                                     (record_id,)).fetchone()
        if hours_request and record["status"] in ("working", "waiting"):
            body += f"<p>Запрошено ещё <strong>{fmt_hours(hours_request['minutes'])}</strong>: {html.escape(snippet(hours_request['reason'], 400))}</p>"
            buttons.append(("Одобрить часы", action_url(conn, user["id"], "approve_hours", ticket_id=record_id, ref_id=hours_request["id"])))
        if record["status"] == "done":
            buttons.append(("Принять работу", action_url(conn, user["id"], "accept_work", ticket_id=record_id)))
        if customer_can_decline(conn, record, user):
            buttons.append(("Заявка не нужна", action_url(conn, user["id"], "decline_ticket", ticket_id=record_id)))
    buttons.append(("Открыть в кабинете", open_url))
    text_lines += ["", f"Открыть в кабинете: {open_url}"]
    message_id = None
    footer = ""
    if can_write and inbound_enabled() and mailer.reply_address():
        reply = email_token(conn, user["id"], "reply", ticket_id=record_id if target == "ticket" else None,
                            chat_id=record_id if target == "chat" else None, days=90)
        message_id = f"<r.{reply}@{mailer.sender_domain()}>"
        footer += "Ответьте на это письмо — текст попадёт в переписку. "
        text_lines += ["", "Ответьте на это письмо — текст попадёт в переписку.", f"ref:{reply}"]
    unsubscribe = action_url(conn, user["id"], "unsubscribe", days=60)
    footer += (f'Вы получили письмо, потому что не открывали кабинет после этого события. '
               f'<a href="{html.escape(unsubscribe)}" style="color:#6b7f7a">Отключить письма</a>')
    if message_id:
        footer += f'<span style="color:#f3f6f5;font-size:1px">ref:{message_id[3:-1].split("@")[0]}</span>'
    subject = events[0]["text"] if len(events) == 1 else f"{heading}: {len(events)} {ru_plural(len(events), 'событие', 'события', 'событий')}"
    thread = f"<thread.{target}.{record_id}.{user['id']}@{mailer.sender_domain()}>"
    return mailer.build([user["email"]], subject, "\n".join(text_lines),
                        email_layout(heading, body, buttons, footer), message_id=message_id,
                        headers={"References": thread, "In-Reply-To": thread, "List-Unsubscribe": f"<{unsubscribe}>"})


# ---------- Почта: действия из писем ----------

EMAIL_ACTIONS = {"approve_estimate": "Одобрить оценку", "approve_hours": "Одобрить дополнительные часы",
                 "accept_work": "Принять работу", "decline_ticket": "Отказаться от заявки", "unsubscribe": "Отключить письма об изменениях",
                 "unsubscribe_digest": "Отключить ежемесячную сводку"}


def email_action_page(title, text, button=None, status=200):
    form = (f'<form method="post"><button type="submit" style="padding:12px 20px;border:0;border-radius:9px;background:#137b69;'
            f'color:#fff;font-size:15px;font-weight:600;cursor:pointer">{html.escape(button)}</button></form>') if button else ""
    return HTMLResponse(email_layout(title, f"<p>{html.escape(text)}</p>{form}", [] if button else [("Открыть кабинет", public_base() + "/")]),
                        status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def email_action_token(conn, token):
    row = conn.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose='action'", (token_hash(token),)).fetchone()
    if not row or row["expires_at"] < now():
        return None, "Ссылка устарела. Откройте кабинет, чтобы продолжить."
    if row["used_at"] and not row["action"].startswith("unsubscribe"):
        return None, "Это действие уже выполнено по ссылке из письма."
    user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (row["user_id"],)).fetchone()
    if not user:
        return None, "Учётная запись недоступна."
    return (row, user), None


def describe_email_action(conn, row):
    if row["action"] == "approve_estimate":
        estimate = conn.execute("SELECT * FROM estimates WHERE id=?", (row["ref_id"],)).fetchone()
        return f"Одобрить оценку заявки №{row['ticket_id']}: версия {estimate['version']}, {fmt_hours(estimate['effort_minutes'] or 0)}? После одобрения команда приступит к работе."
    if row["action"] == "approve_hours":
        request = conn.execute("SELECT * FROM hour_requests WHERE id=?", (row["ref_id"],)).fetchone()
        return f"Одобрить ещё {fmt_hours(request['minutes'])} по заявке №{row['ticket_id']}? {snippet(request['reason'], 300)}"
    if row["action"] == "accept_work":
        return f"Принять работу по заявке №{row['ticket_id']}? Заявка будет закрыта. Если нужна доработка, откройте кабинет и верните её с комментарием."
    if row["action"] == "decline_ticket":
        return f"Отказаться от заявки №{row['ticket_id']}? Она закроется без работы и оплаты, команда получит уведомление."
    if row["action"] == "unsubscribe":
        return "Письма о новых сообщениях и событиях по заявкам больше не будут приходить. Включить их снова можно в профиле."
    return "Ежемесячная сводка по заявкам больше не будет приходить. Включить её снова можно в профиле."


@app.get("/email/a/{token}")
def email_action_confirm(token: str):
    with db() as conn:
        found, error = email_action_token(conn, token)
        if error:
            return email_action_page("Ссылка недоступна", error, status=410)
        row, _ = found
        return email_action_page(EMAIL_ACTIONS.get(row["action"], "Действие"), describe_email_action(conn, row),
                                 "Подтвердить")


@app.post("/email/a/{token}")
def email_action_run(token: str):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        found, error = email_action_token(conn, token)
        if error:
            return email_action_page("Ссылка недоступна", error, status=410)
        row, user = found
        try:
            if row["action"] == "approve_estimate":
                decide_estimate_service(conn, user, row["ticket_id"], EstimateDecision(estimate_id=row["ref_id"], action="approve"))
                done = "Оценка одобрена — команда приступит к работе."
            elif row["action"] == "approve_hours":
                decide_hours_service(conn, user, row["ticket_id"], row["ref_id"], HourRequestDecision(action="approve"))
                done = "Дополнительные часы одобрены."
            elif row["action"] == "accept_work":
                accept_work_service(conn, user, row["ticket_id"], AcceptanceDecision(action="accept"))
                done = "Работа принята, заявка закрыта. Спасибо! Оценить работу команды можно в кабинете."
            elif row["action"] == "decline_ticket":
                decline_ticket_service(conn, user, row["ticket_id"], TicketDecline())
                done = "Заявка закрыта — команда получила уведомление."
            else:
                column = "notify" if row["action"] == "unsubscribe" else "digest"
                prefs = email_preferences(conn, user)
                conn.execute("""INSERT INTO email_preferences(user_id,notify,digest,digest_emails,updated_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET {0}=0,updated_at=excluded.updated_at""".format(column),
                             (user["id"], 0 if column == "notify" else int(prefs["notify"]),
                              0 if column == "digest" else int(prefs["digest"]), ",".join(prefs["digest_emails"]), now()))
                done = "Готово. Настройки писем можно изменить в профиле кабинета."
        except HTTPException as exc:
            conn.execute("ROLLBACK")
            return email_action_page("Не получилось", str(exc.detail), status=409)
        conn.execute("UPDATE email_tokens SET used_at=? WHERE token_hash=?", (now(), token_hash(token)))
        return email_action_page("Готово", done)


# ---------- Почта: ответы клиентов ----------

def process_inbound_email(raw: bytes) -> str:
    """Ответ на письмо становится сообщением в той же переписке. Повторная доставка письма не создаёт копию."""
    parsed = mailer.parse(raw)
    message_id = parsed["message_id"] or "sha:" + hashlib.sha256(raw).hexdigest()
    bounce = None
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM email_inbound WHERE message_id=?", (message_id,)).fetchone():
            return "duplicate"
        result, user, kind, record = "ignored", None, None, None
        token = mailer.reply_token(parsed)
        row = conn.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose='reply'",
                           (token_hash(token),)).fetchone() if token else None
        if parsed["auto_reply"]:
            result = "auto_reply"
        elif not row or row["expires_at"] < now():
            result = "unknown_token"
        else:
            user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (row["user_id"],)).fetchone()
            kind, record = ("ticket", row["ticket_id"]) if row["ticket_id"] else ("chat", row["chat_id"])
            body = mailer.strip_quoted(parsed["body"])[:10000]
            if not user or parsed["from"] != user["email"]:
                result, user = "sender_mismatch", None
            elif not body:
                result = "empty"
            else:
                data = MessageCreate(body=body, request_id="mail-" + hashlib.sha256(message_id.encode()).hexdigest()[:40])
                conn.execute("SAVEPOINT inbound")
                try:
                    if kind == "ticket":
                        add_message_service(conn, user, record, data)
                    else:
                        add_chat_message_service(conn, user, record, data)
                    result = "posted"
                except HTTPException as exc:
                    conn.execute("ROLLBACK TO inbound")
                    result = f"rejected: {exc.detail}"
                    bounce = exc.detail
                finally:
                    conn.execute("RELEASE inbound")
        conn.execute("INSERT INTO email_inbound VALUES(?,?,?,?,?,?)",
                     (message_id, user["id"] if user else None, kind, record, result, now()))
        if bounce and user and mailer.enabled():
            where = f"по заявке №{record}" if kind == "ticket" else "в общий чат"
            text = f"Ваш ответ {where} не добавлен: {bounce}. Откройте кабинет, чтобы продолжить переписку."
            queue_email(conn, user["id"], user["email"], "bounce", "Ответ не доставлен", text,
                        email_layout("Ответ не доставлен", f"<p>{html.escape(text)}</p>",
                                     [("Открыть кабинет", f"{public_base()}/#{kind}/{record}")]))
    return result


@app.post("/api/email/inbound")
async def inbound_email_webhook(request: Request):
    secret = os.getenv("EMAIL_INBOUND_SECRET", "").strip()
    if not secret:
        raise HTTPException(404, "Не найдено")
    if not hmac.compare_digest(request.headers.get("x-inbound-secret", ""), secret):
        raise HTTPException(403, "Неверный ключ")
    raw = await request.body()
    if not raw or len(raw) > 5_000_000:
        raise HTTPException(413, "Письмо пустое или слишком большое")
    return {"result": await asyncio.to_thread(process_inbound_email, raw)}


# ---------- Ежемесячная сводка ----------

MONTHS_NOMINATIVE = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_PREPOSITIONAL = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"]


def month_bounds(period: str):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        raise HTTPException(422, "Период указывается как ГГГГ-ММ")
    year, month = map(int, period.split("-"))
    tz = local_tz()
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat(), month


def build_digest(conn, user, period):
    start, end, month = month_bounds(period)
    tickets = customer_visible_tickets(conn, user)
    ids = [t["id"] for t in tickets]
    marks = ",".join("?" * len(ids)) or "NULL"
    finished_ids = {row["ticket_id"] for row in conn.execute(f"""SELECT DISTINCT ticket_id FROM ticket_events
        WHERE ticket_id IN ({marks}) AND created_at>=? AND created_at<? AND
        ((kind='status' AND new_value IN ('done','closed')) OR (kind='acceptance' AND new_value='accepted'))""", (*ids, start, end))}
    finished = [t for t in tickets if t["id"] in finished_ids and t["status"] in ("done", "closed")]
    created = [t for t in tickets if start <= t["created_at"] < end]
    in_work = [t for t in tickets if t["status"] in ("new", "working", "waiting")]
    logged = conn.execute(f"SELECT COALESCE(SUM(minutes),0) FROM time_entries WHERE ticket_id IN ({marks}) AND created_at>=? AND created_at<?",
                          (*ids, start, end)).fetchone()[0]
    meetings = conn.execute(f"""{MEETING_SUMMARY_SELECT} WHERE s.shared_at IS NOT NULL AND s.occurred_at>=? AND s.occurred_at<?
        AND (s.ticket_id IN ({marks}) OR (s.ticket_id IS NULL AND s.customer_id=?)) ORDER BY s.occurred_at""",
                            (start, end, *ids, user["id"])).fetchall()
    return {"period": period, "month": month, "finished": finished, "created": created, "in_work": in_work,
            "waiting": customer_pending_actions(conn, user), "logged_minutes": logged, "meetings": meetings}


def render_digest(user, digest):
    month = MONTHS_PREPOSITIONAL[digest["month"] - 1]
    title = f"Работа по вашим заявкам в {month}"
    status_names = {"new": "новая", "working": "в работе", "waiting": "ждёт вашего ответа", "done": "на проверке", "closed": "закрыта"}

    def ticket_list(rows, extra=lambda t: ""):
        items = "".join(f'<li style="margin:0 0 6px"><a href="{public_base()}/#ticket/{t["id"]}" style="color:#137b69">№{t["id"]}</a> '
                        f'{html.escape(t["title"])}{extra(t)}</li>' for t in rows[:15])
        more = f'<li style="color:#6b7f7a">и ещё {len(rows) - 15}</li>' if len(rows) > 15 else ""
        return f'<ul style="padding-left:18px;margin:6px 0 16px">{items}{more}</ul>'

    stats = [(len(digest["finished"]), "выполнено"), (len(digest["created"]), "новых"), (len(digest["in_work"]), "в работе")]
    if digest["logged_minutes"]:
        stats.append((fmt_hours(digest["logged_minutes"]), "работы"))
    body = '<table role="presentation" style="width:100%;border-collapse:collapse;margin:0 0 18px"><tr>' + "".join(
        f'<td style="padding:10px;background:#f3f8f6;border-radius:8px;text-align:center"><div style="font-size:22px;font-weight:800">{value}</div>'
        f'<div style="font-size:12px;color:#5c716c">{label}</div></td>' for value, label in stats) + "</tr></table>"
    text = [title, ""]
    if digest["waiting"]:
        body += "<h2 style=\"font-size:16px;margin:0 0 4px;color:#a3620a\">Ждём от вас</h2>"
        body += '<ul style="padding-left:18px;margin:6px 0 16px">' + "".join(
            f'<li style="margin:0 0 6px"><a href="{public_base()}/#ticket/{w["ticket_id"]}" style="color:#137b69">№{w["ticket_id"]}</a> '
            f'{html.escape(w["action"])} — {html.escape(w["title"])}</li>' for w in digest["waiting"]) + "</ul>"
        text += ["Ждём от вас:"] + [f"  №{w['ticket_id']} {w['action']} — {w['title']}" for w in digest["waiting"]] + [""]
    if digest["finished"]:
        body += '<h2 style="font-size:16px;margin:0 0 4px">Что сделано</h2>' + ticket_list(digest["finished"])
        text += ["Что сделано:"] + [f"  №{t['id']} {t['title']}" for t in digest["finished"]] + [""]
    if digest["in_work"]:
        body += '<h2 style="font-size:16px;margin:0 0 4px">Что в работе</h2>' + ticket_list(
            digest["in_work"], lambda t: f' <span style="color:#6b7f7a">· {status_names.get(t["status"], t["status"])}</span>')
        text += ["Что в работе:"] + [f"  №{t['id']} {t['title']} · {status_names.get(t['status'], t['status'])}" for t in digest["in_work"]] + [""]
    if digest["meetings"]:
        body += '<h2 style="font-size:16px;margin:0 0 4px">Итоги встреч</h2>'
        for meeting in digest["meetings"]:
            label = f"{SERVICE_KIND_NAMES.get(meeting['kind'], 'встреча').capitalize()} {format_ru_date(meeting['occurred_at']).removesuffix(' г.')}"
            body += quote_html(label, meeting["client_summary"] or "")
            text += [label + ":", meeting["client_summary"] or "", ""]
    if not (digest["waiting"] or digest["finished"] or digest["in_work"] or digest["meetings"]):
        body += "<p>В этом месяце обращений не было. Если появится задача, создайте заявку в кабинете.</p>"
    text += [f"Открыть кабинет: {public_base()}/"]
    subject = f"Сводка по заявкам за {MONTHS_NOMINATIVE[digest['month'] - 1]}"
    return subject, "\n".join(text), email_layout(title, body, [("Открыть кабинет", public_base() + "/")],
                                                  "Сводка приходит раз в месяц. Отключить её можно в профиле кабинета.")


def digest_has_activity(digest):
    return bool(digest["finished"] or digest["created"] or digest["in_work"] or digest["waiting"] or digest["meetings"])


def run_digests(at: datetime | None = None, force: bool = False) -> int:
    """Первого числа рассылает клиентам сводку за прошедший месяц. Каждому — один раз за период."""
    if not mailer.enabled():
        return 0
    local = (at or datetime.now(timezone.utc)).astimezone(local_tz())
    if not force and (local.day != env_int("DIGEST_DAY", 1) or local.hour < 9):
        return 0
    previous = (local.replace(day=1) - timedelta(days=1))
    period = f"{previous.year}-{previous.month:02d}"
    sent = 0
    with db() as conn:
        customers = conn.execute("SELECT * FROM users WHERE role='customer' AND active=1").fetchall()
    for user in customers:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prefs = email_preferences(conn, user)
            if not prefs["digest"] or conn.execute("SELECT 1 FROM digest_log WHERE user_id=? AND period=?",
                                                   (user["id"], period)).fetchone():
                continue
            conn.execute("INSERT INTO digest_log VALUES(?,?,?)", (user["id"], period, now()))
            digest = build_digest(conn, user, period)
            if not digest_has_activity(digest):
                continue
            subject, text, html_body = render_digest(user, digest)
            for address in [user["email"], *prefs["digest_emails"]]:
                queue_email(conn, user["id"], address, "digest", subject, text, html_body)
            sent += 1
    return sent


@app.get("/api/digest/preview")
def digest_preview(period: str | None = None, desk_session: str | None = Cookie(default=None)):
    user = current_user(desk_session)
    if user["role"] != "customer":
        raise HTTPException(403, "Сводка готовится для заказчиков")
    local = datetime.now(local_tz())
    with db() as conn:
        digest = build_digest(conn, user, period or f"{local.year}-{local.month:02d}")
    return HTMLResponse(render_digest(user, digest)[2], headers={"Cache-Control": "no-store"})


# ---------- Фоновые задачи ----------

def run_background_tick(last: dict):
    stamp = time.time()
    if mailer.enabled():
        deliver_emails()
    if stamp - last.get("reminders", 0) >= 600:
        last["reminders"] = stamp
        start, _, end = os.getenv("REMINDER_HOURS", "9-20").partition("-")
        if env_int("REMINDER_FIRST_HOURS", 48) >= 0 and int(start or 9) <= datetime.now(local_tz()).hour < int(end or 20):
            run_reminders()
    if stamp - last.get("digest", 0) >= 1800:
        last["digest"] = stamp
        run_digests()
    if mailer.imap_configured() and stamp - last.get("imap", 0) >= env_int("IMAP_POLL_SECONDS", 60):
        last["imap"] = stamp
        mailer.fetch_unseen(process_inbound_email)


async def background_jobs():
    last = {}
    while True:
        try:
            await asyncio.to_thread(run_background_tick, last)
        except Exception as exc:
            print(f"background job failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        await asyncio.sleep(20)


@app.on_event("startup")
async def start_background_jobs():
    # Отключается BACKGROUND_JOBS=0, например если задачи запускаются отдельным процессом.
    if os.getenv("BACKGROUND_JOBS", "1").strip() != "0":
        app.state.background_jobs = asyncio.create_task(background_jobs())


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
