"""Team responsibilities, scoped operations and auditable handovers.

Functions describe a person's work; only explicit permissions grant access.
The web service remains the domain adapter for authentication and notifications.
"""
import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_FUNCTIONS = {
    "programmer": ("Программист", "Производство"),
    "integrator": ("Интегратор", "Производство"),
    "devops": ("DevOps", "Производство"),
    "analyst": ("Аналитик", "Производство"),
    "designer": ("Дизайнер", "Производство"),
    "qa": ("Тестировщик", "Производство"),
    "sales": ("Продажи", "Клиенты"),
    "account": ("Ведение клиентов", "Клиенты"),
    "call_host": ("Проведение созвонов", "Клиенты"),
    "support": ("Поддержка", "Клиенты"),
    "project_manager": ("Управление проектами", "Управление"),
    "team_lead": ("Руководство командой", "Управление"),
    "finance": ("Финансовый учёт", "Финансы"),
}
PERMISSIONS = {
    "tasks": "Создание и ведение задач",
    "meetings": "Организация и проведение встреч",
    "sales": "Ведение сделок и передача в работу",
    "clients": "Назначение команды клиента",
    "billing_read": "Биллинг всей компании: просмотр",
    "billing_manage": "Биллинг всей компании: финансовые операции",
}
ACCESS_PRESETS = {
    "specialist": {"name": "Исполнитель", "permissions": ["tasks", "meetings"]},
    "sales": {"name": "Продажи", "permissions": ["sales", "meetings"]},
    "account": {"name": "Ведение клиентов", "permissions": ["tasks", "meetings", "sales"]},
    "coordinator": {"name": "Координатор", "permissions": ["tasks","meetings","sales","clients"]},
    "finance": {"name": "Финансовый специалист", "permissions": ["billing_read","billing_manage"]},
    "viewer": {"name": "Наблюдатель", "permissions": []},
}
CLIENT_ROLES = {
    "sales": "Продажи", "account": "Ведение клиента", "project_manager": "Руководитель проекта",
    "technical": "Технический куратор", "specialist": "Участник команды",
}
DEAL_STAGES = {"new": "Новое обращение", "qualified": "Квалификация", "meeting": "Встреча",
               "proposal": "Предложение", "decision": "Решение", "won": "Выиграна", "lost": "Потеряна"}
TASK_STATES = {"new": "Новая", "working": "В работе", "review": "На проверке", "done": "Выполнена", "cancelled": "Отменена"}
MEETING_STATES = {"planned": "Запланирована", "held": "Проведена", "cancelled": "Отменена", "missed": "Не состоялась"}


def init_schema(conn):
    if 'is_billable' not in {r['name'] for r in conn.execute('PRAGMA table_info(service_entries)')}:
        conn.execute('ALTER TABLE service_entries ADD COLUMN is_billable INTEGER NOT NULL DEFAULT 1')
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS team_functions (
        code TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS staff_functions (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        function_code TEXT NOT NULL REFERENCES team_functions(code), PRIMARY KEY(user_id,function_code)
    );
    CREATE TABLE IF NOT EXISTS staff_settings (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        department TEXT NOT NULL DEFAULT '', manager_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        capacity_minutes INTEGER NOT NULL DEFAULT 2400, availability TEXT NOT NULL DEFAULT 'available',
        permissions TEXT NOT NULL DEFAULT '["tasks","meetings"]', scope TEXT NOT NULL DEFAULT 'assigned',
        responsibilities TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS client_team (
        customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, responsibility TEXT NOT NULL,
        PRIMARY KEY(customer_id,user_id,responsibility)
    );
    CREATE TABLE IF NOT EXISTS ticket_participants (
        ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        participation TEXT NOT NULL CHECK(participation IN ('executor','reviewer','observer')),
        PRIMARY KEY(ticket_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS team_meetings (
        id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL, title TEXT NOT NULL, agenda TEXT NOT NULL DEFAULT '',
        starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, url TEXT NOT NULL DEFAULT '',
        organizer_id INTEGER REFERENCES users(id) ON DELETE SET NULL, host_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'planned', internal_notes TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '', next_steps TEXT NOT NULL DEFAULT '', shared_at TEXT,
        summary_entry_id INTEGER REFERENCES service_entries(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS meeting_participants (
        meeting_id INTEGER NOT NULL REFERENCES team_meetings(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(meeting_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS team_deals (
        id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL, title TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'new', next_action TEXT NOT NULL, due_at TEXT,
        proposal TEXT NOT NULL DEFAULT '', loss_reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS team_tasks (
        id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
        meeting_id INTEGER REFERENCES team_meetings(id) ON DELETE SET NULL,
        deal_id INTEGER UNIQUE REFERENCES team_deals(id) ON DELETE SET NULL,
        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        reviewer_id INTEGER REFERENCES users(id) ON DELETE SET NULL, due_at TEXT,
        planned_minutes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new',
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS task_participants (
        task_id INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(task_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS team_audit (
        id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        entity TEXT NOT NULL, entity_id INTEGER NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS team_notifications (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        entity TEXT NOT NULL, entity_id INTEGER NOT NULL, created_at TEXT NOT NULL, read_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_client_team_user ON client_team(user_id,customer_id);
    CREATE INDEX IF NOT EXISTS idx_team_tasks_owner ON team_tasks(owner_id,status);
    CREATE INDEX IF NOT EXISTS idx_team_meetings_host ON team_meetings(host_id,starts_at);
    CREATE INDEX IF NOT EXISTS idx_team_deals_owner ON team_deals(owner_id,stage);
    """)
    import task_tracker
    task_tracker.init_schema(conn)
    for code, (name, category) in DEFAULT_FUNCTIONS.items():
        conn.execute("INSERT OR IGNORE INTO team_functions(code,name,category) VALUES(?,?,?)", (code,name,category))
    # Run once per existing employee. Subsequent restarts must not resurrect cleared functions.
    people = conn.execute("SELECT id,team_role,created_at FROM users WHERE role IN ('employee','admin') AND id NOT IN (SELECT user_id FROM staff_settings)").fetchall()
    for person in people:
        conn.execute("INSERT INTO staff_settings(user_id,updated_at) VALUES(?,?)", (person['id'],person['created_at']))
        if person['team_role'] in DEFAULT_FUNCTIONS:
            conn.execute("INSERT OR IGNORE INTO staff_functions VALUES(?,?)", (person['id'],person['team_role']))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class FunctionInput(Input):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    name: str = Field(min_length=2, max_length=80)
    category: str = Field(min_length=2, max_length=80)


class StaffSettings(Input):
    functions: list[str] = Field(default_factory=list, max_length=30)
    job_title: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=100)
    manager_id: int | None = None
    capacity_minutes: int = Field(default=2400, ge=0, le=10080)
    availability: Literal["available", "vacation", "sick", "away"] = "available"
    permissions: list[Literal["tasks", "meetings", "sales", "clients", "billing_read", "billing_manage"]] = Field(default_factory=lambda:["tasks","meetings"])
    scope: Literal["assigned", "department", "all"] = "assigned"
    responsibilities: str = Field(default="", max_length=2000)
    version: str | None = None
    access_level: Literal['employee','manager'] = 'employee'


class ClientMember(Input):
    user_id: int
    responsibility: Literal["sales", "account", "project_manager", "technical", "specialist"]


class ClientTeamInput(Input):
    members: list[ClientMember] = Field(max_length=50)


class TicketMember(Input):
    user_id: int
    participation: Literal["executor", "reviewer", "observer"]


class TicketTeamInput(Input):
    members: list[TicketMember] = Field(max_length=30)


class WorkInput(Input):
    customer_id: int
    title: str = Field(min_length=3, max_length=200)
    owner_id: int | None = None
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("Укажите часовой пояс даты")
        return value


class TaskInput(WorkInput):
    customer_id: int | None = None
    ticket_id: int | None = None
    meeting_id: int | None = None
    reviewer_id: int | None = None
    participants: list[int] = Field(default_factory=list, max_length=30)
    description: str = Field(default="", max_length=5000)
    planned_minutes: int = Field(default=0, ge=0, le=60000)
    status: Literal["new", "working", "review", "done", "cancelled"] = "new"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    blocked_reason: str = Field(default="",max_length=2000)
    request_id: str | None = Field(default=None,min_length=8,max_length=100)
    version: int | None = None


class DealInput(WorkInput):
    stage: Literal["new", "qualified", "meeting", "proposal", "decision", "won", "lost"] = "new"
    next_action: str = Field(min_length=3, max_length=1000)
    proposal: str = Field(default="", max_length=5000)
    loss_reason: str = Field(default="", max_length=1000)
    version: int | None = None

    @model_validator(mode="after")
    def outcome(self):
        if self.stage == 'lost' and len(self.loss_reason) < 3:
            raise ValueError("Укажите причину потери сделки")
        if self.stage == 'won' and len(self.proposal) < 3:
            raise ValueError("Сохраните согласованный объём и договорённости")
        return self


class MeetingInput(Input):
    customer_id: int
    ticket_id: int | None = None
    title: str = Field(min_length=3, max_length=200)
    agenda: str = Field(min_length=3, max_length=3000)
    starts_at: datetime
    duration_minutes: int = Field(ge=5, le=480)
    url: str = Field(default="", max_length=1000)
    host_id: int
    participants: list[int] = Field(default_factory=list, max_length=30)
    status: Literal["planned", "held", "cancelled", "missed"] = "planned"
    internal_notes: str = Field(default="", max_length=5000)
    summary: str = Field(default="", max_length=3000)
    next_steps: str = Field(default="", max_length=2000)
    version: int | None = None

    @field_validator("starts_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Укажите часовой пояс встречи")
        return value

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        if value and not re.match(r"^https?://[^\s]+$", value):
            raise ValueError("Ссылка должна начинаться с https:// или http://")
        return value


class HandoffInput(Input):
    owner_id: int
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=5000)
    due_at: datetime | None = None
    planned_minutes: int = Field(default=0, ge=0, le=60000)

    _aware = field_validator("due_at")(WorkInput.aware.__func__)


def privileged(user):
    return user['role'] == 'admin' or bool(user['is_manager'])


def settings(conn, uid):
    row = conn.execute("SELECT * FROM staff_settings WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return {"permissions":["tasks","meetings"], "scope":"assigned", "department":"", "capacity_minutes":2400,
                "availability":"available", "responsibilities":"", "manager_id":None, "updated_at":None}
    result = dict(row)
    result['permissions'] = json.loads(result['permissions'])
    return result


def function_codes(conn, uid):
    return [r[0] for r in conn.execute("SELECT function_code FROM staff_functions WHERE user_id=? ORDER BY function_code", (uid,))]


def ticket_participation(conn, tid, uid):
    row = conn.execute("SELECT participation FROM ticket_participants WHERE ticket_id=? AND user_id=?", (tid,uid)).fetchone()
    return row[0] if row else None


def has_permission(conn, user, permission):
    return privileged(user) or permission in settings(conn, user['id'])['permissions']


def client_visible(conn, user, cid):
    if cid is None:
        return False
    if privileged(user):
        return True
    own = conn.execute("""SELECT 1 FROM client_team WHERE customer_id=? AND user_id=?
        UNION SELECT 1 FROM tickets WHERE customer_id=? AND assignee_id=?
        UNION SELECT 1 FROM chats WHERE assignee_id=? AND
        ((organization_id IS NULL AND customer_id=?) OR organization_id IN
         (SELECT organization_id FROM organization_members WHERE user_id=?))""",
        (cid,user['id'],cid,user['id'],user['id'],cid,cid)).fetchone()
    if own:
        return True
    profile = settings(conn,user['id'])
    if profile['scope'] == 'all':
        return True
    return profile['scope'] == 'department' and bool(profile['department']) and bool(conn.execute("""SELECT 1 FROM client_team c
        JOIN staff_settings s ON s.user_id=c.user_id JOIN users u ON u.id=c.user_id
        WHERE c.customer_id=? AND s.department=? AND u.active=1""", (cid,profile['department'])).fetchone())


def require_client(conn, user, cid, permission=None):
    if not conn.execute("SELECT 1 FROM users WHERE id=? AND role='customer' AND active=1", (cid,)).fetchone():
        raise HTTPException(404, "Клиент не найден")
    if not client_visible(conn,user,cid):
        raise HTTPException(404, "Клиент не найден")
    if permission and not has_permission(conn,user,permission):
        raise HTTPException(403, "Нет права на это действие")


def active_staff(conn, uid):
    if uid is not None and not conn.execute("SELECT 1 FROM users WHERE id=? AND role IN ('employee','admin') AND active=1", (uid,)).fetchone():
        raise HTTPException(422, "Выберите активного сотрудника")


def audit(conn, domain, user, entity, eid, action, details):
    conn.execute("INSERT INTO team_audit(actor_id,entity,entity_id,action,details,created_at) VALUES(?,?,?,?,?,?)",
                 (user['id'],entity,eid,action,json.dumps(details,ensure_ascii=False),domain.now()))
    # No record contents in this event: each browser reloads through the scoped API.
    domain.realtime_bus.broadcast([r[0] for r in conn.execute("SELECT id FROM users WHERE active=1 AND role IN ('employee','admin')")],
                                  {'type':'team_updated'})


def notify_assignment(conn,domain,actor,kind,eid,recipients):
    if kind=='tasks':
        from task_tracker import quiet_notify
        quiet_notify(conn,domain,actor,eid,'assignment',recipients)
        return
    for uid in set(recipients)-{None,actor['id']}:
        conn.execute('INSERT INTO team_notifications(user_id,entity,entity_id,created_at) VALUES(?,?,?,?)',
                     (uid,kind,eid,domain.now()))


def person_data(conn, row, private=False):
    data = {k: row[k] for k in ('id','name','role','is_manager','active')}
    data['functions'] = function_codes(conn,row['id'])
    profile = conn.execute("SELECT job_title,bio,avatar_updated_at FROM staff_profiles WHERE user_id=?", (row['id'],)).fetchone()
    data['job_title'] = profile['job_title'] if profile else ''
    data['avatar_url'] = f"/api/staff/{row['id']}/avatar?v={profile['avatar_updated_at']}" if profile and profile['avatar_updated_at'] else None
    config = settings(conn,row['id'])
    for k in ('department','manager_id','capacity_minutes','availability','responsibilities','updated_at'):
        data[k] = config[k]
    if private:
        data.update(email=row['email'],permissions=config['permissions'],scope=config['scope'])
    return data


def handover(conn, domain, actor, uid, replacement):
    """Called inside the legacy deactivation transaction: preserve authorship, transfer live work."""
    if replacement:
        for r in conn.execute("SELECT customer_id,responsibility FROM client_team WHERE user_id=?", (uid,)).fetchall():
            conn.execute("INSERT OR IGNORE INTO client_team VALUES(?,?,?)", (r['customer_id'],replacement,r['responsibility']))
    conn.execute("DELETE FROM client_team WHERE user_id=?", (uid,))
    counts = {}
    for table, col, live in [('team_tasks','owner_id',"status NOT IN ('done','cancelled')"),
                              ('team_tasks','reviewer_id',"status NOT IN ('done','cancelled')"),
                              ('team_deals','owner_id',"stage NOT IN ('won','lost')"),
                              ('team_meetings','host_id',"status='planned'"),
                              ('team_meetings','organizer_id',"status='planned'")]:
        changed = conn.execute(f"UPDATE {table} SET {col}=?,updated_at=?,version=version+1 WHERE {col}=? AND {live}", (replacement,domain.now(),uid)).rowcount
        counts[f'{table}.{col}'] = changed
    # Memberships are access grants, not historical authorship.
    for table, object_col in [('ticket_participants','ticket_id'),('task_participants','task_id'),('meeting_participants','meeting_id')]:
        if replacement:
            columns = f"{object_col},user_id" + (",participation" if table=='ticket_participants' else '')
            select = f"{object_col},?" + (",participation" if table=='ticket_participants' else '')
            conn.execute(f"INSERT OR IGNORE INTO {table}({columns}) SELECT {select} FROM {table} WHERE user_id=?", (replacement,uid))
        conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
    audit(conn,domain,actor,'staff',uid,'handover',{'replacement_id':replacement,'transferred':counts})
    return counts


def install_routes(app, domain):
    router = APIRouter(prefix='/api/team')

    def user_for(token):
        user = domain.current_user(token)
        domain.require_staff(user)
        return user

    def entity_visible(conn, user, kind, row):
        if privileged(user):
            return True
        if kind == 'deals':
            return has_permission(conn,user,'sales') and (row['owner_id']==user['id'] or client_visible(conn,user,row['customer_id']))
        if kind == 'tasks':
            involved = user['id'] in (row['owner_id'],row['reviewer_id']) or conn.execute(
                "SELECT 1 FROM task_participants WHERE task_id=? AND user_id=?", (row['id'],user['id'])).fetchone()
        else:
            involved = user['id'] in (row['host_id'],row['organizer_id']) or conn.execute(
                "SELECT 1 FROM meeting_participants WHERE meeting_id=? AND user_id=?", (row['id'],user['id'])).fetchone()
        if kind=='tasks' and row['customer_id'] is None:
            profile=settings(conn,user['id'])
            if row['created_by']==user['id'] or profile['scope']=='all':return True
            if profile['scope']=='department' and profile['department']:
                owner=settings(conn,row['owner_id'])
                if owner['department']==profile['department']:return True
        return bool(involved) or client_visible(conn,user,row['customer_id'])

    def get_entity(conn,user,kind,eid,write=False):
        row = conn.execute(f"SELECT * FROM team_{kind} WHERE id=?", (eid,)).fetchone()
        if not row or not entity_visible(conn,user,kind,row):
            raise HTTPException(404,"Запись не найдена")
        permission = {'tasks':'tasks','meetings':'meetings','deals':'sales'}[kind]
        if write and not has_permission(conn,user,permission):
            raise HTTPException(403,"Нет права изменять запись")
        if write and not privileged(user) and not client_visible(conn,user,row['customer_id']):
            responsible = user['id'] in ((row['owner_id'],row['reviewer_id'],row['created_by'] if row['customer_id'] is None else None) if kind=='tasks' else (row['host_id'],row['organizer_id']) if kind=='meetings' else (row['owner_id'],))
            if not responsible:
                raise HTTPException(403,"Участник может читать запись; изменять её может ответственный")
        return row

    def enriched(conn,kind,row,user):
        item = dict(row)
        item['customer_name'] = conn.execute("SELECT name FROM users WHERE id=?", (row['customer_id'],)).fetchone()[0] if row['customer_id'] else 'Внутренняя задача'
        permission = {'tasks':'tasks','meetings':'meetings','deals':'sales'}[kind]
        item['can_edit'] = has_permission(conn,user,permission) and (privileged(user) or client_visible(conn,user,row['customer_id']) or user['id'] in ((row['owner_id'],row['reviewer_id'],row['created_by'] if row['customer_id'] is None else None) if kind=='tasks' else (row['host_id'],row['organizer_id']) if kind=='meetings' else (row['owner_id'],)))
        if kind != 'deals':
            table,col = ('task_participants','task_id') if kind=='tasks' else ('meeting_participants','meeting_id')
            item['participants'] = [r[0] for r in conn.execute(f"SELECT user_id FROM {table} WHERE {col}=?", (row['id'],))]
        if kind=='tasks':
            item['checklist_total']=conn.execute('SELECT COUNT(*) FROM task_checklist WHERE task_id=?',(row['id'],)).fetchone()[0]
            item['checklist_done']=conn.execute('SELECT COUNT(*) FROM task_checklist WHERE task_id=? AND checked=1',(row['id'],)).fetchone()[0]
            item['comment_count']=conn.execute('SELECT COUNT(*) FROM task_comments WHERE task_id=?',(row['id'],)).fetchone()[0]
            item['file_count']=conn.execute('SELECT COUNT(*) FROM task_files WHERE task_id=? AND deleted_at IS NULL',(row['id'],)).fetchone()[0]
        if kind=='deals':
            task = conn.execute("SELECT id FROM team_tasks WHERE deal_id=?", (row['id'],)).fetchone()
            item['handoff_task_id'] = task[0] if task else None
        return item

    @router.get('')
    def workspace(desk_session: str | None = Cookie(default=None)):
        user = user_for(desk_session)
        with domain.db() as conn:
            people = [person_data(conn,r,privileged(user) or r['id']==user['id']) for r in conn.execute("SELECT * FROM users WHERE role IN ('employee','admin') ORDER BY active DESC,name") if r['active'] or privileged(user) or r['id']==user['id']]
            clients = []
            for row in conn.execute("SELECT id,name,email FROM users WHERE role='customer' AND active=1 ORDER BY name"):
                if client_visible(conn,user,row['id']):
                    item = dict(row)
                    item['members'] = [dict(r) for r in conn.execute("SELECT user_id,responsibility FROM client_team WHERE customer_id=?", (row['id'],))]
                    clients.append(item)
            records = {}
            for kind in ('tasks','meetings','deals'):
                records[kind] = [enriched(conn,kind,r,user) for r in conn.execute(f"SELECT * FROM team_{kind} ORDER BY updated_at DESC,id DESC") if entity_visible(conn,user,kind,r)]
            events=[]
            for event in conn.execute('SELECT * FROM team_notifications WHERE user_id=? ORDER BY id DESC LIMIT 50',(user['id'],)):
                record=next((r for r in records[event['entity']] if r['id']==event['entity_id']),None)
                if record: events.append({**dict(event),'title':record['title'],'customer_name':record['customer_name']})
            for person in people:
                uid = person['id']
                active_tasks = [r for r in records['tasks'] if r['status'] not in ('done','cancelled') and (r['owner_id']==uid or uid in r['participants'])]
                week_start = datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
                from datetime import timedelta
                week_start -= timedelta(days=week_start.weekday())
                week_end = week_start + timedelta(days=7)
                calls = [r for r in records['meetings'] if r['status']=='planned' and (r['host_id']==uid or uid in r['participants']) and week_start <= datetime.fromisoformat(r['starts_at']) < week_end]
                task_minutes = sum(r['planned_minutes'] for r in active_tasks if r['due_at'] and datetime.fromisoformat(r['due_at']) < week_end)
                person['workload'] = {'tasks':len(active_tasks),'planned_minutes':sum(r['planned_minutes'] for r in active_tasks),
                    'week_minutes':task_minutes+sum(r['duration_minutes'] for r in calls),'week_meetings':len(calls),
                    'overdue':sum(bool(r['due_at']) and datetime.fromisoformat(r['due_at'])<datetime.now(timezone.utc) for r in active_tasks),
                    'clients':sum(any(m['user_id']==uid for m in c['members']) for c in clients)}
            return {'people':people,'clients':clients,**records,'events':events,'functions':[dict(r) for r in conn.execute("SELECT * FROM team_functions ORDER BY category,name")],
                    'permissions':PERMISSIONS,'presets':ACCESS_PRESETS,'client_roles':CLIENT_ROLES,'deal_stages':DEAL_STAGES,
                    'task_states':TASK_STATES,'meeting_states':MEETING_STATES,'can_admin':user['role']=='admin',
                    'can_dispatch':privileged(user),'my_permissions':list(PERMISSIONS) if privileged(user) else settings(conn,user['id'])['permissions']}

    @router.post('/functions',status_code=201)
    def add_function(data: FunctionInput, desk_session: str | None = Cookie(default=None)):
        user=user_for(desk_session); domain.require_admin(user)
        with domain.db() as conn:
            if conn.execute("SELECT 1 FROM team_functions WHERE code=? OR name=?", (data.code,data.name)).fetchone():
                raise HTTPException(409,"Такая функция уже существует")
            conn.execute("INSERT INTO team_functions(code,name,category) VALUES(?,?,?)", (data.code,data.name,data.category))
            audit(conn,domain,user,'function',0,'create',data.model_dump())
        return data.model_dump()

    @router.post('/notifications/{eid}/read')
    def read_notification(eid:int,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            event=conn.execute('SELECT * FROM team_notifications WHERE id=? AND user_id=?',(eid,user['id'])).fetchone()
            if not event:raise HTTPException(404,'Уведомление не найдено')
            get_entity(conn,user,event['entity'],event['entity_id'])
            conn.execute('UPDATE team_notifications SET read_at=COALESCE(read_at,?) WHERE id=?',(domain.now(),eid))
        return {'ok':True}

    @router.put('/staff/{uid}')
    def update_person(uid:int,data:StaffSettings,desk_session: str | None = Cookie(default=None)):
        user=user_for(desk_session); domain.require_admin(user)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            target=conn.execute("SELECT * FROM users WHERE id=? AND role IN ('employee','admin')", (uid,)).fetchone()
            if not target: raise HTTPException(404,'Сотрудник не найден')
            current=settings(conn,uid)
            if current['updated_at'] != data.version:
                raise HTTPException(409,'Карточка уже изменена. Обновите данные перед сохранением')
            active_staff(conn,data.manager_id)
            if data.scope=='department' and not data.department:
                raise HTTPException(422,'Для доступа к подразделению укажите подразделение')
            seen={uid}; manager=data.manager_id
            while manager:
                if manager in seen: raise HTTPException(422,'Подчинение не должно образовывать цикл')
                seen.add(manager); manager=settings(conn,manager)['manager_id']
            codes=set(data.functions)
            if any(not conn.execute('SELECT 1 FROM team_functions WHERE code=? AND active=1',(code,)).fetchone() for code in codes):
                raise HTTPException(422,'Неизвестная функция команды')
            conn.execute('DELETE FROM staff_functions WHERE user_id=?',(uid,))
            conn.executemany('INSERT INTO staff_functions VALUES(?,?)',[(uid,c) for c in sorted(codes)])
            stamp=domain.now()
            conn.execute("""INSERT INTO staff_settings(user_id,department,manager_id,capacity_minutes,availability,permissions,scope,responsibilities,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET department=excluded.department,manager_id=excluded.manager_id,
                capacity_minutes=excluded.capacity_minutes,availability=excluded.availability,permissions=excluded.permissions,
                scope=excluded.scope,responsibilities=excluded.responsibilities,updated_at=excluded.updated_at""",
                (uid,data.department,data.manager_id,data.capacity_minutes,data.availability,json.dumps(sorted(set(data.permissions))),data.scope,data.responsibilities,stamp))
            # Legacy clients still receive one compatible primary specialty.
            primary=target['team_role'] if target['team_role'] in codes else next((c for c in ('programmer','integrator','devops') if c in codes),None)
            conn.execute('UPDATE users SET team_role=? WHERE id=?',(primary,uid))
            if target['role'] != 'admin':
                conn.execute('UPDATE users SET is_manager=? WHERE id=?',(int(data.access_level=='manager'),uid))
            conn.execute("""INSERT INTO staff_profiles(user_id,job_title,bio,updated_at) VALUES(?,?,'',?)
                ON CONFLICT(user_id) DO UPDATE SET job_title=excluded.job_title,updated_at=excluded.updated_at""",(uid,data.job_title,stamp))
            audit(conn,domain,user,'staff',uid,'update',data.model_dump(exclude={'version'}))
            return person_data(conn,conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(),True)

    @router.patch('/me/availability')
    def update_my_availability(data: dict, desk_session: str | None = Cookie(default=None)):
        user = user_for(desk_session)
        if user['role'] not in ('employee', 'admin'):
            raise HTTPException(403, 'Только для сотрудников')
        availability = data.get('availability')
        if availability not in ('available', 'vacation', 'sick', 'away'):
            raise HTTPException(422, 'Недопустимый статус доступности')
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            stamp = domain.now()
            conn.execute("""INSERT INTO staff_settings(user_id,availability,updated_at)
                VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET availability=excluded.availability,updated_at=excluded.updated_at""",
                (user['id'], availability, stamp))
            audit(conn, domain, user, 'staff', user['id'], 'availability', {'availability': availability})
            return {'ok': True, 'availability': availability}

    @router.put('/clients/{cid}')
    def update_client_team(cid:int,data:ClientTeamInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE'); require_client(conn,user,cid,'clients')
            seen=set(); singles=set()
            for m in data.members:
                active_staff(conn,m.user_id)
                if (m.user_id,m.responsibility) in seen or (m.responsibility!='specialist' and m.responsibility in singles):
                    raise HTTPException(422,'У каждой основной обязанности один ответственный; участники не должны повторяться')
                seen.add((m.user_id,m.responsibility)); singles.add(m.responsibility)
            previous=[dict(r) for r in conn.execute('SELECT user_id,responsibility FROM client_team WHERE customer_id=?',(cid,))]
            conn.execute('DELETE FROM client_team WHERE customer_id=?',(cid,))
            conn.executemany('INSERT INTO client_team VALUES(?,?,?)',[(cid,m.user_id,m.responsibility) for m in data.members])
            audit(conn,domain,user,'client',cid,'assign',{'before':previous,'after':data.model_dump()['members']})
        return {'ok':True}

    @router.get('/tickets/{tid}/participants')
    def ticket_members(tid:int,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            domain.ticket_for(conn,tid,user,write=False)
            return [dict(r) for r in conn.execute('SELECT user_id,participation FROM ticket_participants WHERE ticket_id=?',(tid,))]

    @router.put('/tickets/{tid}/participants')
    def update_ticket_members(tid:int,data:TicketTeamInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session); domain.require_dispatcher(user)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE'); domain.ticket_for(conn,tid,user)
            if len({m.user_id for m in data.members})!=len(data.members): raise HTTPException(422,'Участники не должны повторяться')
            for m in data.members: active_staff(conn,m.user_id)
            conn.execute('DELETE FROM ticket_participants WHERE ticket_id=?',(tid,))
            conn.executemany('INSERT INTO ticket_participants VALUES(?,?,?)',[(tid,m.user_id,m.participation) for m in data.members])
            audit(conn,domain,user,'ticket',tid,'participants',data.model_dump())
        return {'ok':True}

    def save_work(conn,user,kind,data,eid=None):
        if not conn.in_transaction:conn.execute('BEGIN IMMEDIATE')
        old=get_entity(conn,user,kind,eid,True) if eid else None
        permission={'tasks':'tasks','meetings':'meetings','deals':'sales'}[kind]
        if kind=='tasks' and not old and data.request_id:
            previous=conn.execute('SELECT * FROM team_tasks WHERE created_by=? AND request_id=?',(user['id'],data.request_id)).fetchone()
            if previous:return enriched(conn,kind,get_entity(conn,user,kind,previous['id']),user)
        if kind=='tasks' and data.customer_id is None:
            if not has_permission(conn,user,'tasks'):raise HTTPException(403,'Нет права создавать задачи')
            if data.ticket_id or data.meeting_id:raise HTTPException(422,'Для связи с заявкой или встречей укажите клиента')
        elif not old or data.customer_id!=old['customer_id']:
            # A host can turn this meeting's agreements into tasks without receiving all client records.
            linked = get_entity(conn,user,'meetings',data.meeting_id) if kind=='tasks' and data.meeting_id else (domain.ticket_for(conn,data.ticket_id,user,write=False) if kind=='tasks' and data.ticket_id else None)
            if linked and linked['customer_id']==data.customer_id and has_permission(conn,user,permission):
                pass
            else:
                require_client(conn,user,data.customer_id,permission)
        if old and (data.customer_id!=old['customer_id'] or (kind=='tasks' and data.meeting_id!=old['meeting_id'])):
            raise HTTPException(422,'Клиента и исходную встречу существующей записи менять нельзя')
        if old and data.version!=old['version']: raise HTTPException(409,'Запись уже изменена. Обновите страницу')
        for key in ('owner_id','reviewer_id','host_id'):
            if hasattr(data,key): active_staff(conn,getattr(data,key))
        for uid in getattr(data,'participants',[]): active_staff(conn,uid)
        if getattr(data,'ticket_id',None):
            ticket=domain.ticket_for(conn,data.ticket_id,user,write=False)
            if ticket['customer_id']!=data.customer_id: raise HTTPException(422,'Заявка относится к другому клиенту')
        if getattr(data,'meeting_id',None):
            meeting=get_entity(conn,user,'meetings',data.meeting_id)
            if meeting['customer_id']!=data.customer_id: raise HTTPException(422,'Встреча относится к другому клиенту')
        if kind=='tasks':
            if data.status in ('done','cancelled') and data.blocked_reason:raise HTTPException(422,'Сначала снимите блокировку задачи')
            if data.reviewer_id is not None and data.reviewer_id==data.owner_id:
                raise HTTPException(422,'Исполнитель и проверяющий должны быть разными сотрудниками')
            if old and data.status=='done' and conn.execute('SELECT 1 FROM task_checklist WHERE task_id=? AND checked=0',(eid,)).fetchone():
                raise HTTPException(409,'Выполните все пункты чек-листа перед завершением')
            if data.status not in ('done','cancelled') and data.owner_id is None: raise HTTPException(422,'Назначьте ответственного за задачу')
            if data.status=='review' and data.reviewer_id is None: raise HTTPException(422,'Назначьте проверяющего')
            if data.status=='done' and data.reviewer_id and not privileged(user) and user['id']!=data.reviewer_id:
                raise HTTPException(403,'Результат принимает назначенный проверяющий')
            if old and old['reviewer_id'] and data.status=='done' and not privileged(user) and user['id']!=old['reviewer_id']:
                raise HTTPException(403,'Нельзя снять проверяющего, чтобы принять собственную работу')
            initial_reviewer = old and old['reviewer_id'] is None and data.reviewer_id is not None and old['owner_id']==user['id'] and old['status'] in ('new','working')
            if old and data.reviewer_id!=old['reviewer_id'] and not privileged(user) and not has_permission(conn,user,'clients') and not initial_reviewer:
                raise HTTPException(403,'Проверяющего меняет координатор или руководитель')
        if kind=='deals' and data.stage not in ('won','lost') and data.owner_id is None:
            raise HTTPException(422,'Назначьте продавца')
        if kind=='deals' and old and data.stage!='won' and conn.execute('SELECT 1 FROM team_tasks WHERE deal_id=?',(eid,)).fetchone():
            raise HTTPException(409,'Сделка уже передана в работу; сохраните итог продажи')
        if kind=='meetings' and old and old['shared_at'] and (data.summary!=old['summary'] or data.next_steps!=old['next_steps'] or data.status!='held'):
            raise HTTPException(409,'Опубликованные итоги сохраняются в истории и не редактируются')
        if kind=='meetings' and data.status=='held' and data.starts_at.astimezone(timezone.utc)>datetime.now(timezone.utc):
            raise HTTPException(422,'Будущую встречу нельзя отметить проведённой')
        values=data.model_dump(exclude={'participants','version'})
        if old:values.pop('request_id',None)
        for key,value in list(values.items()):
            if isinstance(value,datetime): values[key]=value.astimezone(timezone.utc).isoformat()
        stamp=domain.now(); values['updated_at']=stamp
        if not old:
            values['created_at']=stamp
            if kind=='tasks': values['created_by']=user['id']
            if kind=='meetings': values['organizer_id']=user['id']
            keys=list(values)
            eid=conn.execute(f"INSERT INTO team_{kind}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(values.values())).lastrowid
        else:
            conn.execute(f"UPDATE team_{kind} SET {','.join(k+'=?' for k in values)},version=version+1 WHERE id=?",(*values.values(),eid))
        if kind!='deals':
            table,col=('task_participants','task_id') if kind=='tasks' else ('meeting_participants','meeting_id')
            previous_participants={r[0] for r in conn.execute(f'SELECT user_id FROM {table} WHERE {col}=?',(eid,))}
            conn.execute(f'DELETE FROM {table} WHERE {col}=?',(eid,))
            conn.executemany(f'INSERT INTO {table} VALUES(?,?)',[(eid,uid) for uid in set(data.participants)])
        role_keys=('owner_id','reviewer_id') if kind=='tasks' else ('host_id',) if kind=='meetings' else ('owner_id',)
        recipients={conn.execute(f'SELECT {key} FROM team_{kind} WHERE id=?',(eid,)).fetchone()[0] for key in role_keys
                    if not old or getattr(data,key,None)!=old[key]}
        if kind!='deals':
            recipients.update(set(data.participants)-previous_participants)
        notify_assignment(conn,domain,user,kind,eid,recipients)
        if kind=='tasks':
            from task_tracker import notify_task_change
            notify_task_change(conn,domain,user,old,conn.execute('SELECT * FROM team_tasks WHERE id=?',(eid,)).fetchone(),entity_visible)
        audit(conn,domain,user,kind,eid,'update' if old else 'create',{'before':dict(old) if old else None,'after':values})
        return enriched(conn,kind,conn.execute(f'SELECT * FROM team_{kind} WHERE id=?',(eid,)).fetchone(),user)

    @router.post('/tasks',status_code=201)
    def create_task(data:TaskInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn: return save_work(conn,user,'tasks',data)

    @router.put('/tasks/{eid}')
    def update_task(eid:int,data:TaskInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn: return save_work(conn,user,'tasks',data,eid)

    @router.post('/meetings',status_code=201)
    def create_meeting(data:MeetingInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn: return save_work(conn,user,'meetings',data)

    @router.put('/meetings/{eid}')
    def update_meeting(eid:int,data:MeetingInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn: return save_work(conn,user,'meetings',data,eid)

    @router.post('/meetings/{eid}/publish')
    def publish_meeting(eid:int,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE'); row=get_entity(conn,user,'meetings',eid,True)
            if row['shared_at']: return {'ok':True,'shared_at':row['shared_at']}
            if row['status']!='held' or len(row['summary'].strip())<3:
                raise HTTPException(422,'Сначала отметьте встречу проведённой и заполните итоги')
            # Separate zero-charge service record. Publication never creates a financial operation.
            ticket=conn.execute('SELECT * FROM tickets WHERE id=?',(row['ticket_id'],)).fetchone() if row['ticket_id'] else None
            entry=conn.execute("""INSERT INTO service_entries(customer_id,organization_id,ticket_id,author_id,kind,minutes,note,occurred_at,created_at,request_id,client_summary,client_next_steps,is_billable)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)""",(row['customer_id'],ticket['organization_id'] if ticket else None,row['ticket_id'],user['id'],'meeting',row['duration_minutes'],row['internal_notes'] or row['title'],row['starts_at'],domain.now(),f'team-meeting-{eid}',row['summary'],row['next_steps'])).lastrowid
            # Publication record is deliberately non-billable; exclude it from financial selections.
            domain.share_meeting_summary(conn,entry)
            stamp=domain.now()
            conn.execute('UPDATE team_meetings SET shared_at=?,summary_entry_id=?,version=version+1,updated_at=? WHERE id=?',(stamp,entry,stamp,eid))
            audit(conn,domain,user,'meetings',eid,'publish',{'summary':row['summary'],'next_steps':row['next_steps']})
            return {'ok':True,'shared_at':stamp}

    @router.post('/deals',status_code=201)
    def create_deal(data:DealInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn: return save_work(conn,user,'deals',data)

    @router.put('/deals/{eid}')
    def update_deal(eid:int,data:DealInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn: return save_work(conn,user,'deals',data,eid)

    @router.post('/deals/{eid}/handoff')
    def handoff(eid:int,data:HandoffInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE'); row=get_entity(conn,user,'deals',eid,True)
            if row['stage']!='won': raise HTTPException(409,'Передать в работу можно выигранную сделку')
            previous=conn.execute('SELECT id FROM team_tasks WHERE deal_id=?',(eid,)).fetchone()
            if previous: return {'task_id':previous['id'],'already_transferred':True}
            active_staff(conn,data.owner_id); stamp=domain.now()
            task=conn.execute("""INSERT INTO team_tasks(customer_id,deal_id,title,description,owner_id,due_at,planned_minutes,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(row['customer_id'],eid,data.title,row['proposal']+'\n\n'+data.description,data.owner_id,data.due_at.astimezone(timezone.utc).isoformat() if data.due_at else None,data.planned_minutes,user['id'],stamp,stamp)).lastrowid
            conn.execute("INSERT OR IGNORE INTO client_team VALUES(?,?,'specialist')",(row['customer_id'],data.owner_id))
            notify_assignment(conn,domain,user,'tasks',task,{data.owner_id})
            audit(conn,domain,user,'deals',eid,'handoff',{'task_id':task,'owner_id':data.owner_id})
            return {'task_id':task,'already_transferred':False}

    @router.get('/audit')
    def history(desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session); domain.require_dispatcher(user)
        with domain.db() as conn:
            return [dict(r) for r in conn.execute("SELECT a.*,u.name AS actor_name FROM team_audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100")]

    app.include_router(router)
    import task_tracker
    task_tracker.install_routes(app,domain,user_for,get_entity,entity_visible,enriched,save_work,TaskInput)
