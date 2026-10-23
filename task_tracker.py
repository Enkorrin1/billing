"""Focused task-tracker operations, sharing the team's access and lifecycle rules."""
import hashlib
import json
import re
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Cookie, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field, field_validator
from team_management import Input, WorkInput, audit, has_permission, notify_assignment, privileged


def init_schema(conn):
    columns = list(conn.execute('PRAGMA table_info(team_tasks)'))
    if any(r['name']=='customer_id' and r['notnull'] for r in columns):
        # Rebuild the parent in place, preserving IDs and all referring memberships.
        schema=conn.execute("SELECT sql FROM sqlite_master WHERE name='team_tasks'").fetchone()[0]
        schema=re.sub(r'CREATE TABLE(?: IF NOT EXISTS)? "?team_tasks"?', 'CREATE TABLE team_tasks_nullable',schema,count=1)
        schema=schema.replace('customer_id INTEGER NOT NULL','customer_id INTEGER')
        names=','.join('"'+r['name']+'"' for r in columns)
        conn.executescript(f'''PRAGMA foreign_keys=OFF;
            BEGIN IMMEDIATE;
            {schema};
            INSERT INTO team_tasks_nullable({names}) SELECT {names} FROM team_tasks;
            DROP TABLE team_tasks;
            ALTER TABLE team_tasks_nullable RENAME TO team_tasks;
            COMMIT;
            PRAGMA foreign_keys=ON;''')
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Task migration failed foreign-key validation')
    existing={r['name'] for r in conn.execute('PRAGMA table_info(team_tasks)')}
    for name,decl in {'priority':"TEXT NOT NULL DEFAULT 'normal'",'blocked_reason':"TEXT NOT NULL DEFAULT ''",'request_id':'TEXT'}.items():
        if name not in existing:conn.execute(f'ALTER TABLE team_tasks ADD COLUMN {name} {decl}')
    existing={r['name'] for r in conn.execute('PRAGMA table_info(team_notifications)')}
    if 'event_kind' not in existing:conn.execute("ALTER TABLE team_notifications ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'assignment'")
    conn.executescript('''
    CREATE INDEX IF NOT EXISTS idx_team_tasks_owner ON team_tasks(owner_id,status);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_team_tasks_request ON team_tasks(created_by,request_id);
    CREATE TABLE IF NOT EXISTS task_checklist (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
        body TEXT NOT NULL, checked INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL,
        version INTEGER NOT NULL DEFAULT 1, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS task_comments (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
        author_id INTEGER REFERENCES users(id) ON DELETE SET NULL, body TEXT NOT NULL,
        mentions TEXT NOT NULL DEFAULT '[]', request_id TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(task_id,author_id,request_id)
    );
    CREATE TABLE IF NOT EXISTS task_files (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
        author_id INTEGER REFERENCES users(id) ON DELETE SET NULL, filename TEXT NOT NULL, stored_name TEXT NOT NULL,
        size INTEGER NOT NULL, request_id TEXT NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT,
        UNIQUE(task_id,author_id,request_id)
    );
    CREATE TABLE IF NOT EXISTS task_time_entries (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
        author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        minutes INTEGER NOT NULL CHECK(minutes>0), note TEXT NOT NULL,
        work_date TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT,
        ticket_time_entry_id INTEGER REFERENCES time_entries(id) ON DELETE CASCADE,
        UNIQUE(task_id,author_id,request_id)
    );
    CREATE INDEX IF NOT EXISTS idx_task_time_entries ON task_time_entries(task_id,id);
    CREATE TABLE IF NOT EXISTS task_watches (
        task_id INTEGER NOT NULL REFERENCES team_tasks(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, muted INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(task_id,user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_task_comments ON task_comments(task_id,id);
    CREATE INDEX IF NOT EXISTS idx_task_checklist ON task_checklist(task_id,position,id);
    ''')


def quiet_notify(conn,domain,actor,tid,kind,recipients):
    for uid in set(recipients)-{None,actor['id']}:
        if conn.execute('SELECT 1 FROM task_watches WHERE task_id=? AND user_id=? AND muted=1',(tid,uid)).fetchone():
            continue
        previous=conn.execute("SELECT id FROM team_notifications WHERE user_id=? AND entity='tasks' AND entity_id=? AND event_kind=? AND read_at IS NULL ORDER BY id DESC LIMIT 1",(uid,tid,kind)).fetchone()
        if previous:
            conn.execute('UPDATE team_notifications SET created_at=? WHERE id=?',(domain.now(),previous['id']))
        else:
            conn.execute("INSERT INTO team_notifications(user_id,entity,entity_id,event_kind,created_at) VALUES(?,'tasks',?,?,?)",(uid,tid,kind,domain.now()))


def notify_task_change(conn,domain,actor,old,new,visible):
    if not old:return
    if old['status']!=new['status'] and new['status']=='review':
        quiet_notify(conn,domain,actor,new['id'],'review',{new['reviewer_id']})
    significant=old['due_at']!=new['due_at'] or old['blocked_reason']!=new['blocked_reason'] or (old['status']!=new['status'] and new['status'] in ('done','cancelled'))
    if significant:
        recipients={new['owner_id'],new['reviewer_id'],new['created_by']}
        recipients.update(r[0] for r in conn.execute('SELECT user_id FROM task_participants WHERE task_id=?',(new['id'],)))
        recipients.update(r[0] for r in conn.execute('SELECT user_id FROM task_watches WHERE task_id=? AND muted=0',(new['id'],)))
        recipients={uid for uid in recipients if uid and (person:=conn.execute('SELECT * FROM users WHERE id=? AND active=1',(uid,)).fetchone()) and visible(conn,person,'tasks',new)}
        quiet_notify(conn,domain,actor,new['id'],'change',recipients)


class TaskPatch(Input):
    version:int=Field(ge=1)
    title:str|None=Field(default=None,min_length=3,max_length=200)
    description:str|None=Field(default=None,max_length=5000)
    owner_id:int|None=None
    reviewer_id:int|None=None
    due_at:datetime|None=None
    status:Literal['new','working','review','done','cancelled']|None=None
    priority:Literal['low','normal','high','urgent']|None=None
    blocked_reason:str|None=Field(default=None,max_length=2000)
    participants:list[int]|None=Field(default=None,max_length=30)

    _aware=field_validator('due_at')(WorkInput.aware.__func__)


class ChecklistCreate(Input):
    body:str=Field(min_length=1,max_length=500)


class ChecklistPatch(Input):
    version:int=Field(ge=1)
    checked:bool|None=None
    body:str|None=Field(default=None,min_length=1,max_length=500)


class CommentCreate(Input):
    body:str=Field(min_length=1,max_length=10000)
    request_id:str=Field(min_length=8,max_length=100)
    mention_ids:list[int]=Field(default_factory=list,max_length=30)


class TaskTimeInput(Input):
    minutes:int=Field(strict=True,ge=1,le=100_000)
    summary:str=Field(min_length=3,max_length=2000)
    entry_date:date|None=None
    request_id:str|None=Field(default=None,min_length=8,max_length=100)


class WatchInput(Input):
    muted:bool


def can_log_time(conn,user,row,can_edit):
    if not can_edit or row['status']=='cancelled':return False
    if row['ticket_id']:
        linked=conn.execute('SELECT * FROM tickets WHERE id=?',(row['ticket_id'],)).fetchone()
        return bool(linked and linked['assignee_id']==user['id'] and linked['status'] in ('working','waiting','done'))
    return True


def install_routes(app,domain,user_for,get_entity,entity_visible,enriched,save_work,TaskInput):
    router=APIRouter(prefix='/api/tasks')

    def detail(conn,user,tid):
        row=get_entity(conn,user,'tasks',tid)
        result=enriched(conn,'tasks',row,user)
        result['checklist']=[dict(r) for r in conn.execute('SELECT * FROM task_checklist WHERE task_id=? ORDER BY position,id',(tid,))]
        result['comments']=[{**dict(r),'mentions':json.loads(r['mentions'])} for r in conn.execute('SELECT c.*,u.name AS author_name FROM task_comments c LEFT JOIN users u ON u.id=c.author_id WHERE task_id=? ORDER BY c.id',(tid,))]
        result['files']=[dict(r) for r in conn.execute('SELECT f.id,f.filename,f.size,f.author_id,f.created_at,f.deleted_at,u.name AS author_name FROM task_files f LEFT JOIN users u ON u.id=f.author_id WHERE task_id=? ORDER BY f.id DESC',(tid,))]
        result['history']=[{**dict(r),'details':json.loads(r['details'])} for r in conn.execute("SELECT a.*,u.name AS actor_name FROM team_audit a LEFT JOIN users u ON u.id=a.actor_id WHERE entity='tasks' AND entity_id=? ORDER BY a.id DESC LIMIT 100",(tid,))]
        result['time_entries']=[dict(r) for r in conn.execute('SELECT e.*,u.name AS author_name FROM task_time_entries e JOIN users u ON u.id=e.author_id WHERE e.task_id=? ORDER BY e.id DESC',(tid,))]
        result['can_log_time']=can_log_time(conn,user,row,result.get('can_edit',False))
        result['can_comment']=has_permission(conn,user,'tasks') and row['status']!='cancelled'
        result['mention_candidates']=[{'id':p['id'],'name':p['name']} for p in conn.execute("SELECT * FROM users WHERE active=1 AND role IN ('employee','admin') ORDER BY name") if entity_visible(conn,p,'tasks',row)]
        watch=conn.execute('SELECT muted FROM task_watches WHERE task_id=? AND user_id=?',(tid,user['id'])).fetchone()
        result['muted']=bool(watch and watch[0])
        return result

    def bump(conn,tid):
        conn.execute('UPDATE team_tasks SET version=version+1,updated_at=? WHERE id=?',(domain.now(),tid))

    @router.get('/{tid}')
    def read_task(tid:int,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:return detail(conn,user,tid)

    @router.post('',status_code=201)
    def create_task(data:TaskInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            saved=save_work(conn,user,'tasks',data)
            return detail(conn,user,saved['id'])

    @router.patch('/{tid}')
    def patch_task(tid:int,data:TaskPatch,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE');old=get_entity(conn,user,'tasks',tid,True)
            keys=data.model_fields_set-{'version'}
            if not keys:raise HTTPException(422,'Выберите изменение')
            if any(getattr(data,k) is None for k in keys-{'owner_id','reviewer_id','due_at'}):
                raise HTTPException(422,'Это поле не может быть пустым')
            payload={k:old[k] for k in TaskInput.model_fields if k in old.keys()}
            payload['participants']=[r[0] for r in conn.execute('SELECT user_id FROM task_participants WHERE task_id=?',(tid,))]
            payload.update(data.model_dump(exclude_unset=True))
            saved=save_work(conn,user,'tasks',TaskInput(**payload),tid)
            return detail(conn,user,saved['id'])

    @router.post('/{tid}/time-entries',status_code=201)
    def log_time(tid:int,data:TaskTimeInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task=get_entity(conn,user,'tasks',tid,True)
            if data.request_id:
                existing=conn.execute('SELECT * FROM task_time_entries WHERE task_id=? AND author_id=? AND request_id=?',(tid,user['id'],data.request_id)).fetchone()
                if existing:return dict(existing)
            if task['status']=='cancelled':raise HTTPException(409,'Сначала верните задачу в работу')
            note=data.summary.strip()
            if len(note)<3:raise HTTPException(422,'Опишите выполненную работу')
            work_date=data.entry_date or domain.payroll.work_today()
            if work_date>domain.payroll.work_today():raise HTTPException(422,'Дата фактической работы не может быть в будущем')
            ticket_entry=None
            if task['ticket_id']:
                # Reuse the ticket's permissions and agreed limits in the same transaction.
                entry=domain.add_time_entry_service(conn,user,task['ticket_id'],domain.TimeEntryCreate(minutes=data.minutes,note=note,work_date=work_date,
                    request_id=hashlib.sha256(f'task-{tid}-{data.request_id}'.encode()).hexdigest() if data.request_id else None))
                ticket_entry=entry['id']
            cursor=conn.execute('INSERT INTO task_time_entries(task_id,author_id,minutes,note,work_date,created_at,request_id,ticket_time_entry_id) VALUES(?,?,?,?,?,?,?,?)',
                (tid,user['id'],data.minutes,note,work_date.isoformat(),domain.now(),data.request_id,ticket_entry))
            conn.execute('UPDATE team_tasks SET updated_at=? WHERE id=?',(domain.now(),tid))
            audit(conn,domain,user,'tasks',tid,'time_entry',{'entry_id':cursor.lastrowid,'minutes':data.minutes,'ticket_time_entry_id':ticket_entry})
            return dict(conn.execute('SELECT * FROM task_time_entries WHERE id=?',(cursor.lastrowid,)).fetchone())

    @router.post('/{tid}/checklist',status_code=201)
    def add_checklist(tid:int,data:ChecklistCreate,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE');row=get_entity(conn,user,'tasks',tid,True)
            if row['status'] in ('done','cancelled'):raise HTTPException(409,'Сначала верните задачу в работу')
            if conn.execute('SELECT COUNT(*) FROM task_checklist WHERE task_id=?',(tid,)).fetchone()[0]>=200:raise HTTPException(422,'В чек-листе не больше 200 пунктов')
            pos=conn.execute('SELECT COALESCE(MAX(position),0)+1 FROM task_checklist WHERE task_id=?',(tid,)).fetchone()[0]
            cid=conn.execute('INSERT INTO task_checklist(task_id,body,position,created_by) VALUES(?,?,?,?)',(tid,data.body,pos,user['id'])).lastrowid
            bump(conn,tid);audit(conn,domain,user,'tasks',tid,'checklist_add',{'body':data.body})
            return dict(conn.execute('SELECT * FROM task_checklist WHERE id=?',(cid,)).fetchone())

    @router.patch('/{tid}/checklist/{cid}')
    def update_checklist(tid:int,cid:int,data:ChecklistPatch,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE');task=get_entity(conn,user,'tasks',tid,True)
            if task['status'] in ('done','cancelled'):raise HTTPException(409,'Сначала верните задачу в работу')
            old=conn.execute('SELECT * FROM task_checklist WHERE task_id=? AND id=?',(tid,cid)).fetchone()
            if not old:raise HTTPException(404,'Пункт не найден')
            if data.version!=old['version']:raise HTTPException(409,'Пункт уже изменён. Обновите задачу')
            if not data.model_fields_set-{'version'}:raise HTTPException(422,'Выберите изменение пункта')
            if ('body' in data.model_fields_set and data.body is None) or ('checked' in data.model_fields_set and data.checked is None):raise HTTPException(422,'Укажите значение пункта')
            conn.execute('UPDATE task_checklist SET body=?,checked=?,version=version+1 WHERE id=?',(data.body if data.body is not None else old['body'],data.checked if data.checked is not None else old['checked'],cid))
            bump(conn,tid);audit(conn,domain,user,'tasks',tid,'checklist_update',{'body':data.body or old['body'],'checked':data.checked if data.checked is not None else bool(old['checked'])})
            return detail(conn,user,tid)

    @router.post('/{tid}/comments',status_code=201)
    def add_comment(tid:int,data:CommentCreate,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE');task=get_entity(conn,user,'tasks',tid)
            if not has_permission(conn,user,'tasks') or task['status']=='cancelled':raise HTTPException(403,'Доступ только к чтению обсуждения')
            old=conn.execute('SELECT id FROM task_comments WHERE task_id=? AND author_id=? AND request_id=?',(tid,user['id'],data.request_id)).fetchone()
            if old:return detail(conn,user,tid)
            mentions=set(data.mention_ids)
            for candidate in conn.execute("SELECT * FROM users WHERE active=1 AND role IN ('employee','admin')"):
                if re.search('@'+re.escape(candidate['name'])+r'(?=$|[\s,.;!?])',data.body) and entity_visible(conn,candidate,'tasks',task):mentions.add(candidate['id'])
            for uid in mentions:
                candidate=conn.execute("SELECT * FROM users WHERE id=? AND active=1 AND role IN ('employee','admin')",(uid,)).fetchone()
                if not candidate or not entity_visible(conn,candidate,'tasks',task):raise HTTPException(422,'Упомянутый сотрудник не имеет доступа к задаче')
                if not re.search('@'+re.escape(candidate['name'])+r'(?=$|[\s,.;!?])',data.body):raise HTTPException(422,'Добавьте упоминание сотрудника в текст')
            conn.execute('INSERT INTO task_comments(task_id,author_id,body,mentions,request_id,created_at) VALUES(?,?,?,?,?,?)',(tid,user['id'],data.body,json.dumps(sorted(mentions)),data.request_id,domain.now()))
            quiet_notify(conn,domain,user,tid,'mention',mentions)
            conn.execute('UPDATE team_tasks SET updated_at=? WHERE id=?',(domain.now(),tid))
            audit(conn,domain,user,'tasks',tid,'comment',{'author_id':user['id']})
            return detail(conn,user,tid)

    @router.put('/{tid}/watch')
    def update_watch(tid:int,data:WatchInput,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            get_entity(conn,user,'tasks',tid)
            conn.execute('INSERT INTO task_watches VALUES(?,?,?) ON CONFLICT(task_id,user_id) DO UPDATE SET muted=excluded.muted',(tid,user['id'],data.muted))
            return {'muted':data.muted}

    @router.post('/{tid}/files',status_code=201)
    async def upload_file(tid:int,file:UploadFile=File(...),request_id:str=Form(...),desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        if not 8<=len(request_id)<=100:raise HTTPException(422,'Некорректный идентификатор загрузки')
        filename=Path((file.filename or '').replace('\\','/')).name
        if not filename or len(filename)>200 or Path(filename).suffix.lower() not in domain.ALLOWED_ATTACHMENT_EXTENSIONS:
            raise HTTPException(422,'Этот тип файла не поддерживается')
        with domain.db() as conn:get_entity(conn,user,'tasks',tid,True)
        contents=await file.read(domain.MAX_ATTACHMENT_BYTES+1)
        await file.close()
        if not contents or len(contents)>domain.MAX_ATTACHMENT_BYTES:raise HTTPException(422,'Файл должен быть от 1 байта до 10 МБ')
        folder=domain.ATTACHMENT_DIR/'tasks';folder.mkdir(parents=True,exist_ok=True)
        stored=secrets.token_hex(20)+Path(filename).suffix.lower();path=folder/stored
        try:
            with domain.db() as conn:
                conn.execute('BEGIN IMMEDIATE');get_entity(conn,user,'tasks',tid,True)
                old=conn.execute('SELECT id FROM task_files WHERE task_id=? AND author_id=? AND request_id=?',(tid,user['id'],request_id)).fetchone()
                if old:return detail(conn,user,tid)
                path.write_bytes(contents)
                conn.execute('INSERT INTO task_files(task_id,author_id,filename,stored_name,size,request_id,created_at) VALUES(?,?,?,?,?,?,?)',(tid,user['id'],filename,stored,len(contents),request_id,domain.now()))
                audit(conn,domain,user,'tasks',tid,'file_add',{'filename':filename})
                result=detail(conn,user,tid)
            return result
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @router.get('/{tid}/files/{fid}')
    def download_file(tid:int,fid:int,desk_session:str|None=Cookie(default=None)):
        user=user_for(desk_session)
        with domain.db() as conn:
            get_entity(conn,user,'tasks',tid)
            row=conn.execute('SELECT * FROM task_files WHERE task_id=? AND id=? AND deleted_at IS NULL',(tid,fid)).fetchone()
            if not row:raise HTTPException(404,'Файл не найден')
            path=domain.ATTACHMENT_DIR/'tasks'/row['stored_name']
            if not path.is_file():raise HTTPException(404,'Файл недоступен')
            return FileResponse(path,filename=row['filename'],media_type='application/octet-stream',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @router.post('/{tid}/files/{fid}/hide')
    def hide_file(tid:int,fid:int,desk_session:str|None=Cookie(default=None)):
        return file_visibility(tid,fid,True,desk_session)

    @router.post('/{tid}/files/{fid}/restore')
    def restore_file(tid:int,fid:int,desk_session:str|None=Cookie(default=None)):
        return file_visibility(tid,fid,False,desk_session)

    def file_visibility(tid,fid,hidden,token):
        user=user_for(token)
        with domain.db() as conn:
            conn.execute('BEGIN IMMEDIATE');get_entity(conn,user,'tasks',tid,True)
            row=conn.execute('SELECT * FROM task_files WHERE task_id=? AND id=?',(tid,fid)).fetchone()
            if not row:raise HTTPException(404,'Файл не найден')
            conn.execute('UPDATE task_files SET deleted_at=? WHERE id=?',(domain.now() if hidden else None,fid))
            audit(conn,domain,user,'tasks',tid,'file_hide' if hidden else 'file_restore',{'filename':row['filename']})
            return detail(conn,user,tid)

    app.include_router(router)
