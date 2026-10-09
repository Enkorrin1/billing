"""Durable delivery worker. Run separately: python bot_worker.py run."""

import argparse
import json
import logging
import secrets
import time

from fastapi import HTTPException

from .providers import DeliveryError, ProviderClient, config, validate_config

log = logging.getLogger("bots.delivery")


def claim(engine, providers=None):
    stamp = time.time()
    with engine.desk.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE bot_outbox SET state='pending',lease_token=NULL WHERE state='sending' AND lease_until<?", (stamp,))
        # Callback acknowledgements are not chat messages and must not wait behind history pages.
        jobs = conn.execute("""SELECT * FROM bot_outbox o WHERE o.state='pending' AND o.available_at<=?
            AND (json_extract(o.payload,'$.ack') IS NOT NULL OR NOT EXISTS (
                SELECT 1 FROM bot_outbox earlier WHERE earlier.provider=o.provider AND earlier.chat_id=o.chat_id
                AND earlier.id<o.id AND earlier.state IN ('pending','sending')
                AND json_extract(earlier.payload,'$.ack') IS NULL))
            ORDER BY (json_extract(o.payload,'$.ack') IS NOT NULL) DESC,o.id LIMIT 100""", (stamp,)).fetchall()
        for row in jobs:
            if providers is not None and row["provider"] not in providers:
                continue
            if not config(row["provider"])["token"]:
                continue
            payload = json.loads(row["payload"])
            if row["link_id"]:
                link = conn.execute("SELECT * FROM bot_links WHERE id=? AND enabled=1", (row["link_id"],)).fetchone()
                user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (link["user_id"],)).fetchone() if link else None
                allowed = bool(user)
                if user and row["notification"]:
                    pref = conn.execute("SELECT channel FROM bot_preferences WHERE user_id=?", (user["id"],)).fetchone()
                    allowed = bool(pref and pref["channel"] in (row["provider"], "both"))
                if user and row["context_kind"]:
                    try:
                        engine.check_context(conn, user, row["context_kind"], row["context_id"])
                    except HTTPException:
                        allowed = False
                if not allowed:
                    conn.execute("UPDATE bot_outbox SET state='cancelled' WHERE id=?", (row["id"],))
                    continue
            if not payload.get("ack"):
                slot = conn.execute("SELECT next_at FROM bot_delivery_slots WHERE provider=? AND chat_id=?", (row["provider"], row["chat_id"])).fetchone()
                if slot and slot["next_at"] > stamp:
                    continue
                conn.execute("INSERT INTO bot_delivery_slots VALUES(?,?,?) ON CONFLICT(provider,chat_id) DO UPDATE SET next_at=excluded.next_at",
                             (row["provider"], row["chat_id"], stamp + 1.05))
            lease = secrets.token_hex(16)
            conn.execute("UPDATE bot_outbox SET state='sending',lease_until=?,lease_token=?,attempts=attempts+1 WHERE id=?", (stamp + 60, lease, row["id"]))
            return {**dict(row), "payload": payload, "lease_token": lease, "attempts": row["attempts"] + 1}
    return None


def deliver_one(engine, clients):
    job = claim(engine, clients)
    if not job:
        return False
    try:
        message_id = clients[job["provider"]].deliver(job["chat_id"], job["payload"])
    except DeliveryError as exc:
        terminal = exc.permanent or job["attempts"] >= 10 or bool(job["payload"].get("ack"))
        delay = max(exc.retry_after, min(2 ** job["attempts"], 3600))
        with engine.desk.db() as conn:
            conn.execute("""UPDATE bot_outbox SET state=?,available_at=?,last_error=?,lease_token=NULL
                WHERE id=? AND lease_token=?""", ("failed" if terminal else "pending", time.time() + delay, exc.code, job["id"], job["lease_token"]))
            if exc.blocked and job["link_id"]:
                conn.execute("UPDATE bot_links SET enabled=0 WHERE id=?", (job["link_id"],))
        log.warning("delivery_failed job=%s provider=%s code=%s terminal=%s", job["id"], job["provider"], exc.code, terminal)
        return True
    except (KeyError, TypeError, ValueError):
        with engine.desk.db() as conn:
            conn.execute("UPDATE bot_outbox SET state='failed',last_error='invalid_response' WHERE id=? AND lease_token=?", (job["id"], job["lease_token"]))
        log.error("invalid_provider_response job=%s provider=%s", job["id"], job["provider"])
        return True
    with engine.desk.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("UPDATE bot_outbox SET state='sent',last_error=NULL,lease_token=NULL WHERE id=? AND lease_token=?", (job["id"], job["lease_token"])).rowcount
        exists = conn.execute("SELECT 1 FROM bot_links WHERE id=?", (job["link_id"],)).fetchone()
        if changed and exists and message_id and job["context_kind"]:
            conn.execute("INSERT OR REPLACE INTO bot_sent VALUES(?,?,?,?,?,?)",
                         (job["provider"], job["chat_id"], message_id, job["link_id"], job["context_kind"], job["context_id"]))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "register", "check", "status", "retry-failed"])
    parser.add_argument("--provider", choices=["telegram", "max"])
    args = parser.parse_args()
    import app
    engine = app.bot_engine
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    if args.command == "status":
        with app.db() as conn:
            print([dict(r) for r in conn.execute("SELECT provider,state,COUNT(*) AS count FROM bot_outbox GROUP BY provider,state")])
        return
    if args.command == "retry-failed":
        with app.db() as conn:
            conn.execute("""UPDATE bot_outbox SET state='pending',attempts=0,available_at=?
                WHERE state='failed' AND json_extract(payload,'$.ack') IS NULL AND (? IS NULL OR provider=?)""", (time.time(), args.provider, args.provider))
        print("Failed messages scheduled for retry; current access and preferences will be checked.")
        return
    providers = [args.provider] if args.provider else [p for p in ("telegram", "max") if config(p)["token"]]
    if not providers:
        parser.error("Configure at least one bot; see .env.example and BOTS.md")
    clients = {}
    try:
        for p in providers:
            validate_config(p)
            clients[p] = ProviderClient(p)
        if args.command == "check":
            for p, client in clients.items():
                client.check_connection()
                print(f"{p}: bot API and webhook subscription OK; run the worker and verify a real conversation")
        elif args.command == "register":
            for p, client in clients.items():
                client.register_webhook()
                print(f"{p}: webhook registered")
        else:
            print("Bot delivery worker started. Ctrl+C to stop.", flush=True)
            while True:
                processed = deliver_one(engine, clients)
                time.sleep(0.06 if processed else 0.4)
    except KeyboardInterrupt:
        pass
    except (ValueError, DeliveryError) as exc:
        raise SystemExit(str(exc)) from None
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
