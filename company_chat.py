"""Company-wide chat scope and lossless migration of former account chats."""


SELECT = """SELECT c.*,COALESCE(o.name,u.name) AS customer_name,
    o.name AS organization_name,a.name AS assignee_name
    FROM chats c JOIN users u ON u.id=c.customer_id
    LEFT JOIN organizations o ON o.id=c.organization_id
    LEFT JOIN users a ON a.id=c.assignee_id"""


def init_schema(conn):
    if 'organization_id' not in {r['name'] for r in conn.execute('PRAGMA table_info(chats)')}:
        # Remove the old UNIQUE(customer_id): a former member can start a new chat
        # without taking the previous company's conversation with them.
        conn.commit()
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''CREATE TABLE chats_company (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES users(id),
                organization_id INTEGER REFERENCES organizations(id),
                assignee_id INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            conn.execute('''INSERT INTO chats_company(id,customer_id,assignee_id,created_at,updated_at)
                SELECT id,customer_id,assignee_id,created_at,updated_at FROM chats''')
            conn.execute('DROP TABLE chats')
            conn.execute('ALTER TABLE chats_company RENAME TO chats')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_chats_assignee ON chats(assignee_id)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_company ON chats(organization_id) WHERE organization_id IS NOT NULL')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_personal ON chats(customer_id) WHERE organization_id IS NULL')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_aliases (
        old_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE)''')
    for org in conn.execute('SELECT id FROM organizations').fetchall():
        sync_organization(conn, org['id'])


def sync_organization(conn, organization_id):
    """Adopt/merge existing member chats; never move another company's history."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute('''SELECT c.* FROM chats c WHERE c.organization_id=? OR
        (c.organization_id IS NULL AND c.customer_id IN
         (SELECT user_id FROM organization_members WHERE organization_id=?))
        ORDER BY c.organization_id IS NULL,c.id''', (organization_id, organization_id)).fetchall()
    if not rows:
        return None
    target = rows[0]
    if target['organization_id'] != organization_id:
        conn.execute('UPDATE chats SET organization_id=? WHERE id=?', (organization_id, target['id']))
    for old in rows[1:]:
        # Preserve both messages even if independently generated request IDs collide.
        conn.execute('''UPDATE chat_messages SET request_id=request_id || ':merged:' || id
            WHERE chat_id=? AND EXISTS (SELECT 1 FROM chat_messages t
                WHERE t.chat_id=? AND t.author_id=chat_messages.author_id
                AND t.request_id=chat_messages.request_id)''', (old['id'], target['id']))
        for table in ('chat_messages', 'chat_notifications', 'attachments', 'chat_ticket_links', 'email_tokens'):
            conn.execute(f'UPDATE {table} SET chat_id=? WHERE chat_id=?', (target['id'], old['id']))
        # A read marker from an individual history cannot describe the merged history.
        conn.execute("DELETE FROM message_reads WHERE kind='chat' AND record_id IN (?,?)", (target['id'], old['id']))
        conn.execute('UPDATE chat_aliases SET chat_id=? WHERE chat_id=?', (target['id'], old['id']))
        conn.execute('INSERT OR REPLACE INTO chat_aliases(old_id,chat_id) VALUES(?,?)', (old['id'], target['id']))
        conn.execute('''UPDATE chats SET created_at=MIN(created_at,?),updated_at=MAX(updated_at,?),
            assignee_id=COALESCE(assignee_id,?) WHERE id=?''',
            (old['created_at'], old['updated_at'], old['assignee_id'], target['id']))
        conn.execute('DELETE FROM chats WHERE id=?', (old['id'],))
    return target['id']


def resolve(conn, chat_id):
    alias = conn.execute('SELECT chat_id FROM chat_aliases WHERE old_id=?', (chat_id,)).fetchone()
    return alias['chat_id'] if alias else chat_id


def customers(conn, chat):
    if chat['organization_id'] is not None:
        return {r['user_id'] for r in conn.execute('''SELECT m.user_id FROM organization_members m
            JOIN users u ON u.id=m.user_id WHERE m.organization_id=? AND u.active=1''',
            (chat['organization_id'],))}
    return {chat['customer_id']}


def can_access(conn, chat, user):
    if chat['organization_id'] is not None:
        return bool(conn.execute('SELECT 1 FROM organization_members WHERE organization_id=? AND user_id=?',
                                 (chat['organization_id'], user['id'])).fetchone())
    return chat['customer_id'] == user['id']
