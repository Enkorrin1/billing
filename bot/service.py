"""One conversation engine for both messengers; domain writes reuse app services."""

import hashlib
import json
import secrets
import time
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from pydantic import ValidationError

from .providers import PROVIDERS, config, configured, normalize, public_url


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hours(minutes):
    return f"{minutes / 60:g} ч"


class BotEngine:
    def __init__(self, desk):
        self.desk = desk

    def settings(self, conn, user):
        links = conn.execute("SELECT id,provider,display_name,enabled FROM bot_links WHERE user_id=?", (user["id"],)).fetchall()
        pref = conn.execute("SELECT channel FROM bot_preferences WHERE user_id=?", (user["id"],)).fetchone()
        pending = conn.execute("""SELECT provider,display_name,external_id FROM bot_pairings
            WHERE user_id=? AND expires_at>? AND external_id IS NOT NULL""", (user["id"], time.time())).fetchall()
        return {"links": [dict(x) for x in links], "channel": pref["channel"] if pref else "off",
                "pending": [dict(x) for x in pending],
                "providers": [{"provider": p, "configured": configured(p), "url": config(p)["url"] if configured(p) else ""} for p in PROVIDERS]}

    def create_pairing(self, conn, user, provider):
        if provider not in PROVIDERS or not configured(provider):
            raise HTTPException(409, "Бот пока не настроен администратором")
        token = secrets.token_urlsafe(24)
        conn.execute("DELETE FROM bot_pairings WHERE user_id=? AND provider=?", (user["id"], provider))
        conn.execute("INSERT INTO bot_pairings(token_hash,user_id,provider,expires_at,confirmation) VALUES(?,?,?,?,?)",
                     (digest(token), user["id"], provider, time.time() + 600, secrets.token_hex(3).upper()))
        return {"command": "/link " + token, "expires_in": 600, "url": config(provider)["url"]}

    def claim_pairing(self, conn, event, token):
        row = conn.execute("SELECT * FROM bot_pairings WHERE token_hash=? AND provider=? AND expires_at>?",
                           (digest(token), event.provider, time.time())).fetchone()
        if not row or row["external_id"]:
            self.queue(conn, event, "Код недействителен или уже использован. Создайте новый код в кабинете.")
            return
        if conn.execute("SELECT 1 FROM bot_links WHERE provider=? AND external_id=?", (event.provider, event.external_id)).fetchone():
            self.queue(conn, event, "Этот аккаунт уже подключён. Отключите его в прежнем кабинете перед новой привязкой.")
            return
        conn.execute("UPDATE bot_pairings SET external_id=?,chat_id=?,display_name=? WHERE token_hash=?",
                     (event.external_id, event.chat_id, event.display_name, digest(token)))
        self.queue(conn, event, "Для завершения подключения вернитесь в кабинет → Мессенджеры. "
                   "Введите код подтверждения: " + row["confirmation"] + ". Никому не передавайте этот код.")

    def confirm_pairing(self, conn, user, provider, confirmation):
        row = conn.execute("SELECT * FROM bot_pairings WHERE user_id=? AND provider=? AND expires_at>?",
                           (user["id"], provider, time.time())).fetchone()
        if not row or not row["external_id"]:
            raise HTTPException(409, "Сначала отправьте команду подключения боту")
        if not secrets.compare_digest(row["confirmation"], confirmation.strip().upper()):
            raise HTTPException(422, "Неверный код подтверждения")
        if conn.execute("SELECT 1 FROM bot_links WHERE provider=? AND (external_id=? OR user_id=?)",
                        (provider, row["external_id"], user["id"])).fetchone():
            raise HTTPException(409, "Аккаунт уже подключён. Сначала отключите прежнюю привязку.")
        cursor = conn.execute("""INSERT INTO bot_links(user_id,provider,external_id,chat_id,display_name,created_at)
            VALUES(?,?,?,?,?,?)""", (user["id"], provider, row["external_id"], row["chat_id"], row["display_name"], self.desk.now()))
        conn.execute("INSERT OR IGNORE INTO bot_preferences(user_id,channel) VALUES(?,?)", (user["id"], provider))
        conn.execute("DELETE FROM bot_pairings WHERE token_hash=?", (row["token_hash"],))
        link = conn.execute("SELECT * FROM bot_links WHERE id=?", (cursor.lastrowid,)).fetchone()
        self.menu(conn, link, user, "Подключение подтверждено. ")
        return {"ok": True}

    def unlink(self, conn, user, provider):
        conn.execute("DELETE FROM bot_pairings WHERE user_id=? AND provider=?", (user["id"], provider))
        conn.execute("DELETE FROM bot_links WHERE user_id=? AND provider=?", (user["id"], provider))
        remaining = conn.execute("SELECT provider FROM bot_links WHERE user_id=? ORDER BY id", (user["id"],)).fetchone()
        conn.execute("UPDATE bot_preferences SET channel=? WHERE user_id=? AND channel IN (?, 'both')",
                     (remaining["provider"] if remaining else "off", user["id"], provider))
        return {"ok": True}

    def preference(self, conn, user, channel):
        if channel not in (*PROVIDERS, "both", "off"):
            raise HTTPException(422, "Неизвестный канал")
        linked = {r["provider"] for r in conn.execute("SELECT provider FROM bot_links WHERE user_id=?", (user["id"],))}
        required = set(PROVIDERS) if channel == "both" else {channel} if channel != "off" else set()
        if not required.issubset(linked):
            raise HTTPException(409, "Сначала подключите выбранные мессенджеры")
        conn.execute("INSERT INTO bot_preferences(user_id,channel) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET channel=excluded.channel",
                     (user["id"], channel))

    def state(self, conn, link):
        row = conn.execute("SELECT data FROM bot_states WHERE link_id=? AND expires_at>?", (link["id"], time.time())).fetchone()
        return json.loads(row["data"]) if row else {}

    def set_state(self, conn, link, state):
        conn.execute("INSERT INTO bot_states VALUES(?,?,?) ON CONFLICT(link_id) DO UPDATE SET data=excluded.data,expires_at=excluded.expires_at",
                     (link["id"], encode(state), time.time() + 86400))

    def button(self, conn, link, text, action, **data):
        token = secrets.token_urlsafe(18)
        conn.execute("INSERT INTO bot_actions VALUES(?,?,?,?)", (token, link["id"], encode({"action": action, **data}), time.time() + 604800))
        return {"text": text, "token": token}

    def queue(self, conn, target, text, buttons=None, context=None, notification=False, ack=None):
        if hasattr(target, "provider"):
            provider, chat_id, link_id = target.provider, target.chat_id, None
        else:
            provider, chat_id, link_id = target["provider"], target["chat_id"], target["id"]
        # Split long text without losing the remainder. Buttons belong to the last part.
        chunks = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [""]
        for index, chunk in enumerate(chunks):
            payload = {"text": chunk, "buttons": buttons or [] if index == len(chunks) - 1 else []}
            if ack:
                payload = {"ack": ack}
            stamp = time.time()
            conn.execute("""INSERT INTO bot_outbox(provider,chat_id,link_id,payload,context_kind,context_id,notification,available_at,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", (provider, chat_id, link_id, encode(payload), context[0] if context else None,
                                               context[1] if context else None, int(notification), stamp, stamp))

    def menu(self, conn, link, user, prefix=""):
        if user["role"] != "customer":
            self.queue(conn, link, prefix + "Работайте с заявками в веб-кабинете. Здесь будут уведомления.",
                       [[{"text": "Открыть кабинет", "url": public_url()}],
                        [self.button(conn, link, "Настройки уведомлений", "settings")]])
            return
        self.queue(conn, link, prefix + "Выберите действие. /cancel отменяет текущий ввод.", [
            [self.button(conn, link, "Мои заявки", "tickets"), self.button(conn, link, "Создать заявку", "new")],
            [self.button(conn, link, "Написать компании", "chat")],
            [self.button(conn, link, "Уведомления", "notifications"), self.button(conn, link, "Настройки", "settings")]])

    def tickets(self, conn, link, user, offset=0, select=False):
        rows = conn.execute("SELECT id,title,status FROM tickets WHERE customer_id=? ORDER BY updated_at DESC,id DESC LIMIT 9 OFFSET ?",
                            (user["id"], offset)).fetchall()
        state = self.state(conn, link)
        buttons = [[self.button(conn, link, f"№{r['id']} · {r['title'][:50]}", "destination" if select else "ticket",
                                kind="ticket", record=r["id"], nonce=state.get("nonce"))] for r in rows[:8]]
        if len(rows) > 8:
            buttons.append([self.button(conn, link, "Далее", "tickets", offset=offset + 8, select=select)])
        buttons.append([self.button(conn, link, "Меню", "menu")])
        self.queue(conn, link, "Выберите заявку для сообщения:" if select else "Ваши заявки:" if rows else "Заявок пока нет.", buttons)

    def ticket(self, conn, link, user, ticket_id):
        t = self.desk.ticket_for(conn, ticket_id, user)
        e = self.desk.latest_estimate(conn, ticket_id)
        text = f"Заявка №{t['id']} · {t['title']}\n{t['description']}\n\nСледующий шаг: {self.desk.customer_next_step(t, e)}"
        buttons = [[self.button(conn, link, "Переписка", "history", kind="ticket", record=ticket_id)]]
        if t["status"] != "closed":
            buttons.append([self.button(conn, link, f"Ответить по заявке №{ticket_id}", "reply", kind="ticket", record=ticket_id)])
        if e and e["effort_minutes"] is not None:
            names = {"pending": "ожидает решения", "approved": "одобрена", "rejected": "отклонена", "revision_requested": "на корректировке"}
            text += f"\n\nОценка, версия {e['version']}: {hours(e['effort_minutes'])}. {names.get(e['state'], e['state'])}\n{e['note']}"
            if e["state"] == "pending" and t["status"] != "closed":
                buttons += [[self.button(conn, link, label, "decision", ticket=ticket_id, estimate=e["id"], decision=decision)]
                            for label, decision in [("Одобрить", "approve"), ("Запросить корректировку", "request_revision"), ("Отклонить", "reject")]]
        if t["status"] == "done" and self.desk.customer_can_decide(conn, t, user):
            buttons += [[self.button(conn, link, "Принять работу", "acceptance", ticket=ticket_id, decision="accept")],
                        [self.button(conn, link, "Вернуть на доработку", "acceptance", ticket=ticket_id, decision="return")]]
        if self.desk.customer_can_decline(conn, t, user):
            buttons.append([self.button(conn, link, "Заявка не нужна", "decline", ticket=ticket_id)])
        buttons.append([self.button(conn, link, "Меню", "menu")])
        self.queue(conn, link, text, buttons, ("ticket", ticket_id))

    def chat(self, conn, link, user):
        chat = self.desk.create_chat_service(conn, user)
        self.set_state(conn, link, {"mode": "reply", "kind": "chat", "record": chat["id"]})
        audience = "Все участники вашей компании и команда поддержки видят переписку." if chat["organization_id"] else "Личный диалог с командой поддержки."
        self.queue(conn, link, f"Общий чат: {chat['customer_name']}. {audience} Напишите сообщение. /cancel — отменить.",
                   [[self.button(conn, link, "История чата", "history", kind="chat", record=chat["id"])]], ("chat", chat["id"]))

    def check_context(self, conn, user, kind, record):
        if kind == "ticket":
            return self.desk.ticket_for(conn, record, user)
        if kind == "chat":
            return self.desk.chat_for(conn, record, user)
        raise HTTPException(422, "Неизвестный диалог")

    def history(self, conn, link, user, kind, record, before=None):
        record = self.check_context(conn, user, kind, record)["id"]
        table, key = ("messages", "ticket_id") if kind == "ticket" else ("chat_messages", "chat_id")
        rows = conn.execute(f"""SELECT m.*,u.name,u.role AS author_role FROM {table} m JOIN users u ON u.id=m.author_id
            WHERE m.{key}=? AND m.id<? ORDER BY m.id DESC LIMIT 6""", (record, before or 9223372036854775807)).fetchall()
        for row in reversed(rows[:5]):
            row = dict(row)
            if user["role"] == "customer" and row["author_role"] != "customer":
                row["name"] = self.desk.SUPPORT_NAME
            self.queue(conn, link, f"{'Заявка №' + str(record) if kind == 'ticket' else 'Общий чат'}\n{row['name']} · {row['created_at'][:16]}\n{row['body']}", context=(kind, record))
        buttons = [[self.button(conn, link, "Ответить", "reply", kind=kind, record=record)]]
        if len(rows) > 5:
            buttons.append([self.button(conn, link, "Более ранние сообщения", "history", kind=kind, record=record, before=rows[4]["id"])])
        self.queue(conn, link, "Сообщений пока нет." if not rows else "История переписки.", buttons, (kind, record))

    def send_message(self, conn, link, user, kind, record, text, request_id):
        data = self.desk.MessageCreate(body=text, request_id=request_id)
        if kind == "ticket":
            self.desk.add_message_service(conn, user, record, data)
        else:
            self.desk.add_chat_message_service(conn, user, record, data)
        self.set_state(conn, link, {})
        self.queue(conn, link, f"Сообщение отправлено {'по заявке №' + str(record) if kind == 'ticket' else 'в общий чат'}.",
                   [[self.button(conn, link, "Написать ещё", "reply", kind=kind, record=record),
                     self.button(conn, link, "Меню", "menu")]], (kind, record))

    def draft_preview(self, conn, link, state):
        state["mode"] = "draft_confirm"
        self.set_state(conn, link, state)
        self.queue(conn, link, f"Проверьте заявку:\n{state['title']}\n\n{state['description']}", [
            [self.button(conn, link, "Отправить заявку", "submit", nonce=state["nonce"])],
            [self.button(conn, link, "Изменить тему", "edit", field="title", nonce=state["nonce"]),
             self.button(conn, link, "Изменить описание", "edit", field="description", nonce=state["nonce"])],
            [self.button(conn, link, "Отмена", "cancel")]])

    def show_settings(self, conn, link, user):
        info = self.settings(conn, user)
        labels = {"telegram": "Telegram", "max": "MAX", "both": "Оба мессенджера", "off": "Выключены"}
        available = {x["provider"] for x in info["links"]}
        channels = [p for p in PROVIDERS if p in available] + (["both"] if len(available) == 2 else []) + ["off"]
        self.queue(conn, link, "Уведомления: " + labels[info["channel"]] + ".\nПодключение и отключение аккаунтов — в кабинете.",
                   [[self.button(conn, link, labels[c], "preference", channel=c)] for c in channels] +
                   [[{"text": "Мессенджеры в кабинете", "url": public_url() + "/#messengers"}]])

    def notifications(self, conn, link, user):
        result = []
        for table, kind, key in [("notifications", "ticket", "ticket_id"), ("chat_notifications", "chat", "chat_id")]:
            for row in conn.execute(f"SELECT * FROM {table} WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],)):
                try:
                    self.check_context(conn, user, kind, row[key])
                except HTTPException:
                    continue
                result.append((row["created_at"], self.desk.customer_notification_text(row["text"], user), kind, row[key]))
        buttons = [[self.button(conn, link, item[1][:65], "ticket" if item[2] == "ticket" else "history", kind=item[2], record=item[3])]
                   for item in sorted(result, reverse=True)[:8]]
        self.queue(conn, link, "Последние уведомления:" if result else "Уведомлений пока нет.", buttons)

    def handle_action(self, conn, link, user, data):
        action = data["action"]
        state = self.state(conn, link)
        if action in ("menu", "cancel"):
            self.set_state(conn, link, {})
            return self.menu(conn, link, user, "Текущий ввод отменён. " if state else "")
        if action == "settings":
            return self.show_settings(conn, link, user)
        if action == "preference":
            self.preference(conn, user, data["channel"])
            return self.show_settings(conn, link, user)
        if user["role"] != "customer":
            return self.menu(conn, link, user)
        if action == "tickets":
            return self.tickets(conn, link, user, data.get("offset", 0), data.get("select", False))
        if action == "ticket":
            return self.ticket(conn, link, user, data["record"])
        if action == "chat":
            return self.chat(conn, link, user)
        if action == "notifications":
            return self.notifications(conn, link, user)
        if action == "history":
            return self.history(conn, link, user, data["kind"], data["record"], data.get("before"))
        if action == "reply":
            self.check_context(conn, user, data["kind"], data["record"])
            self.set_state(conn, link, {"mode": "reply", "kind": data["kind"], "record": data["record"]})
            return self.queue(conn, link, f"Напишите сообщение {'по заявке №' + str(data['record']) if data['kind'] == 'ticket' else 'в общий чат'}. /cancel — отменить.", context=(data["kind"], data["record"]))
        if action == "new":
            self.set_state(conn, link, {"mode": "draft_title", "nonce": secrets.token_hex(8)})
            return self.queue(conn, link, "Введите тему заявки (3–140 символов). /cancel — отменить.")
        if action in ("edit", "submit", "destination"):
            if not state.get("nonce") or state["nonce"] != data.get("nonce"):
                raise HTTPException(409, "Эта кнопка устарела. Откройте меню командой /start.")
            if action == "destination":
                if state.get("mode") != "destination":
                    raise HTTPException(409, "Сообщение уже отправлено или отменено")
                kind = data["kind"]
                record = self.desk.create_chat_service(conn, user)["id"] if kind == "chat" else data["record"]
                return self.send_message(conn, link, user, kind, record, state["text"], state["request_id"])
            if state.get("mode") != "draft_confirm":
                raise HTTPException(409, "Сначала завершите ввод заявки")
            if action == "edit":
                state["mode"] = "draft_" + data["field"]
                self.set_state(conn, link, state)
                return self.queue(conn, link, "Введите новую тему:" if data["field"] == "title" else "Введите новое описание:")
            ticket = self.desk.add_ticket_service(conn, user, self.desk.TicketCreate(title=state["title"], description=state["description"]))
            self.set_state(conn, link, {})
            return self.ticket(conn, link, user, ticket["id"])
        if action in ("decision", "confirm_decision"):
            self.desk.ticket_for(conn, data["ticket"], user)
            estimate = self.desk.latest_estimate(conn, data["ticket"])
            if not estimate or estimate["id"] != data["estimate"] or estimate["state"] != "pending" or estimate["effort_minutes"] is None:
                self.queue(conn, link, "Оценка уже изменена или рассмотрена. Показываю актуальное состояние.")
                return self.ticket(conn, link, user, data["ticket"])
            if action == "confirm_decision":
                decision = self.desk.EstimateDecision(estimate_id=data["estimate"], action=data["decision"])
                self.desk.decide_estimate_service(conn, user, data["ticket"], decision)
                self.set_state(conn, link, {})
                return self.ticket(conn, link, user, data["ticket"])
            if data["decision"] == "request_revision":
                self.set_state(conn, link, {"mode": "revision_comment", "ticket": data["ticket"], "estimate": data["estimate"]})
                return self.queue(conn, link, "Напишите пожелания к оценке (до 3000 символов). На следующем шаге можно предложить число часов.")
            return self.queue(conn, link, f"{'Одобрить' if data['decision'] == 'approve' else 'Отклонить'} оценку заявки №{data['ticket']}?\nВерсия {estimate['version']} · {hours(estimate['effort_minutes'])}.\nОдобрение часов не списывает деньги.",
                              [[self.button(conn, link, "Подтвердить", "confirm_decision", ticket=data["ticket"], estimate=data["estimate"], decision=data["decision"])],
                               [self.button(conn, link, "Вернуться к заявке", "ticket", record=data["ticket"])]], ("ticket", data["ticket"]))
        if action in ("acceptance", "confirm_acceptance"):
            t = self.desk.ticket_for(conn, data["ticket"], user)
            if t["status"] != "done":
                self.queue(conn, link, "Работа уже принята или ещё не отправлена на проверку. Показываю актуальное состояние.")
                return self.ticket(conn, link, user, data["ticket"])
            if action == "confirm_acceptance":
                self.desk.accept_work_service(conn, user, data["ticket"], self.desk.AcceptanceDecision(action="accept"))
                self.set_state(conn, link, {})
                self.queue(conn, link, f"Работа по заявке №{data['ticket']} принята, заявка закрыта. Спасибо!")
                return self.ticket(conn, link, user, data["ticket"])
            if data["decision"] == "return":
                self.set_state(conn, link, {"mode": "return_comment", "ticket": data["ticket"]})
                return self.queue(conn, link, "Напишите, что нужно доработать (до 3000 символов). /cancel — отменить.")
            return self.queue(conn, link, f"Принять работу по заявке №{data['ticket']}? Заявка будет закрыта.",
                              [[self.button(conn, link, "Принять", "confirm_acceptance", ticket=data["ticket"])],
                               [self.button(conn, link, "Вернуться к заявке", "ticket", record=data["ticket"])]], ("ticket", data["ticket"]))
        if action in ("decline", "confirm_decline"):
            t = self.desk.ticket_for(conn, data["ticket"], user)
            if not self.desk.customer_can_decline(conn, t, user):
                self.queue(conn, link, "От этой заявки уже нельзя отказаться. Показываю актуальное состояние.")
                return self.ticket(conn, link, user, data["ticket"])
            if action == "confirm_decline":
                self.desk.decline_ticket_service(conn, user, data["ticket"], self.desk.TicketDecline())
                self.queue(conn, link, f"Заявка №{data['ticket']} закрыта — команда получила уведомление.")
                return self.ticket(conn, link, user, data["ticket"])
            return self.queue(conn, link, f"Отказаться от заявки №{data['ticket']}? Она закроется без работы и оплаты.",
                              [[self.button(conn, link, "Да, не нужна", "confirm_decline", ticket=data["ticket"])],
                               [self.button(conn, link, "Вернуться к заявке", "ticket", record=data["ticket"])]], ("ticket", data["ticket"]))
        raise HTTPException(422, "Неизвестное действие. Откройте /start.")

    def handle_text(self, conn, link, user, event):
        text = event.text.strip()
        if text in ("/start", "/help", "/cancel"):
            return self.handle_action(conn, link, user, {"action": "cancel" if text == "/cancel" else "menu"})
        if text == "/settings":
            return self.show_settings(conn, link, user)
        if user["role"] != "customer":
            return self.menu(conn, link, user)
        if event.unsupported:
            return self.queue(conn, link, "Пока поддерживаются текстовые сообщения. Вложения и голосовые не отправлены. Пожалуйста, опишите задачу текстом.")
        if not text or len(text) > 10000:
            raise HTTPException(422, "Сообщение должно содержать от 1 до 10000 символов")
        if text.startswith("/"):
            return self.queue(conn, link, "Неизвестная команда. /start — меню, /cancel — отмена, /settings — настройки.")
        state = self.state(conn, link)
        mode = state.get("mode")
        if mode in ("draft_title", "draft_description", "draft_confirm"):
            if mode == "draft_confirm":
                return self.draft_preview(conn, link, state)
            field = "title" if mode == "draft_title" else "description"
            if not (3 if field == "title" else 5) <= len(text) <= (140 if field == "title" else 10000):
                raise HTTPException(422, "Тема: 3–140 символов. Описание: 5–10000 символов. Повторите ввод.")
            state[field] = text
            if state.get("description") and state.get("title"):
                return self.draft_preview(conn, link, state)
            state["mode"] = "draft_description"
            self.set_state(conn, link, state)
            return self.queue(conn, link, "Опишите задачу (5–10000 символов).")
        if mode in ("revision_comment", "revision_hours"):
            if mode == "revision_comment":
                if len(text) > 3000:
                    raise HTTPException(422, "Комментарий должен быть не длиннее 3000 символов")
                state.update(mode="revision_hours", comment=text)
                self.set_state(conn, link, state)
                return self.queue(conn, link, "Предложите число часов, например 2,5. Напишите «пропустить», чтобы оставить только комментарий.")
            minutes = None
            if text.lower() != "пропустить":
                try:
                    value = Decimal(text.replace(",", ".")) * 60
                    if not value.is_finite() or value != value.to_integral_value() or not 1 <= value <= 100000:
                        raise ValueError()
                    minutes = int(value)
                except (InvalidOperation, ValueError):
                    raise HTTPException(422, "Укажите положительное число часов с точностью до минуты или «пропустить»") from None
            data = self.desk.EstimateDecision(estimate_id=state["estimate"], action="request_revision", comment=state["comment"], proposed_effort_minutes=minutes)
            self.desk.decide_estimate_service(conn, user, state["ticket"], data)
            self.set_state(conn, link, {})
            return self.ticket(conn, link, user, state["ticket"])
        if mode == "return_comment":
            if len(text) > 3000:
                raise HTTPException(422, "Комментарий должен быть не длиннее 3000 символов")
            self.desk.accept_work_service(conn, user, state["ticket"], self.desk.AcceptanceDecision(action="return", comment=text))
            self.set_state(conn, link, {})
            self.queue(conn, link, f"Заявка №{state['ticket']} возвращена на доработку. Команда получила ваш комментарий.")
            return self.ticket(conn, link, user, state["ticket"])
        request_id = "bot-" + digest(event.provider + ":" + event.event_id)
        if event.reply_id:
            ref = conn.execute("SELECT * FROM bot_sent WHERE provider=? AND chat_id=? AND message_id=? AND link_id=?",
                               (event.provider, event.chat_id, event.reply_id, link["id"])).fetchone()
            if ref:
                return self.send_message(conn, link, user, ref["context_kind"], ref["context_id"], text, request_id)
            # Never fall through into a remembered target after an unrecognized reply.
            mode = None
        if mode == "reply":
            return self.send_message(conn, link, user, state["kind"], state["record"], text, request_id)
        if mode == "destination":
            return self.queue(conn, link, "Предыдущее сообщение ещё ожидает выбора адресата. Новое не отправлено. Выберите адресата или /cancel.")
        nonce = secrets.token_hex(8)
        self.set_state(conn, link, {"mode": "destination", "text": text, "request_id": request_id, "nonce": nonce})
        self.queue(conn, link, "Куда отправить это сообщение?", [
            [self.button(conn, link, "В общий чат", "destination", kind="chat", nonce=nonce)],
            [self.button(conn, link, "Выбрать заявку", "tickets", select=True)],
            [self.button(conn, link, "Отмена", "cancel")]])

    def receive(self, provider, update):
        event = normalize(provider, update)
        if not event:
            return {"ok": True, "ignored": True}
        with self.desk.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM bot_updates WHERE provider=? AND event_id=?", (provider, event.event_id)).fetchone():
                return {"ok": True, "duplicate": True}
            conn.execute("INSERT INTO bot_updates VALUES(?,?,?)", (provider, event.event_id, time.time()))
            if event.callback_id:
                self.queue(conn, event, "", ack=event.callback_id)
            link = conn.execute("SELECT * FROM bot_links WHERE provider=? AND external_id=? AND chat_id=?",
                                (provider, event.external_id, event.chat_id)).fetchone()
            if event.stopped:
                if link:
                    conn.execute("UPDATE bot_links SET enabled=0 WHERE id=?", (link["id"],))
                return {"ok": True}
            if event.text.startswith("/link "):
                self.claim_pairing(conn, event, event.text.split(maxsplit=1)[1].strip())
                return {"ok": True}
            user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (link["user_id"],)).fetchone() if link else None
            if not user:
                self.queue(conn, event, "Войдите или зарегистрируйтесь в кабинете, откройте «Мессенджеры» и подключите бота.",
                           [[{"text": "Открыть кабинет", "url": public_url()}]] if public_url() else [])
                return {"ok": True}
            conn.execute("UPDATE bot_links SET enabled=1 WHERE id=?", (link["id"],))
            conn.execute("SAVEPOINT bot_action")
            try:
                if event.callback_id:
                    row = conn.execute("SELECT data FROM bot_actions WHERE token=? AND link_id=? AND expires_at>?",
                                       (event.action, link["id"], time.time())).fetchone()
                    if not row:
                        raise HTTPException(409, "Кнопка устарела или недоступна. Откройте /start.")
                    self.handle_action(conn, link, user, json.loads(row["data"]))
                else:
                    self.handle_text(conn, link, user, event)
            except (HTTPException, ValidationError) as exc:
                conn.execute("ROLLBACK TO bot_action")
                self.queue(conn, link, str(exc.detail) if isinstance(exc, HTTPException) else "Проверьте длину и формат введённых данных. /cancel — отменить.")
            finally:
                conn.execute("RELEASE bot_action")
        return {"ok": True}

    def enqueue_notification(self, conn, user_id, kind, record, event_kind, text):
        links = conn.execute("""SELECT l.* FROM bot_links l JOIN bot_preferences p ON p.user_id=l.user_id
            WHERE l.user_id=? AND l.enabled=1 AND (p.channel=l.provider OR p.channel='both')""", (user_id,)).fetchall()
        user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not user:
            return
        if event_kind == "message":
            table, key = ("messages", "ticket_id") if kind == "ticket" else ("chat_messages", "chat_id")
            msg = conn.execute(f"SELECT m.body,m.author_id,u.name,u.role AS author_role FROM {table} m JOIN users u ON u.id=m.author_id WHERE {key}=? ORDER BY m.id DESC LIMIT 1", (record,)).fetchone()
            if msg and msg["author_id"] == user_id:
                return
            if msg:
                msg = dict(msg)
                if user["role"] == "customer" and msg["author_role"] != "customer":
                    msg["name"] = self.desk.SUPPORT_NAME
                text += f"\n{msg['name']}:\n{msg['body']}"
        if event_kind == "estimate":
            e = self.desk.latest_estimate(conn, record)
            if e and e["effort_minutes"] is not None:
                text += f"\nВерсия {e['version']} · {hours(e['effort_minutes'])}\n{e['note']}"
        for link in links:
            if user["role"] == "customer":
                buttons = [[self.button(conn, link, "Открыть заявку" if kind == "ticket" else "Открыть чат",
                                         "ticket" if kind == "ticket" else "history", kind=kind, record=record)]]
                if event_kind == "ticket_created":
                    ticket = conn.execute("SELECT ticket_id FROM chat_ticket_links WHERE chat_id=? ORDER BY id DESC LIMIT 1", (record,)).fetchone()
                    if ticket:
                        buttons.insert(0, [self.button(conn, link, "Перейти в созданную заявку", "ticket", record=ticket["ticket_id"])])
            else:
                buttons = [[{"text": "Открыть в кабинете", "url": public_url() + f"/#{kind}/{record}"}]]
            self.queue(conn, link, text, buttons, (kind, record), notification=True)
