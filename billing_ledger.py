"""Money is authoritative; minute balances are a display-only equivalent."""


def migrate(conn):
    ticket_columns = {r['name'] for r in conn.execute('PRAGMA table_info(tickets)')}
    if 'channel' not in ticket_columns:
        conn.execute("ALTER TABLE tickets ADD COLUMN channel TEXT NOT NULL DEFAULT 'web'")
    conn.execute("CREATE TABLE IF NOT EXISTS billing_migrations (name TEXT PRIMARY KEY)")
    if not conn.execute("SELECT 1 FROM billing_migrations WHERE name='rub_balance_v1'").fetchone():
        for table in ('organizations', 'customer_profiles'):
            conn.execute(f"UPDATE {table} SET deposit_balance_rub=ROUND(balance_minutes * hourly_rate_rub / 60.0)")
        conn.execute("INSERT INTO billing_migrations VALUES ('rub_balance_v1')")
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(customer_profiles)')}
    for name in ('bank_name', 'bik', 'bank_account', 'corr_account'):
        if name not in columns:
            conn.execute(f"ALTER TABLE customer_profiles ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(invoices)')}
    for name in ('qr_payload', 'performer_json', 'client_json'):
        if name not in columns:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def approved_amount(conn, ticket, rate):
    estimate = conn.execute("SELECT * FROM estimates WHERE ticket_id=? ORDER BY version DESC LIMIT 1", (ticket['id'],)).fetchone()
    if not estimate or estimate['state'] != 'approved':
        return 0
    amount = estimate['amount_rub']
    if amount is None:
        amount = round((estimate['effort_minutes'] or 0) * rate / 60)
    for extra in conn.execute("SELECT * FROM hour_requests WHERE ticket_id=? AND state='approved'", (ticket['id'],)):
        if not extra['bill_customer']:
            continue
        amount += extra['amount_rub'] if extra['amount_rub'] is not None else round((extra['customer_minutes'] or extra['minutes']) * rate / 60)
    return amount


def sync_reservations(conn):
    """Reserve agreed charges until an act posts them; credit balances may be negative."""
    conn.execute("INSERT OR IGNORE INTO customer_profiles(user_id,updated_at) SELECT id,created_at FROM users WHERE role='customer'")
    balances = {}
    for table, key in (('organizations', 'id'), ('customer_profiles', 'user_id')):
        for row in conn.execute(f'SELECT * FROM {table}'):
            balances[(table, row[key])] = [row['hourly_rate_rub'] or 3000, 0]
    for ticket in conn.execute('SELECT * FROM tickets').fetchall():
        table, client_id = ('organizations', ticket['organization_id']) if ticket['organization_id'] else ('customer_profiles', ticket['customer_id'])
        rate, _ = balances.get((table, client_id), [3000, 0])
        amount = 0 if ticket['act_invoice_id'] else approved_amount(conn, ticket, rate)
        status = 'charged' if ticket['act_invoice_id'] else ('reserved' if amount else 'unpaid')
        if ticket['held_amount_rub'] != amount or ticket['payment_status'] != status:
            conn.execute('UPDATE tickets SET held_amount_rub=?,payment_status=? WHERE id=?', (amount, status, ticket['id']))
        if (table, client_id) in balances:
            balances[(table, client_id)][1] += amount
    for (table, client_id), (rate, held) in balances.items():
        key = 'id' if table == 'organizations' else 'user_id'
        conn.execute(f'UPDATE {table} SET held_rub=?,balance_minutes=ROUND(deposit_balance_rub * 60.0 / ?) WHERE {key}=?', (held, rate, client_id))
