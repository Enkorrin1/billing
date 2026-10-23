"""
Admin panel backend module: comprehensive management of accounts, staff, client teams, and tickets.
"""
import json
import logging
from typing import Any, List, Optional, Literal
import sqlite3
from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=2, max_length=100)
    email: str
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(customer|employee|admin)$")
    is_manager: bool = False
    team_role: Optional[str] = None
    active: bool = True
    must_change_credentials: bool = False

    # Staff profile fields
    job_title: str = ""
    bio: str = ""
    functions: List[str] = []
    permissions: List[str] = []
    scope: Literal["assigned", "department", "all"] = "assigned"
    availability: str = "available"
    hourly_rate_cents: Optional[int] = Field(default=None, ge=1, le=100000000)

    # Customer profile fields
    company_name: str = ""
    phone: str = ""
    inn: str = ""
    legal_address: str = ""
    organization_id: Optional[int] = None
    org_role: Literal["owner", "member", "viewer"] = "member"
    hourly_rate_rub: Optional[int] = Field(default=None, ge=100, le=1000000)


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_manager: Optional[bool] = None
    team_role: Optional[str] = None
    active: Optional[bool] = None
    must_change_credentials: Optional[bool] = None

    # Staff fields
    job_title: Optional[str] = None
    bio: Optional[str] = None
    functions: Optional[List[str]] = None
    permissions: Optional[List[str]] = None
    scope: Optional[Literal["assigned", "department", "all"]] = None
    availability: Optional[str] = None
    hourly_rate_cents: Optional[int] = Field(default=None, ge=1, le=100000000)

    # Customer fields
    company_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    phone: Optional[str] = None
    inn: Optional[str] = None
    legal_address: Optional[str] = None
    hourly_rate_rub: Optional[int] = Field(default=None, ge=100, le=1000000)
    auto_approve_minutes: Optional[int] = None
    organization_id: Optional[int] = None
    org_role: Optional[Literal["owner", "member", "viewer"]] = None


class AdminOrgCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=2, max_length=100)
    hourly_rate_rub: int = Field(default=3000, ge=100, le=1000000)
    inn: str = ""
    kpp: str = ""
    legal_address: str = ""


class AdminOrgUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    hourly_rate_rub: Optional[int] = Field(default=None, ge=100, le=1000000)
    inn: Optional[str] = None
    kpp: Optional[str] = None
    legal_address: Optional[str] = None


class AdminOrgMemberAdd(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = ""
    role: Literal["owner", "member", "viewer"] = "member"


class ClientTeamMember(BaseModel):
    user_id: int
    responsibility: Literal["sales", "account", "project_manager", "technical", "specialist"]


class AdminClientTeamUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    members: List[ClientTeamMember]


class AdminEstimateInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amount_rub: Optional[int] = Field(default=None, ge=0, le=100000000)
    hourly_rate_rub: Optional[int] = Field(default=None, ge=100, le=1000000)
    performer_effort_minutes: Optional[int] = Field(default=None, ge=0, le=1000000)
    pm_effort_minutes: Optional[int] = Field(default=None, ge=0, le=1000000)
    state: Optional[Literal["pending_pm", "pending", "approved", "rejected", "revision_requested", "rejected_by_pm", "pm_revision_requested"]] = None
    note: Optional[str] = None
    client_note: Optional[str] = None
    author_id: Optional[int] = None


class AdminTicketUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    service_type: Optional[str] = None
    channel: Optional[str] = None
    service_limit_minutes: Optional[int] = None
    customer_id: Optional[int] = None
    organization_id: Optional[int] = None
    created_by_id: Optional[int] = None
    assignee_id: Optional[int] = None
    executor_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    observer_ids: Optional[List[int]] = None
    response_due_at: Optional[str] = None
    estimate_due_at: Optional[str] = None
    delivery_due_at: Optional[str] = None
    rating: Optional[int] = None
    rating_comment: Optional[str] = None
    estimate: Optional[AdminEstimateInput] = None


class AdminTicketCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2)
    customer_id: int
    organization_id: Optional[int] = None
    created_by_id: Optional[int] = None
    assignee_id: Optional[int] = None
    executor_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    observer_ids: List[int] = []
    status: Literal["new", "working", "waiting", "done", "closed"] = "new"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    service_type: str = "other"
    channel: str = "manual"
    service_limit_minutes: Optional[int] = None
    response_due_at: Optional[str] = None
    estimate_due_at: Optional[str] = None
    delivery_due_at: Optional[str] = None
    estimate: Optional[AdminEstimateInput] = None


def install_routes(app, domain):
    router = APIRouter(prefix="/api/admin")

    def require_admin(desk_session: str | None):
        user = domain.current_user(desk_session)
        domain.require_admin(user)
        return user

    def validate_staff(conn, ids):
        for uid in set(ids) - {None, 0}:
            if not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND role IN ('employee','admin')", (uid,)).fetchone():
                raise HTTPException(422, "Выберите активного сотрудника")

    def validate_profile(conn, data):
        for code in getattr(data, 'functions', None) or []:
            if not conn.execute("SELECT 1 FROM team_functions WHERE code=? AND active=1", (code,)).fetchone():
                raise HTTPException(422, "Неизвестная функция сотрудника")
        if set(getattr(data, 'permissions', None) or []) - set(domain.team_management.PERMISSIONS):
            raise HTTPException(422, 'Неизвестное разрешение')
        if getattr(data, 'organization_id', None):
            if data.organization_id > 0 and not conn.execute("SELECT 1 FROM organizations WHERE id=?", (data.organization_id,)).fetchone():
                raise HTTPException(422, "Компания не найдена")

    def protect_owner(conn, uid):
        membership = conn.execute("SELECT * FROM organization_members WHERE user_id=?", (uid,)).fetchone()
        if membership and membership['role'] == 'owner':
            domain.organization_member_to_edit(conn, membership['organization_id'], uid)

    def disable_user(conn, actor, person):
        if person['id'] == actor['id']:
            raise HTTPException(409, "Нельзя отключить собственный доступ")
        protect_owner(conn, person['id'])
        if person['role'] != 'customer':
            conn.execute("UPDATE tickets SET assignee_id=NULL,updated_at=? WHERE assignee_id=? AND status!='closed'", (domain.now(), person['id']))
            conn.execute("UPDATE chats SET assignee_id=NULL,updated_at=? WHERE assignee_id=?", (domain.now(), person['id']))
            domain.team_management.handover(conn, domain, actor, person['id'], None)
        conn.execute("DELETE FROM sessions WHERE user_id=?", (person['id'],))

    @router.get("/overview")
    def admin_overview(desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            users_total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            users_active = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
            customers_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0]
            staff_count = conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('employee', 'admin')").fetchone()[0]
            admins_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]

            tickets_total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            tickets_active = conn.execute("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('done','closed')").fetchone()[0]
            tickets_closed = conn.execute("SELECT COUNT(*) FROM tickets WHERE status IN ('done','closed')").fetchone()[0]
            orgs_total = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]

            return {
                "users_total": users_total,
                "users_active": users_active,
                "customers_count": customers_count,
                "staff_count": staff_count,
                "admins_count": admins_count,
                "tickets_total": tickets_total,
                "tickets_active": tickets_active,
                "tickets_closed": tickets_closed,
                "orgs_total": orgs_total,
            }

    @router.get("/users")
    def list_users(
        q: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        desk_session: str | None = Cookie(default=None)
    ):
        require_admin(desk_session)
        with domain.db() as conn:
            sql = """
                SELECT u.id, u.name, u.email, u.role, u.active, u.created_at, u.is_manager,
                       u.team_role, u.must_change_credentials, u.temporary_credentials_expires_at,
                       sp.job_title, sp.bio, sp.avatar_updated_at,
                       cp.company_name, cp.phone, cp.inn, cp.legal_address, cp.hourly_rate_rub, cp.auto_approve_minutes,
                       om.organization_id, o.name AS organization_name, om.role AS org_role,
                       ss.department, ss.availability, ss.permissions, ss.scope,
                       (SELECT cents_per_hour FROM payroll_rates WHERE employee_id=u.id ORDER BY id DESC LIMIT 1) AS payroll_rate_cents,
                       (SELECT COUNT(*) FROM tickets WHERE assignee_id=u.id AND status NOT IN ('done','closed')) AS assigned_tickets_count
                FROM users u
                LEFT JOIN staff_profiles sp ON sp.user_id = u.id
                LEFT JOIN customer_profiles cp ON cp.user_id = u.id
                LEFT JOIN organization_members om ON om.user_id = u.id
                LEFT JOIN organizations o ON o.id = om.organization_id
                LEFT JOIN staff_settings ss ON ss.user_id = u.id
                WHERE 1=1
            """
            params = []
            if role and role != "all":
                sql += " AND u.role = ?"
                params.append(role)
            if status == "active":
                sql += " AND u.active = 1"
            elif status == "inactive":
                sql += " AND u.active = 0"

            if q:
                kw = f"%{q.strip().lower()}%"
                sql += " AND (lower(u.name) LIKE ? OR lower(u.email) LIKE ? OR lower(COALESCE(cp.company_name,'')) LIKE ? OR lower(COALESCE(o.name,'')) LIKE ?)"
                params.extend([kw, kw, kw, kw])

            sql += " ORDER BY u.active DESC, u.id DESC"
            rows = conn.execute(sql, params).fetchall()

            # Batch load functions for all staff users
            funcs_by_uid = {}
            for row in conn.execute("SELECT user_id, function_code FROM staff_functions"):
                funcs_by_uid.setdefault(row[0], []).append(row[1])

            result = []
            for r in rows:
                item = dict(r)
                item["functions"] = funcs_by_uid.get(r["id"], [])
                item["is_manager"] = bool(item["is_manager"])
                item["active"] = bool(item["active"])
                item["must_change_credentials"] = bool(item["must_change_credentials"])
                item["permissions"] = json.loads(item["permissions"]) if item.get("permissions") else []
                result.append(item)
            return result

    @router.post("/users", status_code=201)
    def create_user(data: AdminUserCreate, desk_session: str | None = Cookie(default=None)):
        admin = require_admin(desk_session)
        clean_email = domain.clean_email(data.email)
        stamp = domain.now()

        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            validate_profile(conn, data)
            existing = conn.execute("SELECT id FROM users WHERE email=?", (clean_email,)).fetchone()
            if existing:
                raise HTTPException(409, "Пользователь с таким email уже существует")

            pwd_hash = domain.password_hash(data.password)
            cur = conn.execute(
                """INSERT INTO users(name, email, password_hash, role, active, created_at, is_manager, team_role, must_change_credentials)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (data.name.strip(), clean_email, pwd_hash, data.role, 1 if data.active else 0,
                 stamp, 1 if data.is_manager else 0, data.team_role, 1 if data.must_change_credentials else 0)
            )
            uid = cur.lastrowid

            if data.role in ("employee", "admin"):
                conn.execute(
                    "INSERT INTO staff_profiles(user_id, job_title, bio, updated_at) VALUES(?,?,?,?)",
                    (uid, data.job_title.strip(), data.bio.strip(), stamp)
                )
                if data.functions:
                    conn.executemany("INSERT OR IGNORE INTO staff_functions(user_id, function_code) VALUES(?,?)",
                                     [(uid, f) for f in data.functions])
                conn.execute(
                    """INSERT INTO staff_settings(user_id, department, manager_id, capacity_minutes, availability, permissions, scope, responsibilities, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (uid, "", None, 0, data.availability or "available", json.dumps(data.permissions or []),
                     data.scope or "all", json.dumps([]), stamp)
                )
                if data.hourly_rate_cents:
                    conn.execute(
                        "INSERT INTO payroll_rates(employee_id, cents_per_hour, created_by, created_at) VALUES(?,?,?,?)",
                        (uid, data.hourly_rate_cents, admin["id"], stamp)
                    )
            elif data.role == "customer":
                conn.execute(
                    """INSERT INTO customer_profiles(user_id, company_name, phone, inn, legal_address, hourly_rate_rub, updated_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (uid, data.company_name.strip(), data.phone.strip(), data.inn.strip(), data.legal_address.strip(),
                     data.hourly_rate_rub or 3000, stamp)
                )
                if data.organization_id:
                    conn.execute(
                        "INSERT INTO organization_members(organization_id, user_id, role, joined_at) VALUES(?,?,?,?)",
                        (data.organization_id, uid, data.org_role or "member", stamp)
                    )

            return {"ok": True, "id": uid, "name": data.name.strip(), "email": clean_email}

    @router.get("/users/{user_id}")
    def get_user(user_id: int, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, "Пользователь не найден")
            res = dict(user)
            res.pop("password_hash", None)
            res["is_manager"] = bool(res["is_manager"])
            res["active"] = bool(res["active"])
            res["must_change_credentials"] = bool(res["must_change_credentials"])

            # Staff
            sp = conn.execute("SELECT * FROM staff_profiles WHERE user_id=?", (user_id,)).fetchone()
            if sp:
                res["staff_profile"] = {
                    "job_title": sp["job_title"],
                    "bio": sp["bio"],
                    "avatar_updated_at": sp["avatar_updated_at"]
                }
            res["functions"] = [r[0] for r in conn.execute("SELECT function_code FROM staff_functions WHERE user_id=?", (user_id,)).fetchall()]
            ss = conn.execute("SELECT * FROM staff_settings WHERE user_id=?", (user_id,)).fetchone()
            if ss:
                res["staff_settings"] = {
                    "department": ss["department"],
                    "availability": ss["availability"],
                    "scope": ss["scope"],
                    "permissions": json.loads(ss["permissions"]) if ss["permissions"] else [],
                }
            rate = conn.execute("SELECT cents_per_hour FROM payroll_rates WHERE employee_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
            res["hourly_rate_cents"] = rate[0] if rate else None

            # Customer
            cp = conn.execute("SELECT * FROM customer_profiles WHERE user_id=?", (user_id,)).fetchone()
            if cp:
                res["customer_profile"] = {
                    "company_name": cp["company_name"],
                    "phone": cp["phone"],
                    "inn": cp["inn"],
                    "legal_address": cp["legal_address"],
                    "hourly_rate_rub": cp["hourly_rate_rub"],
                    "auto_approve_minutes": cp["auto_approve_minutes"],
                }
            om = conn.execute("""
                SELECT om.organization_id, om.role AS org_role, o.name AS organization_name
                FROM organization_members om JOIN organizations o ON o.id = om.organization_id
                WHERE om.user_id=?
            """, (user_id,)).fetchone()
            if om:
                res["organization"] = dict(om)

            return res

    @router.patch("/users/{user_id}")
    def update_user(user_id: int, data: AdminUserUpdate, desk_session: str | None = Cookie(default=None)):
        admin = require_admin(desk_session)
        stamp = domain.now()

        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, "Пользователь не найден")

            validate_profile(conn, data)
            if data.role is not None and data.role != user['role']:
                if user_id == admin['id']:
                    raise HTTPException(409, "Нельзя изменить собственную роль")
                protect_owner(conn, user_id)
                if (data.role == 'customer') != (user['role'] == 'customer'):
                    raise HTTPException(409, "Для перехода между заказчиком и сотрудником создайте отдельный аккаунт: история должна сохранить тип владельца")
            if data.active is False:
                disable_user(conn, admin, user)
            if data.organization_id is not None or data.org_role not in (None, 'owner'):
                protect_owner(conn, user_id)
            if data.password or (data.email is not None and domain.clean_email(data.email) != user['email']) or (data.role is not None and data.role != user['role']):
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            # Check email uniqueness
            if data.email is not None:
                new_email = domain.clean_email(data.email)
                conflict = conn.execute("SELECT id FROM users WHERE email=? AND id!=?", (new_email, user_id)).fetchone()
                if conflict:
                    raise HTTPException(409, "Email уже используется другим аккаунтом")
                conn.execute("UPDATE users SET email=? WHERE id=?", (new_email, user_id))

            # Direct password reset by admin
            if data.password:
                if len(data.password) < 8:
                    raise HTTPException(422, "Пароль должен содержать минимум 8 символов")
                pwd_hash = domain.password_hash(data.password)
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (pwd_hash, user_id))

            if data.name is not None:
                conn.execute("UPDATE users SET name=? WHERE id=?", (data.name.strip(), user_id))

            if data.role is not None:
                if data.role not in ("customer", "employee", "admin"):
                    raise HTTPException(422, "Недопустимая роль")
                conn.execute("UPDATE users SET role=? WHERE id=?", (data.role, user_id))

            if data.is_manager is not None:
                conn.execute("UPDATE users SET is_manager=? WHERE id=?", (1 if data.is_manager else 0, user_id))

            if data.team_role is not None:
                conn.execute("UPDATE users SET team_role=? WHERE id=?", (data.team_role or None, user_id))

            if data.active is not None:
                conn.execute("UPDATE users SET active=? WHERE id=?", (1 if data.active else 0, user_id))
                if not data.active:
                    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

            if data.must_change_credentials is not None:
                conn.execute("UPDATE users SET must_change_credentials=? WHERE id=?",
                             (1 if data.must_change_credentials else 0, user_id))

            # Staff Profile updates
            if data.job_title is not None or data.bio is not None:
                conn.execute("""
                    INSERT INTO staff_profiles(user_id, job_title, bio, updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    job_title=COALESCE(?, job_title),
                    bio=COALESCE(?, bio),
                    updated_at=?
                """, (user_id, data.job_title or "", data.bio or "", stamp,
                      data.job_title, data.bio, stamp))

            if data.functions is not None:
                conn.execute("DELETE FROM staff_functions WHERE user_id=?", (user_id,))
                conn.executemany("INSERT OR IGNORE INTO staff_functions(user_id, function_code) VALUES(?,?)",
                                 [(user_id, f) for f in data.functions])

            if any(x is not None for x in (data.permissions, data.scope, data.availability)):
                ss = conn.execute("SELECT * FROM staff_settings WHERE user_id=?", (user_id,)).fetchone()
                cur_perms = json.loads(ss["permissions"]) if ss and ss["permissions"] else []
                new_perms = json.dumps(data.permissions if data.permissions is not None else cur_perms)
                new_scope = data.scope if data.scope is not None else (ss["scope"] if ss else "all")
                new_avail = data.availability if data.availability is not None else (ss["availability"] if ss else "available")
                conn.execute("""
                    INSERT INTO staff_settings(user_id, department, manager_id, capacity_minutes, availability, permissions, scope, responsibilities, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    permissions=excluded.permissions,
                    scope=excluded.scope,
                    availability=excluded.availability,
                    updated_at=excluded.updated_at
                """, (user_id, "", None, 0, new_avail, new_perms, new_scope, json.dumps([]), stamp))

            if data.hourly_rate_cents is not None and data.hourly_rate_cents > 0:
                conn.execute(
                    "INSERT INTO payroll_rates(employee_id, cents_per_hour, created_by, created_at) VALUES(?,?,?,?)",
                    (user_id, data.hourly_rate_cents, admin["id"], stamp)
                )

            # Customer Profile updates
            if any(x is not None for x in (data.company_name, data.phone, data.inn, data.legal_address, data.hourly_rate_rub, data.auto_approve_minutes)):
                conn.execute("""
                    INSERT INTO customer_profiles(user_id, company_name, phone, inn, legal_address, hourly_rate_rub, auto_approve_minutes, updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    company_name=COALESCE(?, company_name),
                    phone=COALESCE(?, phone),
                    inn=COALESCE(?, inn),
                    legal_address=COALESCE(?, legal_address),
                    hourly_rate_rub=COALESCE(?, hourly_rate_rub),
                    auto_approve_minutes=COALESCE(?, auto_approve_minutes),
                    updated_at=?
                """, (user_id, data.company_name or "", data.phone or "", data.inn or "", data.legal_address or "",
                      data.hourly_rate_rub or 3000, data.auto_approve_minutes or 0, stamp,
                      data.company_name, data.phone, data.inn, data.legal_address, data.hourly_rate_rub, data.auto_approve_minutes, stamp))

            # Organization assignment
            if data.organization_id is not None:
                if data.organization_id <= 0:
                    conn.execute("DELETE FROM organization_members WHERE user_id=?", (user_id,))
                else:
                    role_to_set = data.org_role or "member"
                    conn.execute("""
                        INSERT INTO organization_members(organization_id, user_id, role, joined_at)
                        VALUES(?,?,?,?)
                        ON CONFLICT(user_id) DO UPDATE SET
                        organization_id=excluded.organization_id,
                        role=excluded.role
                    """, (data.organization_id, user_id, role_to_set, stamp))
            elif data.org_role is not None:
                conn.execute("UPDATE organization_members SET role=? WHERE user_id=?", (data.org_role, user_id))

            return {"ok": True, "id": user_id}

    @router.delete("/users/{user_id}")
    def delete_user(user_id: int, desk_session: str | None = Cookie(default=None)):
        admin = require_admin(desk_session)
        if user_id == admin["id"]:
            raise HTTPException(400, "Нельзя удалить собственный аккаунт")
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, "Пользователь не найден")
            disable_user(conn, admin, user)
            conn.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            return {"ok": True, "message": "Пользователь деактивирован"}

    # ==========================
    # STAFF & CLIENT TEAMS
    # ==========================

    @router.get("/staff")
    def list_staff(desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            rows = conn.execute("""
                SELECT u.id, u.name, u.email, u.role, u.active, u.is_manager, u.team_role,
                       sp.job_title, sp.bio, sp.avatar_updated_at,
                       ss.availability, ss.permissions, ss.scope,
                       (SELECT cents_per_hour FROM payroll_rates WHERE employee_id=u.id ORDER BY id DESC LIMIT 1) AS payroll_rate_cents,
                       (SELECT COUNT(*) FROM tickets WHERE assignee_id=u.id AND status NOT IN ('done','closed')) AS active_assigned_tickets,
                       (SELECT COUNT(*) FROM ticket_participants WHERE user_id=u.id AND participation='executor') AS active_executor_tickets
                FROM users u
                LEFT JOIN staff_profiles sp ON sp.user_id = u.id
                LEFT JOIN staff_settings ss ON ss.user_id = u.id
                WHERE u.role IN ('employee', 'admin')
                ORDER BY u.active DESC, u.name ASC
            """).fetchall()

            funcs_by_uid = {}
            for row in conn.execute("SELECT user_id, function_code FROM staff_functions"):
                funcs_by_uid.setdefault(row[0], []).append(row[1])

            staff_list = []
            for r in rows:
                item = dict(r)
                item["functions"] = funcs_by_uid.get(r["id"], [])
                item["permissions"] = json.loads(item["permissions"]) if item.get("permissions") else []
                item["is_manager"] = bool(item["is_manager"])
                item["active"] = bool(item["active"])
                staff_list.append(item)
            return staff_list

    @router.get("/organizations")
    def list_organizations(desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            orgs = conn.execute("SELECT * FROM organizations ORDER BY name ASC").fetchall()
            result = []
            for org in orgs:
                oid = org["id"]
                members = conn.execute("""
                    SELECT om.user_id, om.role, om.joined_at,
                           u.name, u.email, u.active, u.must_change_credentials,
                           cp.phone, cp.company_name
                    FROM organization_members om
                    JOIN users u ON u.id = om.user_id
                    LEFT JOIN customer_profiles cp ON cp.user_id = u.id
                    WHERE om.organization_id=?
                    ORDER BY CASE om.role WHEN 'owner' THEN 1 WHEN 'member' THEN 2 ELSE 3 END, u.name ASC
                """, (oid,)).fetchall()

                # Internal staff assigned to this client
                assigned_team = conn.execute("""
                    SELECT ct.user_id, ct.responsibility, u.name, u.email, sp.job_title
                    FROM client_team ct
                    JOIN users u ON u.id = ct.user_id
                    LEFT JOIN staff_profiles sp ON sp.user_id = u.id
                    WHERE ct.customer_id IN (SELECT user_id FROM organization_members WHERE organization_id=?)
                    GROUP BY ct.user_id, ct.responsibility
                """, (oid,)).fetchall()

                # Tickets count
                tickets_count = conn.execute("""
                    SELECT COUNT(*) FROM tickets WHERE organization_id=? OR customer_id IN
                    (SELECT user_id FROM organization_members WHERE organization_id=?)
                """, (oid, oid)).fetchone()[0]

                result.append({
                    **dict(org),
                    "members": [dict(m) for m in members],
                    "assigned_team": [dict(t) for t in assigned_team],
                    "tickets_count": tickets_count
                })
            return result

    @router.post("/organizations", status_code=201)
    def create_organization(data: AdminOrgCreate, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        stamp = domain.now()
        with domain.db() as conn:
            cur = conn.execute(
                """INSERT INTO organizations(name, created_at, hourly_rate_rub, inn, kpp, legal_address)
                   VALUES(?,?,?,?,?,?)""",
                (data.name.strip(), stamp, data.hourly_rate_rub or 3000,
                 data.inn.strip(), data.kpp.strip(), data.legal_address.strip())
            )
            return {"ok": True, "id": cur.lastrowid, "name": data.name.strip()}

    @router.patch("/organizations/{org_id}")
    def update_organization(org_id: int, data: AdminOrgUpdate, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            org = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
            if not org:
                raise HTTPException(404, "Компания не найдена")

            if data.name is not None:
                conn.execute("UPDATE organizations SET name=? WHERE id=?", (data.name.strip(), org_id))
            if data.hourly_rate_rub is not None:
                conn.execute("UPDATE organizations SET hourly_rate_rub=? WHERE id=?", (data.hourly_rate_rub, org_id))
            if data.inn is not None:
                conn.execute("UPDATE organizations SET inn=? WHERE id=?", (data.inn.strip(), org_id))
            if data.kpp is not None:
                conn.execute("UPDATE organizations SET kpp=? WHERE id=?", (data.kpp.strip(), org_id))
            if data.legal_address is not None:
                conn.execute("UPDATE organizations SET legal_address=? WHERE id=?", (data.legal_address.strip(), org_id))

            return {"ok": True, "id": org_id}

    @router.delete("/organizations/{org_id}")
    def delete_organization(org_id: int, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            org = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
            if not org:
                raise HTTPException(404, "Компания не найдена")
            if org['deposit_balance_rub'] or org['held_rub']:
                raise HTTPException(409, "У компании есть финансовый остаток")
            try:
                conn.execute("DELETE FROM organizations WHERE id=?", (org_id,))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "У компании есть участники или история; удаление недоступно")
            return {"ok": True}

    @router.post("/organizations/{org_id}/members", status_code=201)
    def add_org_member(org_id: int, data: AdminOrgMemberAdd, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        stamp = domain.now()
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            org = conn.execute("SELECT id FROM organizations WHERE id=?", (org_id,)).fetchone()
            if not org:
                raise HTTPException(404, "Компания не найдена")

            uid = data.user_id
            if not uid:
                if not data.email or not data.name or not data.password:
                    raise HTTPException(422, "Укажите имя, email и пароль для нового пользователя")
                if len(data.password) < 8:
                    raise HTTPException(422, "Пароль должен содержать минимум 8 символов")
                c_email = domain.clean_email(data.email)
                conflict = conn.execute("SELECT id FROM users WHERE email=?", (c_email,)).fetchone()
                if conflict:
                    raise HTTPException(409, "Пользователь с таким email уже существует")
                pwd_hash = domain.password_hash(data.password)
                cur = conn.execute(
                    """INSERT INTO users(name, email, password_hash, role, active, created_at, is_manager)
                       VALUES(?,?,?,?,1,?,0)""",
                    (data.name.strip(), c_email, pwd_hash, "customer", stamp)
                )
                uid = cur.lastrowid
                conn.execute(
                    "INSERT INTO customer_profiles(user_id, phone, updated_at) VALUES(?,?,?)",
                    (uid, (data.phone or "").strip(), stamp)
                )

            person = conn.execute("SELECT * FROM users WHERE id=? AND active=1 AND role='customer'", (uid,)).fetchone()
            if not person:
                raise HTTPException(422, "Выберите активного заказчика")
            previous = conn.execute("SELECT organization_id FROM organization_members WHERE user_id=?", (uid,)).fetchone()
            if previous and previous['organization_id'] != org_id:
                raise HTTPException(409, "Сначала удалите участника из предыдущей компании")
            protect_owner(conn, uid)
            # Assign to org
            conn.execute("""
                INSERT INTO organization_members(organization_id, user_id, role, joined_at)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                organization_id=excluded.organization_id,
                role=excluded.role
            """, (org_id, uid, data.role or "member", stamp))

            return {"ok": True, "user_id": uid, "organization_id": org_id}

    @router.delete("/organizations/{org_id}/members/{user_id}")
    def remove_org_member(org_id: int, user_id: int, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            protect_owner(conn, user_id)
            conn.execute("DELETE FROM organization_members WHERE organization_id=? AND user_id=?", (org_id, user_id))
            return {"ok": True}

    @router.put("/organizations/{org_id}/team")
    def update_organization_team(org_id: int, data: AdminClientTeamUpdate, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            member_ids = [r[0] for r in conn.execute("SELECT user_id FROM organization_members WHERE organization_id=?", (org_id,)).fetchall()]
            if not member_ids:
                raise HTTPException(400, "В компании нет участников для закрепления команды")

            validate_staff(conn, [m.user_id for m in data.members])
            for cid in member_ids:
                conn.execute("DELETE FROM client_team WHERE customer_id=?", (cid,))
                conn.executemany(
                    "INSERT OR IGNORE INTO client_team(customer_id, user_id, responsibility) VALUES(?,?,?)",
                    [(cid, m.user_id, m.responsibility) for m in data.members]
                )
            return {"ok": True}

    # ==========================
    # TICKETS & ESTIMATES FULL EDITING
    # ==========================

    @router.get("/tickets")
    def list_all_tickets(
        q: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        customer_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        executor_id: Optional[int] = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        desk_session: str | None = Cookie(default=None)
    ):
        require_admin(desk_session)
        with domain.db() as conn:
            sql = """
                SELECT t.id, t.title, t.description, t.status, t.priority, t.service_type, t.channel,
                       t.service_limit_minutes, t.customer_id, t.organization_id, t.created_by_id, t.assignee_id,
                       t.response_due_at, t.estimate_due_at, t.delivery_due_at, t.created_at, t.updated_at,
                       t.rating, t.rating_comment,
                       c.name AS customer_name, c.email AS customer_email,
                       o.name AS organization_name,
                       a.name AS assignee_name,
                       (SELECT u.name FROM users u JOIN ticket_participants p ON p.user_id=u.id WHERE p.ticket_id=t.id AND p.participation='executor' LIMIT 1) AS executor_name,
                       (SELECT p.user_id FROM ticket_participants p WHERE p.ticket_id=t.id AND p.participation='executor' LIMIT 1) AS executor_id,
                       (SELECT e.amount_rub FROM estimates e WHERE e.ticket_id=t.id ORDER BY e.version DESC LIMIT 1) AS estimate_amount_rub,
                       (SELECT e.state FROM estimates e WHERE e.ticket_id=t.id ORDER BY e.version DESC LIMIT 1) AS estimate_state
                FROM tickets t
                JOIN users c ON c.id = t.customer_id
                LEFT JOIN organizations o ON o.id = t.organization_id
                LEFT JOIN users a ON a.id = t.assignee_id
                WHERE 1=1
            """
            params = []
            if status:
                sql += " AND t.status = ?"
                params.append(status)
            if priority:
                sql += " AND t.priority = ?"
                params.append(priority)
            if customer_id:
                sql += " AND t.customer_id = ?"
                params.append(customer_id)
            if assignee_id:
                sql += " AND t.assignee_id = ?"
                params.append(assignee_id)
            if executor_id:
                sql += " AND EXISTS (SELECT 1 FROM ticket_participants WHERE ticket_id=t.id AND user_id=? AND participation='executor')"
                params.append(executor_id)
            if q:
                kw = f"%{q.strip().lower()}%"
                sql += " AND (CAST(t.id AS TEXT) LIKE ? OR lower(t.title) LIKE ? OR lower(t.description) LIKE ? OR lower(c.name) LIKE ? OR lower(COALESCE(o.name,'')) LIKE ?)"
                params.extend([kw, kw, kw, kw, kw])

            sql += " ORDER BY t.id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    @router.get("/tickets/{ticket_id}")
    def get_admin_ticket(ticket_id: int, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            ticket = conn.execute("""
                SELECT t.*, c.name AS customer_name, c.email AS customer_email,
                       o.name AS organization_name, a.name AS assignee_name,
                       cr.name AS created_by_name
                FROM tickets t
                JOIN users c ON c.id = t.customer_id
                LEFT JOIN organizations o ON o.id = t.organization_id
                LEFT JOIN users a ON a.id = t.assignee_id
                LEFT JOIN users cr ON cr.id = t.created_by_id
                WHERE t.id=?
            """, (ticket_id,)).fetchone()
            if not ticket:
                raise HTTPException(404, "Заявка не найдена")

            # Participants
            participants = conn.execute("""
                SELECT p.user_id, p.participation, u.name, u.email, sp.job_title
                FROM ticket_participants p
                JOIN users u ON u.id = p.user_id
                LEFT JOIN staff_profiles sp ON sp.user_id = u.id
                WHERE p.ticket_id=?
            """, (ticket_id,)).fetchall()

            executor = next((dict(p) for p in participants if p["participation"] == "executor"), None)
            reviewer = next((dict(p) for p in participants if p["participation"] == "reviewer"), None)
            observers = [dict(p) for p in participants if p["participation"] == "observer"]

            # Estimate
            latest_estimate = conn.execute("""
                SELECT e.*, u.name AS author_name
                FROM estimates e
                JOIN users u ON u.id = e.author_id
                WHERE e.ticket_id=?
                ORDER BY e.version DESC LIMIT 1
            """, (ticket_id,)).fetchone()

            return {
                "ticket": dict(ticket),
                "executor": executor,
                "reviewer": reviewer,
                "observers": observers,
                "estimate": dict(latest_estimate) if latest_estimate else None,
            }

    @router.post("/tickets", status_code=201)
    def create_admin_ticket(data: AdminTicketCreate, desk_session: str | None = Cookie(default=None)):
        admin = require_admin(desk_session)
        stamp = domain.now()
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            validate_staff(conn, [data.assignee_id, data.executor_id, data.reviewer_id, *data.observer_ids])
            # Verify customer
            customer = conn.execute("SELECT id FROM users WHERE id=? AND role='customer' AND active=1", (data.customer_id,)).fetchone()
            if not customer:
                raise HTTPException(422, "Заказчик не найден")

            org_id = data.organization_id
            if org_id is None:
                om = conn.execute("SELECT organization_id FROM organization_members WHERE user_id=?", (data.customer_id,)).fetchone()
                if om:
                    org_id = om[0]

            if org_id and not conn.execute("SELECT 1 FROM organization_members WHERE organization_id=? AND user_id=?", (org_id, data.customer_id)).fetchone():
                raise HTTPException(422, "Заказчик не состоит в выбранной компании")
            creator_id = data.created_by_id or admin["id"]
            if not conn.execute("SELECT 1 FROM users WHERE id=?", (creator_id,)).fetchone():
                raise HTTPException(422, "Автор не найден")
            response_hours, estimate_hours = {'urgent':(2,12),'high':(4,24),'normal':(24,72),'low':(48,120)}[data.priority]
            response_due = data.response_due_at or (domain.datetime.fromisoformat(stamp) + domain.timedelta(hours=response_hours)).isoformat()
            estimate_due = data.estimate_due_at or (domain.datetime.fromisoformat(stamp) + domain.timedelta(hours=estimate_hours)).isoformat()

            cur = conn.execute("""
                INSERT INTO tickets(
                    customer_id, organization_id, created_by_id, assignee_id,
                    title, description, status, priority, service_type, channel,
                    service_limit_minutes, response_due_at, estimate_due_at, delivery_due_at,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                data.customer_id, org_id, creator_id, data.assignee_id,
                data.title.strip(), data.description.strip(), data.status or "new",
                data.priority or "normal", data.service_type or "other", data.channel or "manual",
                data.service_limit_minutes, response_due, estimate_due,
                data.delivery_due_at, stamp, stamp
            ))
            tid = cur.lastrowid
            domain.notify(conn, data.customer_id, tid, "new_ticket", f"Для вас создана заявка №{tid}: {data.title.strip()}")

            # Participants
            if data.executor_id:
                conn.execute("INSERT OR REPLACE INTO ticket_participants(ticket_id, user_id, participation) VALUES(?,?,?)",
                             (tid, data.executor_id, "executor"))
            if data.reviewer_id:
                conn.execute("INSERT OR REPLACE INTO ticket_participants(ticket_id, user_id, participation) VALUES(?,?,?)",
                             (tid, data.reviewer_id, "reviewer"))
            if data.observer_ids:
                for oid in set(data.observer_ids) - {data.executor_id, data.reviewer_id}:
                    if oid:
                        conn.execute("INSERT OR REPLACE INTO ticket_participants(ticket_id, user_id, participation) VALUES(?,?,?)",
                                     (tid, oid, "observer"))

            # Estimate
            if data.estimate and (data.estimate.amount_rub is not None or data.estimate.performer_effort_minutes is not None):
                est = data.estimate
                perf_mins = est.performer_effort_minutes or 0
                pm_mins = est.pm_effort_minutes or 0
                effort_mins = perf_mins + pm_mins
                hr_rate = est.hourly_rate_rub or 3000
                calc_amount = est.amount_rub if est.amount_rub is not None else int((effort_mins / 60.0) * hr_rate)
                author_id = est.author_id or admin["id"]

                conn.execute("""
                    INSERT INTO estimates(
                        ticket_id, author_id, version, amount_minor, assessment_minutes, note, state,
                        created_at, effort_minutes, performer_effort_minutes, pm_effort_minutes,
                        total_billable_minutes, hourly_rate_rub, amount_rub, client_note
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    tid, author_id, 1, calc_amount * 100, 1,
                    est.note or "", est.state or "pending", stamp, effort_mins, perf_mins,
                    pm_mins, effort_mins, hr_rate, calc_amount, est.client_note or ""
                ))

            # Audit event
            conn.execute(
                "INSERT INTO ticket_events(ticket_id, actor_id, kind, new_value, created_at) VALUES(?,?,?,?,?)",
                (tid, admin["id"], "create_admin", f"Заявка создана администратором: {data.title}", stamp)
            )

            # Broadcast live update
            recipients = {data.customer_id, admin["id"]}
            if data.assignee_id:
                recipients.add(data.assignee_id)
            if data.executor_id:
                recipients.add(data.executor_id)
            domain.realtime_bus.broadcast(recipients, {"type": "ticket_updated", "ticket_id": tid})

            return {"ok": True, "id": tid, "title": data.title.strip()}

    @router.patch("/tickets/{ticket_id}")
    def update_admin_ticket(ticket_id: int, data: AdminTicketUpdate, desk_session: str | None = Cookie(default=None)):
        admin = require_admin(desk_session)
        stamp = domain.now()
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if not ticket:
                raise HTTPException(404, "Заявка не найдена")

            validate_staff(conn, [data.assignee_id, data.executor_id, data.reviewer_id, *(data.observer_ids or [])])
            if ticket['act_invoice_id'] and any(getattr(data, f) is not None for f in ('estimate','customer_id','organization_id','status')):
                raise HTTPException(409, "Сначала аннулируйте акт по заявке")
            if data.customer_id is not None and data.customer_id != ticket['customer_id']:
                raise HTTPException(409, "Нельзя переносить историю заявки другому заказчику")
            if data.organization_id is not None and (data.organization_id or None) != ticket['organization_id']:
                raise HTTPException(409, "Нельзя переносить финансовую историю заявки в другую компанию")
            # Collect field updates
            updates = []
            params = []

            if data.title is not None:
                updates.append("title = ?")
                params.append(data.title.strip())

            if data.description is not None:
                updates.append("description = ?")
                params.append(data.description.strip())

            if data.status is not None:
                if data.status not in domain.STATUSES:
                    raise HTTPException(422, f"Недопустимый статус заявки: {data.status}")
                updates.append("status = ?")
                params.append(data.status)
                if ticket["status"] != data.status:
                    conn.execute(
                        "INSERT INTO ticket_events(ticket_id, actor_id, kind, old_value, new_value, created_at) VALUES(?,?,?,?,?,?)",
                        (ticket_id, admin["id"], "status", ticket["status"], data.status, stamp)
                    )

            if data.priority is not None:
                if data.priority not in ("low", "normal", "high", "urgent"):
                    raise HTTPException(422, "Недопустимый приоритет")
                updates.append("priority = ?")
                params.append(data.priority)

            if data.service_type is not None:
                updates.append("service_type = ?")
                params.append(data.service_type)

            if data.channel is not None:
                updates.append("channel = ?")
                params.append(data.channel)

            if data.service_limit_minutes is not None:
                limit_val = None if data.service_limit_minutes < 0 else data.service_limit_minutes
                updates.append("service_limit_minutes = ?")
                params.append(limit_val)

            if data.customer_id is not None:
                cust = conn.execute("SELECT id FROM users WHERE id=?", (data.customer_id,)).fetchone()
                if not cust:
                    raise HTTPException(422, "Указанный заказчик не существует")
                updates.append("customer_id = ?")
                params.append(data.customer_id)

            if data.organization_id is not None:
                org_val = None if data.organization_id <= 0 else data.organization_id
                updates.append("organization_id = ?")
                params.append(org_val)

            if data.created_by_id is not None:
                cr_val = None if data.created_by_id <= 0 else data.created_by_id
                updates.append("created_by_id = ?")
                params.append(cr_val)

            if data.assignee_id is not None:
                assignee_val = None if data.assignee_id <= 0 else data.assignee_id
                updates.append("assignee_id = ?")
                params.append(assignee_val)
                if ticket["assignee_id"] != assignee_val:
                    conn.execute(
                        "INSERT INTO ticket_events(ticket_id, actor_id, kind, old_value, new_value, created_at) VALUES(?,?,?,?,?,?)",
                        (ticket_id, admin["id"], "assignment", str(ticket["assignee_id"] or ""), str(assignee_val or ""), stamp)
                    )

            if data.response_due_at is not None:
                updates.append("response_due_at = ?")
                params.append(data.response_due_at or None)

            if data.estimate_due_at is not None:
                updates.append("estimate_due_at = ?")
                params.append(data.estimate_due_at or None)

            if data.delivery_due_at is not None:
                updates.append("delivery_due_at = ?")
                params.append(data.delivery_due_at or None)

            if data.rating is not None:
                rating_val = None if data.rating <= 0 else max(1, min(5, data.rating))
                updates.append("rating = ?")
                params.append(rating_val)
                updates.append("rated_at = ?")
                params.append(stamp if rating_val else None)

            if data.rating_comment is not None:
                updates.append("rating_comment = ?")
                params.append(data.rating_comment.strip() or None)

            # Always bump updated_at
            updates.append("updated_at = ?")
            params.append(stamp)

            if updates:
                sql = f"UPDATE tickets SET {', '.join(updates)} WHERE id = ?"
                params.append(ticket_id)
                conn.execute(sql, params)

            # ==========================
            # Participants editing (executor, reviewer, observers)
            # ==========================
            if data.executor_id is not None:
                conn.execute("DELETE FROM ticket_participants WHERE ticket_id=? AND participation='executor'", (ticket_id,))
                if data.executor_id > 0:
                    conn.execute("INSERT OR REPLACE INTO ticket_participants(ticket_id, user_id, participation) VALUES(?,?,?)",
                                 (ticket_id, data.executor_id, "executor"))

            if data.reviewer_id is not None:
                conn.execute("DELETE FROM ticket_participants WHERE ticket_id=? AND participation='reviewer'", (ticket_id,))
                if data.reviewer_id > 0:
                    conn.execute("INSERT OR REPLACE INTO ticket_participants(ticket_id, user_id, participation) VALUES(?,?,?)",
                                 (ticket_id, data.reviewer_id, "reviewer"))

            if data.observer_ids is not None:
                conn.execute("DELETE FROM ticket_participants WHERE ticket_id=? AND participation='observer'", (ticket_id,))
                for oid in set(data.observer_ids):
                    if oid > 0:
                        conn.execute("INSERT OR REPLACE INTO ticket_participants(ticket_id, user_id, participation) VALUES(?,?,?)",
                                     (ticket_id, oid, "observer"))

            # ==========================
            # Estimate editing
            # ==========================
            if data.estimate is not None:
                est = data.estimate
                latest_est = conn.execute("SELECT * FROM estimates WHERE ticket_id=? ORDER BY version DESC LIMIT 1", (ticket_id,)).fetchone()
                if latest_est:
                    # Update existing estimate fields
                    cur_perf = est.performer_effort_minutes if est.performer_effort_minutes is not None else latest_est["performer_effort_minutes"] or 0
                    cur_pm = est.pm_effort_minutes if est.pm_effort_minutes is not None else latest_est["pm_effort_minutes"] or 0
                    cur_effort = cur_perf + cur_pm
                    cur_rate = est.hourly_rate_rub if est.hourly_rate_rub is not None else latest_est["hourly_rate_rub"] or 3000
                    cur_amount = est.amount_rub if est.amount_rub is not None else latest_est["amount_rub"] or 0
                    cur_state = est.state if est.state is not None else latest_est["state"]
                    cur_note = est.note if est.note is not None else latest_est["note"]
                    cur_client_note = est.client_note if est.client_note is not None else latest_est["client_note"]
                    cur_author = est.author_id or latest_est["author_id"]

                    conn.execute("""
                        UPDATE estimates SET
                            author_id=?, amount_minor=?, assessment_minutes=?, note=?, state=?,
                            effort_minutes=?, performer_effort_minutes=?, pm_effort_minutes=?,
                            total_billable_minutes=?, hourly_rate_rub=?, amount_rub=?, client_note=?
                        WHERE id=?
                    """, (
                        cur_author, cur_amount * 100, latest_est["assessment_minutes"], cur_note, cur_state,
                        cur_effort, cur_perf, cur_pm, cur_effort, cur_rate, cur_amount, cur_client_note,
                        latest_est["id"]
                    ))
                else:
                    # Create new estimate (version 1)
                    perf_mins = est.performer_effort_minutes or 0
                    pm_mins = est.pm_effort_minutes or 0
                    effort_mins = perf_mins + pm_mins
                    hr_rate = est.hourly_rate_rub or 3000
                    amount_rub = est.amount_rub if est.amount_rub is not None else int((effort_mins / 60.0) * hr_rate)
                    author_id = est.author_id or admin["id"]

                    conn.execute("""
                        INSERT INTO estimates(
                            ticket_id, author_id, version, amount_minor, assessment_minutes, note, state,
                            created_at, effort_minutes, performer_effort_minutes, pm_effort_minutes,
                            total_billable_minutes, hourly_rate_rub, amount_rub, client_note
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        ticket_id, author_id, 1, amount_rub * 100, 1,
                        est.note or "", est.state or "pending", stamp, effort_mins, perf_mins,
                        pm_mins, effort_mins, hr_rate, amount_rub, est.client_note or ""
                    ))

            # Record audit event
            conn.execute(
                "INSERT INTO ticket_events(ticket_id, actor_id, kind, new_value, created_at) VALUES(?,?,?,?,?)",
                (ticket_id, admin["id"], "admin_edit", "Все поля заявки отредактированы администратором", stamp)
            )

            # Live broadcast
            recipients = {ticket["customer_id"], admin["id"]}
            if ticket["assignee_id"]:
                recipients.add(ticket["assignee_id"])
            if data.assignee_id:
                recipients.add(data.assignee_id)
            if data.customer_id:
                recipients.add(data.customer_id)
            domain.realtime_bus.broadcast(recipients, {"type": "ticket_updated", "ticket_id": ticket_id})

            return {"ok": True, "id": ticket_id}

    @router.delete("/tickets/{ticket_id}")
    def delete_ticket(ticket_id: int, desk_session: str | None = Cookie(default=None)):
        require_admin(desk_session)
        with domain.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM tickets WHERE id=?", (ticket_id,)).fetchone():
                raise HTTPException(404, "Заявка не найдена")
            try:
                conn.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "У заявки есть история или финансовые связи. Используйте закрытие заявки")
            return {"ok": True}

    app.include_router(router)
    logger.info("Admin routes registered at /api/admin")
