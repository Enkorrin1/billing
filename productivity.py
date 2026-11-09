"""Team and client productivity: decisions inbox, mentions, saved views, SLA escalation,
weekly timesheet, low-deposit alerts, recurring tickets and duplicate merging."""

from datetime import date, datetime, timedelta, timezone
import calendar
import html
import json
import re
from typing import Literal

from fastapi import Cookie, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


def init_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS saved_views (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, filters TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_saved_views_user ON saved_views(user_id,id);
    CREATE TABLE IF NOT EXISTS sla_escalations (
        ticket_id INTEGER NOT NULL REFERENCES tickets(id), kind TEXT NOT NULL, due_at TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(ticket_id,kind,due_at)
    );
    CREATE TABLE IF NOT EXISTS timesheet_reminders (
        user_id INTEGER NOT NULL REFERENCES users(id), week_start TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(user_id,week_start)
    );
    CREATE TABLE IF NOT EXISTS balance_alerts (
        client_table TEXT NOT NULL, client_id INTEGER NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(client_table,client_id)
    );
    CREATE TABLE IF NOT EXISTS recurring_tickets (
        id INTEGER PRIMARY KEY, created_by INTEGER NOT NULL REFERENCES users(id),
        customer_id INTEGER NOT NULL REFERENCES users(id),
        title TEXT NOT NULL, description TEXT NOT NULL, service_type TEXT NOT NULL DEFAULT 'maintenance',
        priority TEXT NOT NULL DEFAULT 'normal', visibility TEXT NOT NULL DEFAULT 'private',
        frequency TEXT NOT NULL CHECK(frequency IN ('weekly','monthly')), day INTEGER NOT NULL,
        next_run_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        last_ticket_id INTEGER REFERENCES tickets(id), last_error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_recurring_due ON recurring_tickets(active,next_run_at);
    """)


# ---------- Упоминания ----------

NAME_CHAR = re.compile(r"[\wЁё]")


def mentioned_staff(conn, body, author_id):
    """@Имя, @Имя Фамилия или @логин из email. Совпадение — самое длинное, после него не буква."""
    if "@" not in body:
        return set()
    candidates = []
    for person in conn.execute("SELECT id,name,email FROM users WHERE role IN ('employee','admin') AND active=1"):
        names = {person["name"].strip().lower(), person["name"].split()[0].lower() if person["name"].split() else "",
                 person["email"].split("@")[0].lower()}
        candidates += [(name, person["id"]) for name in names if len(name) >= 2]
    candidates.sort(key=lambda item: -len(item[0]))
    found, text = set(), body.lower()
    for match in re.finditer(r"(?<![\w.])@", text):
        rest = text[match.end():]
        for name, person_id in candidates:
            if rest.startswith(name) and not (len(rest) > len(name) and NAME_CHAR.match(rest[len(name)])):
                found.add(person_id)
                break
    found.discard(author_id)
    return found


def notify_mentions(domain, conn, author, ticket_id, body):
    for person_id in mentioned_staff(conn, body, author["id"]):
        person = conn.execute("SELECT * FROM users WHERE id=?", (person_id,)).fetchone()
        try:
            domain.ticket_for(conn, ticket_id, person, write=False)
        except HTTPException:
            continue
        domain.notify(conn, person_id, ticket_id, "mention",
                      f"{author['name']} упомянул(а) вас в заметке по заявке №{ticket_id}: {domain.snippet(body, 140)}")


# ---------- Сроки ----------

def ticket_deadlines(row):
    """Те же сроки, что в очереди работ: ответ до первого ответа, оценка до оценки, сдача до выполнения."""
    items = []
    if row["first_staff_response_at"] is None and row["response_due_at"]:
        items.append(("response", row["response_due_at"], "ответ заказчику"))
    if row["effort_minutes"] is None and row["estimate_due_at"]:
        items.append(("estimate", row["estimate_due_at"], "оценка"))
    if row["delivery_due_at"] and row["status"] not in ("done", "closed"):
        items.append(("delivery", row["delivery_due_at"], "сдача работы"))
    return items


DEADLINE_SQL = """SELECT t.id,t.title,t.status,t.assignee_id,t.response_due_at,t.estimate_due_at,t.delivery_due_at,
    t.first_staff_response_at,
    (SELECT effort_minutes FROM estimates WHERE ticket_id=t.id ORDER BY version DESC LIMIT 1) AS effort_minutes
    FROM tickets t WHERE t.status!='closed'"""


def run_escalations(domain, at=None):
    at = at or datetime.now(timezone.utc)
    soon = timedelta(minutes=domain.env_int("ESCALATION_SOON_MINUTES", 60))
    sent = 0
    with domain.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        dispatchers = domain.dispatcher_ids(conn)
        for row in conn.execute(DEADLINE_SQL).fetchall():
            for kind, due, label in ticket_deadlines(row):
                due_at = datetime.fromisoformat(due)
                overdue = due_at <= at
                if not overdue and due_at - at > soon:
                    continue
                level = f"{kind}:{'overdue' if overdue else 'soon'}"
                if conn.execute("SELECT 1 FROM sla_escalations WHERE ticket_id=? AND kind=? AND due_at=?",
                                (row["id"], level, due)).fetchone():
                    continue
                conn.execute("INSERT INTO sla_escalations VALUES(?,?,?,?)", (row["id"], level, due, at.isoformat()))
                # Давно просроченное до включения эскалации не рассылаем: очередь уже показывает его первым.
                if overdue and at - due_at > timedelta(hours=24):
                    continue
                if overdue:
                    recipients = ({row["assignee_id"]} | dispatchers) - {None}
                    text = f"Просрочена {label} по заявке №{row['id']}: {row['title']}"
                else:
                    recipients = {row["assignee_id"]} - {None} or dispatchers
                    minutes = max(1, int((due_at - at).total_seconds() // 60))
                    text = f"Через {minutes} мин истекает срок: {label} по заявке №{row['id']}"
                for recipient in recipients:
                    domain.notify(conn, recipient, row["id"], "sla_overdue" if overdue else "sla_soon", text)
                sent += 1
    return sent


# ---------- Журнал времени ----------

def week_bounds(day: date):
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def timesheet(domain, conn, user, week_start: date):
    start, end = week_bounds(week_start)
    rows = conn.execute("""SELECT t.id,t.title,t.status,COALESCE(o.name,cp.company_name,c.name) AS customer_name
        FROM tickets t JOIN users c ON c.id=t.customer_id
        LEFT JOIN organizations o ON o.id=t.organization_id LEFT JOIN customer_profiles cp ON cp.user_id=t.customer_id
        WHERE (t.assignee_id=? AND t.status IN ('working','waiting','done'))
           OR t.id IN (SELECT ticket_id FROM time_entries WHERE author_id=? AND work_date BETWEEN ? AND ?)
        ORDER BY t.id DESC""", (user["id"], user["id"], start.isoformat(), end.isoformat())).fetchall()
    result = []
    for row in rows:
        entries = conn.execute("""SELECT work_date,SUM(minutes) AS minutes FROM time_entries
            WHERE ticket_id=? AND author_id=? AND work_date BETWEEN ? AND ? GROUP BY work_date""",
                               (row["id"], user["id"], start.isoformat(), end.isoformat())).fetchall()
        approved = domain.approved_minutes(conn, row["id"])
        result.append({**dict(row), "days": {e["work_date"]: e["minutes"] for e in entries},
                       "remaining_minutes": max(0, approved - domain.actual_minutes(conn, row["id"])),
                       "can_log": row["status"] in ("working", "waiting", "done")})
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    totals = {d: sum(r["days"].get(d, 0) for r in result) for d in days}
    return {"week_start": start.isoformat(), "days": days, "rows": result, "totals": totals,
            "total_minutes": sum(totals.values()), "today": domain.payroll.work_today().isoformat()}


def week_minutes(conn, user_id, start: date):
    return conn.execute("SELECT COALESCE(SUM(minutes),0) FROM time_entries WHERE author_id=? AND work_date BETWEEN ? AND ?",
                        (user_id, start.isoformat(), (start + timedelta(days=6)).isoformat())).fetchone()[0]


def has_active_work(conn, user_id):
    return bool(conn.execute("SELECT 1 FROM tickets WHERE assignee_id=? AND status='working' LIMIT 1", (user_id,)).fetchone())


def run_timesheet_reminders(domain, at=None):
    local = (at or datetime.now(timezone.utc)).astimezone(domain.local_tz())
    if local.weekday() != 4 or local.hour < domain.env_int("TIMESHEET_REMINDER_HOUR", 15):
        return 0
    start, _ = week_bounds(local.date())
    sent = 0
    with domain.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for person in conn.execute("SELECT id FROM users WHERE role IN ('employee','admin') AND active=1").fetchall():
            if conn.execute("SELECT 1 FROM timesheet_reminders WHERE user_id=? AND week_start=?",
                            (person["id"], start.isoformat())).fetchone():
                continue
            if not has_active_work(conn, person["id"]) or week_minutes(conn, person["id"], start):
                continue
            conn.execute("INSERT INTO timesheet_reminders VALUES(?,?,?)", (person["id"], start.isoformat(), domain.now()))
            payload = {"title": "Журнал времени", "body": "За эту неделю время не внесено. Заполните журнал — это займёт минуту.",
                       "url": "/#timesheet", "tag": f"timesheet-{start.isoformat()}"}
            domain.web_push.enqueue(person["id"], payload)
            domain.realtime_bus.publish(person["id"], {"type": "timesheet_reminder"})
            sent += 1
    return sent


# ---------- Депозит ----------

def client_balances(conn):
    for table, key in (("organizations", "id"), ("customer_profiles", "user_id")):
        for row in conn.execute(f"SELECT {key} AS id,deposit_balance_rub,held_rub FROM {table}"):
            yield table, row["id"], row["deposit_balance_rub"] or 0, row["held_rub"] or 0


def balance_recipients(conn, table, client_id):
    if table == "organizations":
        return [r for r in conn.execute("""SELECT u.* FROM organization_members m JOIN users u ON u.id=m.user_id
            WHERE m.organization_id=? AND m.role='owner' AND u.active=1""", (client_id,))]
    if conn.execute("SELECT 1 FROM organization_members WHERE user_id=?", (client_id,)).fetchone():
        return []
    return [r for r in conn.execute("SELECT * FROM users WHERE id=? AND role='customer' AND active=1", (client_id,))]


def rub(value):
    return f"{int(value):,} ₽".replace(",", " ")


def run_balance_alerts(domain):
    if not domain.billing_enabled():
        return 0
    threshold = domain.env_int("LOW_BALANCE_RUB", 10000)
    sent = 0
    with domain.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for table, client_id, deposit, held in list(client_balances(conn)):
            available = deposit - held
            alerted = conn.execute("SELECT 1 FROM balance_alerts WHERE client_table=? AND client_id=?", (table, client_id)).fetchone()
            if available >= threshold or (deposit == 0 and held == 0):
                if alerted:
                    conn.execute("DELETE FROM balance_alerts WHERE client_table=? AND client_id=?", (table, client_id))
                continue
            if alerted:
                continue
            conn.execute("INSERT INTO balance_alerts VALUES(?,?,?)", (table, client_id, domain.now()))
            text = (f"Свободный остаток депозита — {rub(available)}. Пополните депозит, чтобы новые работы "
                    f"согласовывались без остановки.")
            for person in balance_recipients(conn, table, client_id):
                domain.web_push.enqueue(person["id"], {"title": "Депозит заканчивается", "body": text,
                                                        "url": "/#billing", "tag": "low-balance"})
                domain.realtime_bus.publish(person["id"], {"type": "balance_low"})
                if domain.mailer.enabled():
                    url = f"{domain.public_base()}/#billing"
                    domain.queue_email(conn, person["id"], person["email"], "balance_low", "Депозит заканчивается", f"{text}\n\n{url}",
                                       domain.email_layout("Депозит заканчивается", f"<p>{html.escape(text)}</p>",
                                                           [("Пополнить депозит", url)]))
            sent += 1
    return sent


def balance_status(domain, conn, user):
    if user["role"] != "customer" or not domain.billing_enabled():
        return {"visible": False}
    member = conn.execute("SELECT organization_id,role FROM organization_members WHERE user_id=?", (user["id"],)).fetchone()
    if member and member["role"] != "owner":
        return {"visible": False}
    table, client_id = ("organizations", member["organization_id"]) if member else ("customer_profiles", user["id"])
    key = "id" if table == "organizations" else "user_id"
    row = conn.execute(f"SELECT deposit_balance_rub,held_rub FROM {table} WHERE {key}=?", (client_id,)).fetchone()
    if not row:
        return {"visible": False}
    deposit, held = row["deposit_balance_rub"] or 0, row["held_rub"] or 0
    threshold = domain.env_int("LOW_BALANCE_RUB", 10000)
    return {"visible": True, "deposit_rub": deposit, "held_rub": held, "available_rub": deposit - held,
            "threshold_rub": threshold, "low": bool(deposit or held) and deposit - held < threshold}


# ---------- Регулярные заявки ----------

def next_run(frequency, day, after: datetime, tz):
    """Следующий запуск в 09:00 местного времени строго позже `after`."""
    local = after.astimezone(tz)
    if frequency == "weekly":
        candidate = local.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=(day - 1 - local.weekday()) % 7)
        if candidate <= local:
            candidate += timedelta(days=7)
    else:
        year, month = local.year, local.month
        candidate = local.replace(day=min(day, 28), hour=9, minute=0, second=0, microsecond=0)
        if candidate <= local:
            month += 1
            if month == 13:
                year, month = year + 1, 1
            candidate = candidate.replace(year=year, month=month, day=min(day, calendar.monthrange(year, month)[1]))
    return candidate.astimezone(timezone.utc).isoformat()


def recurring_visible(conn, user, row):
    if user["role"] == "admin" or user["is_manager"]:
        return True
    if user["role"] == "customer":
        return row["created_by"] == user["id"] or row["customer_id"] == user["id"]
    return row["created_by"] == user["id"]


def run_recurring(domain, at=None):
    at = at or datetime.now(timezone.utc)
    created = 0
    with domain.db() as conn:
        due = conn.execute("SELECT * FROM recurring_tickets WHERE active=1 AND next_run_at<=?", (at.isoformat(),)).fetchall()
    for plan in due:
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            plan = conn.execute("SELECT * FROM recurring_tickets WHERE id=? AND active=1 AND next_run_at<=?",
                                (plan["id"], at.isoformat())).fetchone()
            if not plan:
                continue
            following = next_run(plan["frequency"], plan["day"], at, domain.local_tz())
            author = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (plan["created_by"],)).fetchone()
            if not author:
                conn.execute("UPDATE recurring_tickets SET active=0,last_error=?,updated_at=? WHERE id=?",
                             ("Автор расписания отключён", domain.now(), plan["id"]))
                continue
            data = domain.TicketCreate(title=plan["title"], description=plan["description"], service_type=plan["service_type"],
                                       priority=plan["priority"], visibility=plan["visibility"],
                                       customer_id=None if author["role"] == "customer" else plan["customer_id"])
            conn.execute("SAVEPOINT recurring")
            try:
                ticket = domain.add_ticket_service(conn, author, data)
                conn.execute("RELEASE recurring")
                conn.execute("UPDATE recurring_tickets SET next_run_at=?,last_ticket_id=?,last_error=NULL,updated_at=? WHERE id=?",
                             (following, ticket["id"], domain.now(), plan["id"]))
                created += 1
            except HTTPException as exc:
                conn.execute("ROLLBACK TO recurring")
                conn.execute("RELEASE recurring")
                conn.execute("UPDATE recurring_tickets SET next_run_at=?,last_error=?,updated_at=? WHERE id=?",
                             (following, str(exc.detail), domain.now(), plan["id"]))
    return created


# ---------- Объединение дублей ----------

def merge_tickets(domain, conn, user, source_id, target_id):
    if not (user["role"] == "admin" or user["is_manager"]):
        raise HTTPException(403, "Объединять заявки может менеджер или администратор")
    if source_id == target_id:
        raise HTTPException(422, "Выберите другую заявку")
    source = domain.ticket_for(conn, source_id, user)
    target = domain.ticket_for(conn, target_id, user)
    if source["customer_id"] != target["customer_id"] and not (
            source["organization_id"] and source["organization_id"] == target["organization_id"]):
        raise HTTPException(422, "Объединять можно только заявки одного клиента")
    if source["status"] == "closed" or target["status"] == "closed":
        raise HTTPException(409, "Закрытые заявки не объединяются")
    if source["act_invoice_id"] or conn.execute("""SELECT 1 FROM estimates WHERE ticket_id=? AND state NOT IN ('rejected')
            UNION SELECT 1 FROM time_entries WHERE ticket_id=? UNION SELECT 1 FROM hour_requests WHERE ticket_id=?""",
                                                 (source_id, source_id, source_id)).fetchone():
        raise HTTPException(409, "У дубля уже есть оценка или учтённое время. Объедините в обратную сторону или закройте дубль вручную")
    stamp = domain.now()
    # request_id уникален в пределах заявки: помечаем перенесённые, чтобы не столкнуться с сообщениями цели.
    conn.execute("""UPDATE messages SET ticket_id=?, request_id=CASE WHEN request_id IS NULL THEN NULL
        ELSE request_id || '-merged-' || ? END WHERE ticket_id=?""", (target_id, source_id, source_id))
    conn.execute("UPDATE attachments SET ticket_id=? WHERE ticket_id=?", (target_id, source_id))
    conn.execute("UPDATE ticket_internal_notes SET ticket_id=? WHERE ticket_id=?", (target_id, source_id))
    link = conn.execute("SELECT id FROM chat_ticket_links WHERE ticket_id=?", (source_id,)).fetchone()
    if link and not conn.execute("SELECT 1 FROM chat_ticket_links WHERE ticket_id=?", (target_id,)).fetchone():
        conn.execute("UPDATE chat_ticket_links SET ticket_id=? WHERE id=?", (target_id, link["id"]))
    conn.execute("INSERT INTO ticket_internal_notes(ticket_id,author_id,body,created_at) VALUES(?,?,?,?)",
                 (target_id, user["id"], f"Присоединена заявка №{source_id} «{source['title']}»: переписка и файлы перенесены.\n\n"
                                         f"Исходное описание:\n{source['description']}", stamp))
    conn.execute("UPDATE tickets SET status='closed',updated_at=? WHERE id=?", (stamp, source_id))
    conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (stamp, target_id))
    conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                 (source_id, user["id"], "merged", source["status"], str(target_id), stamp))
    conn.execute("INSERT INTO ticket_events(ticket_id,actor_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",
                 (target_id, user["id"], "merged_from", None, str(source_id), stamp))
    domain.notify(conn, source["customer_id"], target_id, "merged",
                  f"Заявка №{source_id} объединена с №{target_id} «{target['title']}» — переписка продолжится там")
    if target["assignee_id"] and target["assignee_id"] != user["id"]:
        domain.notify(conn, target["assignee_id"], target_id, "merged", f"К заявке №{target_id} присоединена №{source_id}")
    return {"source_id": source_id, "target_id": target_id}


# ---------- Требует моего решения ----------

def decisions(domain, conn, user):
    manager = user["role"] == "admin" or user["is_manager"]
    items = []

    def add(kind, title, detail, since, ticket_id=None, task_id=None, view=None, tone="normal"):
        items.append({"kind": kind, "title": title, "detail": detail, "since": since, "ticket_id": ticket_id,
                      "task_id": task_id, "view": view, "tone": tone})

    scope = "" if manager else "AND t.assignee_id=:me"
    rows = conn.execute(f"""SELECT t.*, COALESCE(o.name,cp.company_name,c.name) AS customer_name,
        (SELECT author_id FROM messages WHERE ticket_id=t.id ORDER BY id DESC LIMIT 1) AS last_author_id,
        (SELECT created_at FROM messages WHERE ticket_id=t.id ORDER BY id DESC LIMIT 1) AS last_message_at,
        (SELECT effort_minutes FROM estimates WHERE ticket_id=t.id ORDER BY version DESC LIMIT 1) AS effort_minutes
        FROM tickets t JOIN users c ON c.id=t.customer_id
        LEFT JOIN organizations o ON o.id=t.organization_id LEFT JOIN customer_profiles cp ON cp.user_id=t.customer_id
        WHERE t.status!='closed' {scope}""", {"me": user["id"]}).fetchall()
    stamp = domain.now()
    for t in rows:
        label = f"№{t['id']} · {t['customer_name']}"
        estimate = domain.latest_estimate(conn, t["id"])
        if manager and t["assignee_id"] is None:
            add("assign", "Назначьте ответственного", f"{label}: {t['title']}", t["created_at"], t["id"], tone="high")
        if manager and estimate and estimate["state"] == "pending_pm":
            add("pm_estimate", "Проверьте оценку исполнителя и цену", f"{label}: {t['title']}", estimate["created_at"], t["id"], tone="high")
        if t["assignee_id"] == user["id"] and estimate and estimate["state"] == "revision_requested":
            add("revision", "Клиент просит пересмотреть оценку", f"{label}: {t['title']}", estimate["decided_at"] or estimate["created_at"], t["id"], tone="high")
        if t["assignee_id"] == user["id"] and t["last_author_id"] == t["customer_id"]:
            add("reply", "Ответьте клиенту", f"{label}: {t['title']}", t["last_message_at"], t["id"])
        for kind, due, what in ticket_deadlines(t):
            if due < stamp and (t["assignee_id"] == user["id"] or manager):
                add("overdue", f"Просрочено: {what}", f"{label}: {t['title']}", due, t["id"], tone="late")
    if manager:
        for request in conn.execute("""SELECT h.*, t.title FROM hour_requests h JOIN tickets t ON t.id=h.ticket_id
                WHERE h.state='pending_pm' AND t.status!='closed'"""):
            add("pm_hours", "Решите по дополнительным часам", f"№{request['ticket_id']}: {request['title']}",
                request["created_at"], request["ticket_id"], tone="high")
    for task in conn.execute("SELECT id,title,updated_at FROM team_tasks WHERE reviewer_id=? AND status='review'", (user["id"],)):
        add("task_review", "Проверьте результат задачи", f"Задача #{task['id']}: {task['title']}", task["updated_at"], task_id=task["id"])
    for note in conn.execute("""SELECT id,ticket_id,text,created_at FROM notifications
            WHERE user_id=? AND kind='mention' AND read_at IS NULL ORDER BY id DESC LIMIT 20""", (user["id"],)):
        add("mention", "Вас упомянули", note["text"], note["created_at"], note["ticket_id"])
    today = domain.payroll.work_today()
    start, _ = week_bounds(today)
    if today.weekday() >= 4 and has_active_work(conn, user["id"]) and not week_minutes(conn, user["id"], start):
        add("timesheet", "Внесите время за неделю", "За эту неделю время ещё не отмечено", start.isoformat(), view="timesheet")
    order = {"late": 0, "high": 1, "normal": 2}
    return sorted(items, key=lambda item: (order[item["tone"]], item["since"] or ""))


# ---------- API ----------

class SavedViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    filters: dict


class TimesheetEntry(BaseModel):
    ticket_id: int
    work_date: date
    minutes: int = Field(ge=1, le=24 * 60)
    note: str = Field(min_length=3, max_length=2000)
    request_id: str = Field(min_length=8, max_length=100)


class TimesheetIn(BaseModel):
    entries: list[TimesheetEntry] = Field(min_length=1, max_length=100)


class RecurringIn(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=10000)
    customer_id: int | None = None
    service_type: str = Field(default="maintenance", max_length=87, pattern=r"^(development|new_development|integration|support|maintenance|consultation|other|custom:\S[^\r\n]{0,79})$")
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    visibility: Literal["private", "organization"] = "private"
    frequency: Literal["weekly", "monthly"]
    day: int = Field(ge=1, le=31)


class RecurringPatch(BaseModel):
    active: bool


class MergeIn(BaseModel):
    target_id: int


SAVED_VIEW_KEYS = {"filter", "owner", "priorityFilter", "search"}


def install_routes(app, domain):
    def staff_user(token):
        user = domain.current_user(token)
        domain.require_staff(user)
        return user

    @app.get("/productivity.js")
    def script():
        return FileResponse(domain.ROOT / "web" / "productivity.js", media_type="text/javascript", headers=domain.NO_CACHE)

    @app.get("/api/decisions")
    def get_decisions(desk_session: str | None = Cookie(default=None)):
        user = staff_user(desk_session)
        with domain.db() as conn:
            return decisions(domain, conn, user)

    @app.get("/api/saved-views")
    def list_views(desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        with domain.db() as conn:
            return [{**dict(r), "filters": json.loads(r["filters"])} for r in
                    conn.execute("SELECT id,name,filters FROM saved_views WHERE user_id=? ORDER BY id", (user["id"],))]

    @app.post("/api/saved-views", status_code=201)
    def create_view(data: SavedViewIn, desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        filters = {k: str(v)[:200] for k, v in data.filters.items() if k in SAVED_VIEW_KEYS}
        with domain.db() as conn:
            if conn.execute("SELECT COUNT(*) FROM saved_views WHERE user_id=?", (user["id"],)).fetchone()[0] >= 20:
                raise HTTPException(409, "Можно сохранить не больше 20 видов. Удалите ненужный")
            cursor = conn.execute("INSERT INTO saved_views(user_id,name,filters,created_at) VALUES(?,?,?,?)",
                                  (user["id"], data.name.strip(), json.dumps(filters, ensure_ascii=False), domain.now()))
            return {"id": cursor.lastrowid, "name": data.name.strip(), "filters": filters}

    @app.delete("/api/saved-views/{view_id}")
    def delete_view(view_id: int, desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        with domain.db() as conn:
            if not conn.execute("DELETE FROM saved_views WHERE id=? AND user_id=?", (view_id, user["id"])).rowcount:
                raise HTTPException(404, "Вид не найден")
            return {"ok": True}

    @app.get("/api/timesheet")
    def get_timesheet(week_start: date | None = None, desk_session: str | None = Cookie(default=None)):
        user = staff_user(desk_session)
        with domain.db() as conn:
            return timesheet(domain, conn, user, week_start or domain.payroll.work_today())

    @app.post("/api/timesheet")
    def save_timesheet(data: TimesheetIn, desk_session: str | None = Cookie(default=None)):
        user = staff_user(desk_session)
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            saved = []
            for entry in data.entries:
                try:
                    saved.append(domain.add_time_entry_service(conn, user, entry.ticket_id, domain.TimeEntryCreate(
                        minutes=entry.minutes, note=entry.note, request_id=entry.request_id, work_date=entry.work_date)))
                except HTTPException as exc:
                    raise HTTPException(exc.status_code, f"Заявка №{entry.ticket_id}: {exc.detail}")
            return {"saved": len(saved)}

    @app.get("/api/balance-status")
    def get_balance_status(desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        with domain.db() as conn:
            return balance_status(domain, conn, user)

    @app.get("/api/recurring-tickets")
    def list_recurring(desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        with domain.db() as conn:
            rows = conn.execute("""SELECT r.*, c.name AS customer_name FROM recurring_tickets r
                JOIN users c ON c.id=r.customer_id ORDER BY r.active DESC, r.next_run_at""").fetchall()
            return [dict(r) for r in rows if recurring_visible(conn, user, r)]

    @app.post("/api/recurring-tickets", status_code=201)
    def create_recurring(data: RecurringIn, desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        day = min(data.day, 7) if data.frequency == "weekly" else min(data.day, 28)
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if user["role"] == "customer":
                customer_id = user["id"]
                if data.visibility == "organization" and not conn.execute(
                        "SELECT 1 FROM organization_members WHERE user_id=?", (user["id"],)).fetchone():
                    raise HTTPException(422, "Общие заявки доступны участникам компании")
            else:
                if not (user["role"] == "admin" or user["is_manager"]):
                    raise HTTPException(403, "Регулярные заявки для клиентов настраивает менеджер")
                if data.customer_id is None or not conn.execute(
                        "SELECT 1 FROM users WHERE id=? AND role='customer' AND active=1", (data.customer_id,)).fetchone():
                    raise HTTPException(422, "Выберите заказчика")
                customer_id = data.customer_id
            stamp = domain.now()
            first = next_run(data.frequency, day, datetime.now(timezone.utc), domain.local_tz())
            cursor = conn.execute("""INSERT INTO recurring_tickets(created_by,customer_id,title,description,service_type,priority,
                visibility,frequency,day,next_run_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                                  (user["id"], customer_id, data.title.strip(), data.description.strip(), data.service_type,
                                   data.priority, data.visibility, data.frequency, day, first, stamp, stamp))
            return dict(conn.execute("SELECT * FROM recurring_tickets WHERE id=?", (cursor.lastrowid,)).fetchone())

    def own_recurring(conn, user, plan_id):
        row = conn.execute("SELECT * FROM recurring_tickets WHERE id=?", (plan_id,)).fetchone()
        if not row or not recurring_visible(conn, user, row):
            raise HTTPException(404, "Расписание не найдено")
        return row

    @app.patch("/api/recurring-tickets/{plan_id}")
    def toggle_recurring(plan_id: int, data: RecurringPatch, desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        with domain.db() as conn:
            row = own_recurring(conn, user, plan_id)
            following = row["next_run_at"]
            if data.active and not row["active"]:
                following = next_run(row["frequency"], row["day"], datetime.now(timezone.utc), domain.local_tz())
            conn.execute("UPDATE recurring_tickets SET active=?,next_run_at=?,updated_at=? WHERE id=?",
                         (int(data.active), following, domain.now(), plan_id))
            return dict(conn.execute("SELECT * FROM recurring_tickets WHERE id=?", (plan_id,)).fetchone())

    @app.delete("/api/recurring-tickets/{plan_id}")
    def delete_recurring(plan_id: int, desk_session: str | None = Cookie(default=None)):
        user = domain.current_user(desk_session)
        with domain.db() as conn:
            own_recurring(conn, user, plan_id)
            conn.execute("DELETE FROM recurring_tickets WHERE id=?", (plan_id,))
            return {"ok": True}

    @app.post("/api/tickets/{ticket_id}/merge")
    def merge(ticket_id: int, data: MergeIn, desk_session: str | None = Cookie(default=None)):
        user = staff_user(desk_session)
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return merge_tickets(domain, conn, user, ticket_id, data.target_id)


def run_tick(domain, last, stamp):
    if stamp - last.get("escalations", 0) >= 300:
        last["escalations"] = stamp
        run_escalations(domain)
    if stamp - last.get("productivity", 0) >= 600:
        last["productivity"] = stamp
        run_recurring(domain)
        run_balance_alerts(domain)
        run_timesheet_reminders(domain)
