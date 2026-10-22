import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient

_import_dir = tempfile.TemporaryDirectory()
os.environ.setdefault('APP_DB', str(Path(_import_dir.name) / 'import.db'))
os.environ['BACKGROUND_JOBS'] = '0'
import app as service
import payroll


class PayrollTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = service.DB_PATH
        service.DB_PATH = Path(self.temp.name) / 'payroll.db'
        service.init_db()
        self.clients = {}
        self.ids = {}
        with service.db() as conn:
            for key, role in [('admin','admin'),('worker','employee'),('other','employee'),('client','customer')]:
                service.create_user(conn, key, f'{key}@payroll.test', 'Password123!', role)
                self.ids[key] = conn.execute('SELECT id FROM users WHERE email=?', (f'{key}@payroll.test',)).fetchone()[0]
        for key in self.ids:
            client = TestClient(service.app)
            self.assertEqual(client.post('/api/login', json={'email':f'{key}@payroll.test','password':'Password123!'}).status_code, 200)
            self.clients[key] = client
        self.admin = self.clients['admin']
        self.worker = self.clients['worker']
        self.day = payroll.work_today().isoformat()
        ticket = self.clients['client'].post('/api/tickets', json={'title':'Проверка выплат','description':'Фактическая работа по заявке'}).json()
        self.ticket = ticket['id']
        self.admin.patch(f'/api/tickets/{self.ticket}/assignee', json={'assignee_id':self.ids['worker']})
        quote = self.worker.post(f'/api/tickets/{self.ticket}/estimates', json={'effort_minutes':600,'assessment_minutes':10}).json()
        self.admin.post(f'/api/tickets/{self.ticket}/estimates/{quote["id"]}/pm-review', json={'action':'send_to_customer'})
        self.clients['client'].post(f'/api/tickets/{self.ticket}/estimates/decision', json={'estimate_id':quote['id'],'action':'approve'})
        self.worker.patch(f'/api/tickets/{self.ticket}/status', json={'status':'working'})

    def tearDown(self):
        for client in self.clients.values():
            client.close()
        service.DB_PATH = self.old_path
        self.temp.cleanup()

    def entry(self, minutes=90, day=None, note='Выполненная работа'):
        r = self.worker.post(f'/api/tickets/{self.ticket}/time-entries', json={'minutes':minutes,'note':note,'work_date':day or self.day})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()['id']

    def rate(self, cents=2000):
        r = self.admin.post(f'/api/payroll/rates/{self.ids["worker"]}', json={'cents_per_hour':cents})
        self.assertEqual(r.status_code,200,r.text)

    def review(self, entry, action='approve', reason=''):
        return self.admin.post(f'/api/payroll/entries/{entry}/review', json={'action':action,'reason':reason})

    def overview(self, client=None, **params):
        return (client or self.admin).get('/api/payroll', params={'period_start':self.day,'period_end':self.day,**params})

    def payload(self, ids, total=3000):
        return {'employee_id':self.ids['worker'],'period_start':self.day,'period_end':self.day,'entry_ids':ids,'expected_total_cents':total,'request_id':'test-act-unique-1'}

    def test_approval_rate_snapshot_act_and_payment(self):
        entry = self.entry(note='<script>alert(1)</script> Исправление интеграции')
        self.assertEqual(self.review(entry).status_code,409)
        self.rate()
        self.assertEqual(self.review(entry).status_code,200)
        self.rate(4000)
        self.assertEqual(self.review(entry).status_code,200)
        row = self.overview().json()['entries'][0]
        self.assertEqual((row['cents_per_hour'],row['amount_cents']),(2000,3000))
        payload = self.payload([entry])
        response = self.admin.post('/api/payroll/acts',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        act = response.json()
        self.assertEqual((act['total_cents'],act['total_minutes']),(3000,90))
        retry = self.admin.post('/api/payroll/acts',json=payload)
        self.assertEqual(retry.json()['id'],act['id'])
        payload['request_id']='another-request-key'
        self.assertEqual(self.admin.post('/api/payroll/acts',json=payload).status_code,409)
        self.assertEqual(self.review(entry,'reset').status_code,409)
        printed = self.worker.get(f'/api/payroll/acts/{act["id"]}/print')
        self.assertEqual(printed.status_code,200)
        self.assertIn('&lt;script&gt;',printed.text)
        self.assertNotIn('<script>',printed.text)
        paid = self.admin.post(f'/api/payroll/acts/{act["id"]}/paid').json()
        self.assertEqual(self.admin.post(f'/api/payroll/acts/{act["id"]}/paid').json()['paid_at'],paid['paid_at'])
        service.init_db()
        self.assertEqual(self.admin.get(f'/api/payroll/acts/{act["id"]}').json()['total_cents'],3000)

    def test_pending_rejected_and_period_boundaries(self):
        self.rate(1001)
        pending = self.entry(1)
        rejected = self.entry(1)
        approved = self.entry(1)
        yesterday = (payroll.work_today()-timedelta(days=1)).isoformat()
        outside = self.entry(1,yesterday)
        self.assertEqual(self.review(rejected,'reject').status_code,422)
        self.assertEqual(self.review(rejected,'reject','Неверное описание').status_code,200)
        self.review(approved)
        self.review(outside)
        self.assertEqual(self.overview().json()['entries'][0]['amount_cents'],17)
        for ids in ([pending],[rejected],[outside],[approved,approved]):
            self.assertEqual(self.admin.post('/api/payroll/acts',json=self.payload(ids,17)).status_code,409)
        self.assertEqual(self.admin.post('/api/payroll/acts',json=self.payload([approved],18)).status_code,409)
        self.assertEqual(self.admin.post('/api/payroll/acts',json=self.payload([approved],17)).status_code,201)
        self.assertEqual(self.review(rejected,'reset').status_code,200)
        self.assertEqual(self.review(rejected).status_code,200)
        future = (payroll.work_today()+timedelta(days=1)).isoformat()
        self.assertEqual(self.worker.post(f'/api/tickets/{self.ticket}/time-entries',json={'minutes':1,'note':'Будущая работа','work_date':future}).status_code,422)
        self.assertEqual(self.overview(period_start=future).status_code,422)

    def test_permissions_and_own_records_only(self):
        entry = self.entry()
        self.rate()
        self.review(entry)
        act = self.admin.post('/api/payroll/acts',json=self.payload([entry])).json()
        for key in ('worker','other','client'):
            client = self.clients[key]
            self.assertEqual(client.post(f'/api/payroll/rates/{self.ids["worker"]}',json={'cents_per_hour':5000}).status_code,403)
            self.assertEqual(client.post(f'/api/payroll/entries/{entry}/review',json={'action':'reset'}).status_code,403)
            self.assertEqual(client.post('/api/payroll/acts',json=self.payload([entry])).status_code,403)
            self.assertEqual(client.post(f'/api/payroll/acts/{act["id"]}/paid').status_code,403)
        self.assertEqual(self.overview(self.clients['client']).status_code,403)
        other = self.overview(self.clients['other'],employee_id=self.ids['worker']).json()
        self.assertEqual((other['entries'],other['acts']),([],[]))
        for path in ('', '/print'):
            self.assertEqual(self.clients['other'].get(f'/api/payroll/acts/{act["id"]}{path}').status_code,404)
        self.assertEqual(TestClient(service.app).get('/api/payroll',params={'period_start':self.day,'period_end':self.day}).status_code,401)

    def test_concurrent_act_creation_cannot_double_pay(self):
        entry = self.entry()
        self.rate()
        self.review(entry)
        def create(index):
            payload = {**self.payload([entry]),'request_id':f'concurrent-request-{index}'}
            return self.admin.post('/api/payroll/acts',json=payload).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(create,range(2))),[201,409])

    def test_legacy_dates_and_money_validation(self):
        entry = self.entry()
        with service.db() as conn:
            conn.execute("UPDATE time_entries SET work_date=NULL,created_at='2026-10-01T22:30:00+00:00' WHERE id=?",(entry,))
        service.init_db()
        self.assertEqual(self.overview(period_start='2026-10-02',period_end='2026-10-02').json()['entries'][0]['state'],'pending')
        for value in (0,-1,1.5,True,100000001):
            self.assertEqual(self.admin.post(f'/api/payroll/rates/{self.ids["worker"]}',json={'cents_per_hour':value}).status_code,422)

    def test_assessments_service_and_work_are_paid_once(self):
        self.rate(2500)
        work = self.entry(90)
        customer = self.clients['client']
        second = customer.post('/api/tickets',json={'title':'Повторные оценки','description':'Уточнение состава работ'}).json()['id']
        self.admin.patch(f'/api/tickets/{second}/assignee',json={'assignee_id':self.ids['worker']})
        for minutes, action in ((5,'reject'),(7,'request_revision'),(11,None)):
            estimate = self.worker.post(f'/api/tickets/{second}/estimates',json={'effort_minutes':60,'assessment_minutes':minutes}).json()
            if action:
                self.admin.post(f'/api/tickets/{second}/estimates/{estimate["id"]}/pm-review', json={'action':'send_to_customer'})
                result = customer.post(f'/api/tickets/{second}/estimates/decision',json={'estimate_id':estimate['id'],'action':action,'comment':'Уточнить оценку'})
                self.assertEqual(result.status_code,200,result.text)
        services = []
        for ticket, kind, minutes in ((self.ticket,'chat',30),(None,'call',12)):
            r = self.worker.post('/api/service-entries',json={'customer_id':self.ids['client'],'ticket_id':ticket,'kind':kind,'minutes':minutes,'note':'Обсуждение результатов'})
            self.assertEqual(r.status_code,201,r.text)
            services.append(r.json()['id'])
        rows = self.overview().json()['entries']
        self.assertEqual(len({r['id'] for r in rows}),7)
        self.assertEqual(sum(r['minutes'] for r in rows),165)
        self.assertEqual({r['state'] for r in rows},{'pending'})
        self.assertEqual(sum(r['minutes'] for r in rows if r['source_kind']=='assessment'),33)
        service_row = next(r for r in rows if r['source_kind']=='service' and r['source_id']==services[0])
        self.assertEqual(self.clients['other'].post(f'/api/payroll/entries/{service_row["id"]}/review',json={'action':'approve'}).status_code,403)
        self.assertEqual(self.review(service_row['id'],'reject','Уточнить содержание').status_code,200)
        self.assertEqual(self.worker.delete(f'/api/service-entries/{services[0]}').status_code,409)
        self.review(service_row['id'],'reset')
        for row in rows:
            self.assertEqual(self.review(row['id']).status_code,200)
        ready = self.overview().json()['entries']
        total = sum(r['amount_cents'] for r in ready)
        payload = self.payload([r['id'] for r in ready],total)
        act = self.admin.post('/api/payroll/acts',json=payload)
        self.assertEqual(act.status_code,201,act.text)
        self.assertEqual(act.json()['total_minutes'],165)
        self.assertEqual({r['source_kind'] for r in act.json()['items']},{'work','assessment','service'})
        self.assertTrue(any(r['ticket_id'] is None for r in act.json()['items']))
        self.assertEqual(self.worker.delete(f'/api/service-entries/{services[1]}').status_code,409)
        payload['request_id']='second-mixed-act-key'
        self.assertEqual(self.admin.post('/api/payroll/acts',json=payload).status_code,409)
        printed = self.admin.get(f'/api/payroll/acts/{act.json()["id"]}/print').text
        for word in ('Оценка заявки','Переписка','Созвон'):
            self.assertIn(word,printed)
        self.assertNotIn('#None',printed)

    def test_non_billable_meeting_publication_is_excluded(self):
        with service.db() as conn:
            conn.execute('''INSERT INTO service_entries(customer_id,ticket_id,author_id,kind,minutes,note,occurred_at,created_at,is_billable)
                VALUES(?,?,?,?,?,?,?,?,0)''', (self.ids['client'],self.ticket,self.ids['worker'],'meeting',30,'Публичные итоги',service.now(),service.now()))
        self.assertFalse(any(r['source_kind']=='service' for r in self.overview().json()['entries']))

    def test_upgrade_preserves_existing_paid_work_act(self):
        entry = self.entry()
        self.rate()
        self.review(entry)
        act = self.admin.post('/api/payroll/acts',json=self.payload([entry])).json()
        self.admin.post(f'/api/payroll/acts/{act["id"]}/paid')
        before = self.admin.get(f'/api/payroll/acts/{act["id"]}').json()
        # Reconstruct the shipped work-only schema, then run the actual migration.
        with service.db() as conn:
            conn.execute('ALTER TABLE payroll_act_items DROP COLUMN source_kind')
            conn.execute('ALTER TABLE payroll_act_items DROP COLUMN source_id')
            for table in ('payroll_reviews','payroll_audit','payroll_act_items'):
                sql = conn.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone()[0]
                sql = sql.replace('"'+table+'"',table+'_old',1).replace('REFERENCES payroll_sources(id)','REFERENCES time_entries(id)')
                if table=='payroll_act_items':
                    sql = sql.replace('ticket_id INTEGER,','ticket_id INTEGER NOT NULL,')
                conn.execute(sql)
                conn.execute(f'INSERT INTO {table}_old SELECT * FROM {table}')
                conn.execute(f'DROP TABLE {table}')
                conn.execute(f'ALTER TABLE {table}_old RENAME TO {table}')
            conn.execute('DROP TABLE payroll_sources')
        service.init_db()
        service.init_db()
        after = self.admin.get(f'/api/payroll/acts/{act["id"]}').json()
        self.assertEqual((before['total_cents'],before['paid_at'],before['items']),(after['total_cents'],after['paid_at'],after['items']))
        self.assertEqual(self.review(entry,'reset').status_code,409)


if __name__ == '__main__':
    unittest.main()
