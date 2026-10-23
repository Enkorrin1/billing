"""Internal contractor payouts; independent of customer invoices and balances."""

from datetime import date, datetime, timedelta, timezone
from html import escape
import hashlib
from typing import Literal

from fastapi import Cookie, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field


def work_today():
    return datetime.now(timezone(timedelta(hours=3))).date()


# Stable IDs across independent source tables: work stays compatible with existing IDs.
# Estimates use negative odd IDs, service entries negative even IDs.
# Task time uses a separate high positive range (SQLite source IDs remain unchanged).
SOURCE_SQL = '''
    SELECT e.id,e.id AS source_id,'work' AS source_kind,e.author_id,e.ticket_id,
        t.title AS ticket_title,COALESCE(e.work_date,date(e.created_at,'+3 hours')) AS work_date,
        e.minutes,e.note
    FROM time_entries e JOIN tickets t ON t.id=e.ticket_id
    UNION ALL
    SELECT -(e.id*2-1),e.id,'assessment',e.author_id,e.ticket_id,t.title,
        date(e.created_at,'+3 hours'),e.assessment_minutes,
        'Оценка заявки, версия ' || e.version || CASE WHEN e.note!='' THEN ': ' || e.note ELSE '' END
    FROM estimates e JOIN tickets t ON t.id=e.ticket_id
    UNION ALL
    SELECT -(s.id*2),s.id,'service',s.author_id,s.ticket_id,
        COALESCE(t.title,'Общий чат · ' || u.name),date(s.occurred_at,'+3 hours'),s.minutes,
        CASE s.kind WHEN 'chat' THEN 'Переписка' WHEN 'call' THEN 'Созвон'
            WHEN 'meeting' THEN 'Встреча' ELSE 'Сопровождение' END || ': ' || s.note
    FROM service_entries s LEFT JOIN tickets t ON t.id=s.ticket_id JOIN users u ON u.id=s.customer_id
    WHERE s.is_billable=1
    UNION ALL
    SELECT 1000000000000+e.id,e.id,'task',e.author_id,NULL,
        'Задача #' || t.id || ' · ' || t.title,e.work_date,e.minutes,e.note
    FROM task_time_entries e JOIN team_tasks t ON t.id=e.task_id
    WHERE e.ticket_time_entry_id IS NULL
'''


def source_entry(conn, entry_id):
    return conn.execute(f'SELECT * FROM ({SOURCE_SQL}) WHERE id=?', (entry_id,)).fetchone()


def protect_service_deletion(conn, source_id):
    entry_id = -source_id * 2
    if conn.execute('SELECT 1 FROM payroll_act_items WHERE entry_id=?', (entry_id,)).fetchone():
        raise HTTPException(409, 'Сопровождение уже включено в акт исполнителя')
    if conn.execute('SELECT 1 FROM payroll_audit WHERE entry_id=?', (entry_id,)).fetchone():
        raise HTTPException(409, 'По сопровождению уже есть решение администратора; запись сохраняется в учёте выплат')


def init_schema(conn):
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(time_entries)')}
    if 'work_date' not in columns:
        conn.execute('ALTER TABLE time_entries ADD COLUMN work_date TEXT')
    conn.execute("UPDATE time_entries SET work_date=date(created_at, '+3 hours') WHERE work_date IS NULL")
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS payroll_rates (
        id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES users(id),
        cents_per_hour INTEGER NOT NULL CHECK(cents_per_hour>0),
        created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS payroll_rates_employee ON payroll_rates(employee_id,id);
    CREATE TABLE IF NOT EXISTS payroll_reviews (
        entry_id INTEGER PRIMARY KEY REFERENCES time_entries(id),
        state TEXT NOT NULL CHECK(state IN ('approved','rejected')),
        rate_id INTEGER REFERENCES payroll_rates(id), amount_cents INTEGER,
        reason TEXT NOT NULL DEFAULT '', reviewed_by INTEGER NOT NULL REFERENCES users(id),
        reviewed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payroll_audit (
        id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES time_entries(id),
        action TEXT NOT NULL, reason TEXT NOT NULL, actor_id INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payroll_acts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL REFERENCES users(id),
        employee_name TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
        total_minutes INTEGER NOT NULL, total_cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
        created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        paid_at TEXT, paid_by INTEGER REFERENCES users(id), request_id TEXT NOT NULL,
        request_hash TEXT NOT NULL, UNIQUE(created_by,request_id)
    );
    CREATE TABLE IF NOT EXISTS payroll_act_items (
        entry_id INTEGER PRIMARY KEY REFERENCES time_entries(id),
        act_id INTEGER NOT NULL REFERENCES payroll_acts(id),
        ticket_id INTEGER NOT NULL, ticket_title TEXT NOT NULL, work_date TEXT NOT NULL,
        note TEXT NOT NULL, minutes INTEGER NOT NULL, cents_per_hour INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS payroll_items_act ON payroll_act_items(act_id);
    CREATE TABLE IF NOT EXISTS payroll_sources (
        id INTEGER PRIMARY KEY, source_kind TEXT NOT NULL CHECK(source_kind IN ('work','assessment','service','task')),
        source_id INTEGER NOT NULL, UNIQUE(source_kind,source_id)
    );
    ''')
    # Widen the source registry while keeping its stable IDs and existing foreign keys.
    source_schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='payroll_sources'").fetchone()[0]
    if "'task'" not in source_schema:
        conn.commit()
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(source_schema.replace('payroll_sources', 'payroll_sources_upgrade', 1).replace("'assessment','service'", "'assessment','service','task'"))
            conn.execute('INSERT INTO payroll_sources_upgrade SELECT * FROM payroll_sources')
            conn.execute('DROP TABLE payroll_sources')
            conn.execute('ALTER TABLE payroll_sources_upgrade RENAME TO payroll_sources')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute('PRAGMA foreign_keys=ON')
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Payroll source migration failed foreign-key validation')
    # Upgrade the initial work-only schema without changing issued acts or decisions.
    if any(r['table'] == 'time_entries' for r in conn.execute('PRAGMA foreign_key_list(payroll_reviews)')):
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("INSERT OR IGNORE INTO payroll_sources SELECT id,'work',id FROM time_entries")
        for table in ('payroll_reviews', 'payroll_audit', 'payroll_act_items'):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            sql = sql.replace(table, table + '_upgrade', 1).replace('REFERENCES time_entries(id)', 'REFERENCES payroll_sources(id)')
            if table == 'payroll_act_items':
                sql = sql.replace('ticket_id INTEGER NOT NULL', 'ticket_id INTEGER')
            conn.execute(sql)
            conn.execute(f'INSERT INTO {table}_upgrade SELECT * FROM {table}')
            conn.execute(f'DROP TABLE {table}')
            conn.execute(f'ALTER TABLE {table}_upgrade RENAME TO {table}')
        conn.execute('CREATE INDEX payroll_items_act ON payroll_act_items(act_id)')
    item_columns = {r['name'] for r in conn.execute('PRAGMA table_info(payroll_act_items)')}
    if 'source_kind' not in item_columns:
        conn.execute("ALTER TABLE payroll_act_items ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'work'")
        conn.execute('ALTER TABLE payroll_act_items ADD COLUMN source_id INTEGER')
        conn.execute('UPDATE payroll_act_items SET source_id=entry_id')


class RateInput(BaseModel):
    cents_per_hour: int = Field(strict=True, gt=0, le=100_000_000)


class ReviewInput(BaseModel):
    action: Literal['approve', 'reject', 'reset']
    reason: str = Field(default='', max_length=2000)


class ActInput(BaseModel):
    employee_id: int
    period_start: date
    period_end: date
    entry_ids: list[int] = Field(min_length=1, max_length=10000)
    expected_total_cents: int = Field(strict=True, ge=0)
    request_id: str = Field(min_length=8, max_length=100)


def check_period(start, end):
    if start > end:
        raise HTTPException(422, 'Начало периода должно быть не позже окончания')


def entries(conn, employee_id, start, end):
    return [dict(r) for r in conn.execute(f'''
        SELECT e.*,
            u.name AS employee_name,COALESCE(r.state,'pending') AS state,r.reason,
            r.amount_cents,pr.cents_per_hour,r.reviewed_at,a.act_id
        FROM ({SOURCE_SQL}) e JOIN users u ON u.id=e.author_id
        LEFT JOIN payroll_reviews r ON r.entry_id=e.id
        LEFT JOIN payroll_rates pr ON pr.id=r.rate_id
        LEFT JOIN payroll_act_items a ON a.entry_id=e.id
        WHERE (? IS NULL OR e.author_id=?) AND e.work_date>=? AND e.work_date<=?
        ORDER BY e.work_date DESC,e.id DESC
        ''', (employee_id, employee_id, start.isoformat(), end.isoformat()))]


def install_routes(app, domain):
    def staff(token, admin=False):
        user = domain.current_user(token)
        if user['role'] == 'customer' or (admin and user['role'] != 'admin'):
            raise HTTPException(403, 'Это действие доступно только администратору' if admin else 'Доступ только для команды')
        return user

    def get_act(conn, act_id, user):
        row = conn.execute('SELECT * FROM payroll_acts WHERE id=?', (act_id,)).fetchone()
        if not row or (user['role'] != 'admin' and row['employee_id'] != user['id']):
            raise HTTPException(404, 'Акт не найден')
        result = dict(row)
        result['number'] = f'ИСП-{row["id"]:06d}'
        result['items'] = [dict(r) for r in conn.execute('SELECT * FROM payroll_act_items WHERE act_id=? ORDER BY work_date,entry_id', (act_id,))]
        return result

    @app.get('/payroll.js')
    def script():
        return FileResponse(domain.ROOT / 'web' / 'payroll.js', media_type='text/javascript', headers=domain.NO_CACHE)

    @app.get('/api/payroll')
    def overview(period_start: date, period_end: date, employee_id: int | None = None,
                 desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session)
        check_period(period_start, period_end)
        if user['role'] != 'admin':
            employee_id = user['id']
        with domain.db() as conn:
            people = [dict(r) for r in conn.execute('''SELECT u.id,u.name,u.active,
                (SELECT cents_per_hour FROM payroll_rates WHERE employee_id=u.id ORDER BY id DESC LIMIT 1) AS cents_per_hour
                FROM users u WHERE u.role!='customer' AND (? OR u.id=?) ORDER BY u.name''', (user['role'] == 'admin', user['id']))]
            rows = entries(conn, employee_id, period_start, period_end)
            acts = [dict(r) for r in conn.execute('''SELECT * FROM payroll_acts
                WHERE (? IS NULL OR employee_id=?) AND period_start<=? AND period_end>=? ORDER BY id DESC''',
                (employee_id, employee_id, period_end.isoformat(), period_start.isoformat()))]
        return {'employees': people, 'entries': rows, 'acts': acts, 'timezone': 'UTC+03:00'}

    @app.post('/api/payroll/rates/{employee_id}')
    def set_rate(employee_id: int, data: RateInput, desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session, admin=True)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            person = conn.execute("SELECT id FROM users WHERE id=? AND role!='customer'", (employee_id,)).fetchone()
            if not person:
                raise HTTPException(404, 'Исполнитель не найден')
            conn.execute('INSERT INTO payroll_rates(employee_id,cents_per_hour,created_by,created_at) VALUES(?,?,?,?)',
                         (employee_id, data.cents_per_hour, user['id'], domain.now()))
        return {'ok': True}

    @app.post('/api/payroll/entries/{entry_id}/review')
    def review(entry_id: int, data: ReviewInput, desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session, admin=True)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            entry = source_entry(conn, entry_id)
            if not entry:
                raise HTTPException(404, 'Запись времени не найдена')
            if conn.execute('SELECT 1 FROM payroll_act_items WHERE entry_id=?', (entry_id,)).fetchone():
                raise HTTPException(409, 'Запись уже включена в акт и не может быть изменена')
            conn.execute('INSERT OR IGNORE INTO payroll_sources(id,source_kind,source_id) VALUES(?,?,?)',
                         (entry_id, entry['source_kind'], entry['source_id']))
            existing = conn.execute('SELECT state FROM payroll_reviews WHERE entry_id=?', (entry_id,)).fetchone()
            if data.action == 'reset':
                conn.execute('DELETE FROM payroll_reviews WHERE entry_id=?', (entry_id,))
            else:
                state = 'approved' if data.action == 'approve' else 'rejected'
                if existing:
                    if existing['state'] == state:
                        return {'ok': True}
                    raise HTTPException(409, 'Сначала верните запись на проверку')
                rate_id = amount = None
                if data.action == 'approve':
                    rate = conn.execute('SELECT * FROM payroll_rates WHERE employee_id=? ORDER BY id DESC LIMIT 1', (entry['author_id'],)).fetchone()
                    if not rate:
                        raise HTTPException(409, 'Сначала задайте ставку исполнителю')
                    rate_id = rate['id']
                    # Round each line to cents, half up, without floating point.
                    amount = (entry['minutes'] * rate['cents_per_hour'] + 30) // 60
                elif not data.reason.strip():
                    raise HTTPException(422, 'Укажите причину отклонения')
                conn.execute('''INSERT INTO payroll_reviews(entry_id,state,rate_id,amount_cents,reason,reviewed_by,reviewed_at)
                    VALUES(?,?,?,?,?,?,?)''', (entry_id, state, rate_id, amount, data.reason.strip(), user['id'], domain.now()))
            conn.execute('INSERT INTO payroll_audit(entry_id,action,reason,actor_id,created_at) VALUES(?,?,?,?,?)',
                         (entry_id, data.action, data.reason.strip(), user['id'], domain.now()))
        return {'ok': True}

    @app.post('/api/payroll/acts', status_code=201)
    def create_act(data: ActInput, desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session, admin=True)
        check_period(data.period_start, data.period_end)
        fingerprint = hashlib.sha256(data.model_dump_json(exclude={'request_id'}).encode()).hexdigest()
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = conn.execute('SELECT id,request_hash FROM payroll_acts WHERE created_by=? AND request_id=?', (user['id'], data.request_id)).fetchone()
            if prior:
                if prior['request_hash'] != fingerprint:
                    raise HTTPException(409, 'Ключ запроса уже использован для другого акта')
                return get_act(conn, prior['id'], user)
            selected = set(data.entry_ids)
            rows = [r for r in entries(conn, data.employee_id, data.period_start, data.period_end) if r['id'] in selected and r['state'] == 'approved' and not r['act_id']]
            total = sum(r['amount_cents'] for r in rows)
            if len(rows) != len(data.entry_ids) or total != data.expected_total_cents:
                raise HTTPException(409, 'Состав или сумма изменились. Обновите предварительный расчёт')
            person = conn.execute('SELECT name FROM users WHERE id=?', (data.employee_id,)).fetchone()
            cursor = conn.execute('''INSERT INTO payroll_acts(employee_id,employee_name,period_start,period_end,total_minutes,total_cents,created_by,created_at,request_id,request_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (data.employee_id, person['name'], data.period_start.isoformat(), data.period_end.isoformat(),
                sum(r['minutes'] for r in rows), total, user['id'], domain.now(), data.request_id, fingerprint))
            act_id = cursor.lastrowid
            conn.executemany('''INSERT INTO payroll_act_items(entry_id,act_id,ticket_id,ticket_title,work_date,note,minutes,cents_per_hour,amount_cents,source_kind,source_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', [(r['id'],act_id,r['ticket_id'],r['ticket_title'],r['work_date'],r['note'],r['minutes'],r['cents_per_hour'],r['amount_cents'],r['source_kind'],r['source_id']) for r in rows])
            return get_act(conn, act_id, user)

    @app.get('/api/payroll/acts/{act_id}')
    def detail(act_id: int, desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session)
        with domain.db() as conn:
            return get_act(conn, act_id, user)

    @app.post('/api/payroll/acts/{act_id}/paid')
    def mark_paid(act_id: int, desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session, admin=True)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            get_act(conn, act_id, user)
            conn.execute('UPDATE payroll_acts SET paid_at=?,paid_by=? WHERE id=? AND paid_at IS NULL', (domain.now(), user['id'], act_id))
            return get_act(conn, act_id, user)

    @app.get('/api/payroll/acts/{act_id}/print', response_class=HTMLResponse)
    def print_act(act_id: int, desk_session: str | None = Cookie(default=None)):
        user = staff(desk_session)
        with domain.db() as conn:
            act = get_act(conn, act_id, user)
        money = lambda cents: f'{cents // 100}.{cents % 100:02d}'
        rows = ''.join(f'<tr><td>{escape(r["work_date"])}</td><td>{"#"+str(r["ticket_id"])+" " if r["ticket_id"] else ""}{escape(r["ticket_title"])}<br>{escape(r["note"])}</td><td>{r["minutes"]}</td><td>{money(r["cents_per_hour"])}</td><td>{money(r["amount_cents"])}</td></tr>' for r in act['items'])
        return HTMLResponse(f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Акт {act['number']}</title><style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#172033}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ccd2db}}td:nth-child(n+3){{white-space:nowrap}}.hint{{color:#586174}}@media print{{.hint{{display:none}}body{{margin:0}}}}</style>
        <h1>Акт выполненных работ {act['number']}</h1><p class="hint">Предварительная форма. Договорные реквизиты и окончательное оформление будут добавлены по вашему шаблону. Печать / сохранение в PDF: Ctrl+P.</p>
        <p>Исполнитель: <strong>{escape(act['employee_name'])}</strong></p><p>Период: {act['period_start']} — {act['period_end']} включительно</p>
        <table><thead><tr><th>Дата работы</th><th>Выполненная работа</th><th>Минуты</th><th>USD/час</th><th>USD</th></tr></thead><tbody>{rows}</tbody></table>
        <h2>Итого: {act['total_minutes']} мин. · {money(act['total_cents'])} USD</h2><p>Сумма рассчитана по каждой записи с округлением до цента.</p>
        <p>Заказчик ____________________ &nbsp; Исполнитель ____________________</p></html>''', headers={'Cache-Control': 'no-store'})
