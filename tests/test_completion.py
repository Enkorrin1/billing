"""End-to-end regression coverage for the unfinished admin and ruble billing work."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ['BACKGROUND_JOBS'] = '0'
_initial = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ.setdefault('APP_DB', str(Path(_initial.name) / 'initial.db'))
from fastapi.testclient import TestClient
import app as service
import billing_ledger


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.old_billing = os.environ.get('BILLING_ENABLED')
        os.environ['BILLING_ENABLED'] = '1'
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_path = service.DB_PATH
        service.DB_PATH = Path(self.temp.name) / 'test.db'
        service.init_db()
        with service.db() as conn:
            self.admin_id = service.create_user(conn, 'Admin', 'admin@test.local', 'password123', 'admin')['id']
            self.client_id = service.create_user(conn, 'Client', 'client@test.local', 'password123', 'customer')['id']
            self.worker_id = service.create_user(conn, 'Worker', 'worker@test.local', 'password123', 'employee')['id']
        self.admin = TestClient(service.app)
        self.customer = TestClient(service.app)
        self.worker = TestClient(service.app)
        for client, email in ((self.admin,'admin'),(self.customer,'client'),(self.worker,'worker')):
            self.assertEqual(client.post('/api/login', json={'email':email+'@test.local','password':'password123'}).status_code, 200)

    def tearDown(self):
        if self.old_billing is None:
            os.environ.pop('BILLING_ENABLED', None)
        else:
            os.environ['BILLING_ENABLED'] = self.old_billing
        for client in (self.admin,self.customer,self.worker):
            client.close()
        service.DB_PATH = self.old_path
        self.temp.cleanup()

    def ok(self, response):
        self.assertIn(response.status_code, (200,201), response.text)
        return response.json()

    def client_info(self):
        return self.ok(self.customer.get('/api/billing/overview'))

    def invoice(self, amount=12345):
        return self.ok(self.admin.post('/api/billing/invoices', json={'doc_type':'invoice','client_type':'user','client_id':self.client_id,'amount_rub':amount}))

    def test_exact_money_payment_idempotency_and_rate_change(self):
        doc=self.invoice()
        self.assertEqual(doc['total_rub'],12345)
        for _ in range(2):
            self.ok(self.admin.patch(f"/api/billing/invoices/{doc['id']}/status",json={'status':'paid'}))
        self.ok(self.admin.patch(f'/api/billing/clients/user/{self.client_id}',json={'hourly_rate_rub':6700}))
        self.assertEqual(self.client_info()['balance_rub'],12345)
        with service.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM billing_transactions').fetchone()[0],1)

    def test_client_invoice_scope_and_snapshot_qr(self):
        own={'doc_type':'invoice','client_type':'user','client_id':self.client_id,'hours':5}
        doc=self.ok(self.customer.post('/api/billing/invoices',json=own))
        self.assertEqual(doc['total_rub'],15000)
        own['client_id']=self.worker_id
        self.assertEqual(self.customer.post('/api/billing/invoices',json=own).status_code,403)
        profile=self.ok(self.admin.get('/api/billing/company-profile'))
        old_name=profile['name'];profile['name']='Новый исполнитель'
        self.ok(self.admin.patch('/api/billing/company-profile',json=profile))
        rendered=self.admin.get(f"/api/billing/invoices/{doc['id']}/print")
        self.assertEqual(rendered.status_code,200,rendered.text)
        self.assertIn('data:image/svg+xml;base64,',rendered.text)
        self.assertNotIn('Новый исполнитель',rendered.text)
        self.assertIn('Линия Сервис',rendered.text)

    def test_requisites_roundtrip(self):
        data={'hourly_rate_rub':3500,'inn':'1234567890','kpp':'123456789','ogrn':'1234567890123','legal_address':'Адрес клиента','bank_name':'Банк клиента','bik':'123456789','bank_account':'12345678901234567890','corr_account':'98765432109876543210'}
        self.ok(self.admin.patch(f'/api/billing/clients/user/{self.client_id}',json=data))
        client=next(c for c in self.ok(self.admin.get('/api/billing/clients')) if c['client_id']==self.client_id)
        for key,value in data.items():self.assertEqual(client[key],value)

    def test_reserve_act_cancel_and_customer_price(self):
        self.ok(self.admin.post('/api/billing/deposit',json={'client_type':'user','client_id':self.client_id,'amount_rub':20000,'description':'Test payment'}))
        ticket=self.ok(self.admin.post('/api/admin/tickets',json={'title':'Доработка','description':'Описание работы','customer_id':self.client_id,'assignee_id':self.worker_id,'estimate':{'performer_effort_minutes':120,'pm_effort_minutes':60,'amount_rub':11234,'state':'approved'}}))
        self.assertEqual(self.client_info()['held_rub'],11234)
        self.assertEqual(self.client_info()['available_rub'],8766)
        self.ok(self.admin.patch(f"/api/admin/tickets/{ticket['id']}",json={'status':'done'}))
        preview=self.ok(self.admin.get(f'/api/billing/unbilled-tickets?client_type=user&client_id={self.client_id}'))
        self.assertEqual(preview[0]['cost_rub'],11234)
        self.assertEqual(self.client_info()['unbilled_rub'],11234)
        act=self.ok(self.admin.post('/api/billing/invoices',json={'doc_type':'act','client_type':'user','client_id':self.client_id,'ticket_ids':[ticket['id']],'service_entry_ids':[]}))
        self.assertEqual(act['total_rub'],11234)
        self.assertEqual(self.client_info()['balance_rub'],8766)
        self.assertEqual(self.client_info()['held_rub'],0)
        self.assertEqual(self.admin.patch(f"/api/admin/tickets/{ticket['id']}",json={'estimate':{'amount_rub':1}}).status_code,409)
        for _ in range(2):self.ok(self.admin.patch(f"/api/billing/invoices/{act['id']}/status",json={'status':'cancelled'}))
        self.assertEqual(self.client_info()['balance_rub'],20000)
        self.assertEqual(self.client_info()['held_rub'],11234)

    def test_admin_permissions_users_orgs_and_members(self):
        for client in (self.customer,self.worker,TestClient(service.app)):
            for endpoint in ('overview','users','staff','organizations','tickets'):
                self.assertIn(client.get('/api/admin/'+endpoint).status_code,(401,403))
        for endpoint in ('overview','users','staff','organizations','tickets'):
            self.ok(self.admin.get('/api/admin/'+endpoint))
        org=self.ok(self.admin.post('/api/admin/organizations',json={'name':'Test organization'}))
        person=self.ok(self.admin.post('/api/admin/users',json={'name':'New owner','email':'owner@test.local','password':'password123','role':'customer','organization_id':org['id'],'org_role':'owner'}))
        self.assertEqual(self.admin.delete(f"/api/admin/organizations/{org['id']}/members/{person['id']}").status_code,409)
        self.assertEqual(self.admin.patch(f'/api/admin/users/{self.admin_id}',json={'active':False}).status_code,409)
        self.ok(self.admin.patch(f"/api/admin/users/{person['id']}",json={'name':'Updated owner'}))
        self.assertNotIn('password_hash', self.ok(self.admin.get(f"/api/admin/users/{person['id']}")))
        self.ok(self.admin.put(f"/api/admin/organizations/{org['id']}/team",json={'members':[{'user_id':self.worker_id,'responsibility':'technical'}]}))
        self.assertEqual(self.admin.put(f"/api/admin/organizations/{org['id']}/team",json={'members':[{'user_id':self.client_id,'responsibility':'technical'}]}).status_code,422)

    def test_own_profile_keeps_session_and_password_reset_revokes_sessions(self):
        self.ok(self.admin.patch(f'/api/admin/users/{self.admin_id}',json={'name':'Updated admin','email':'admin@test.local','role':'admin'}))
        self.ok(self.admin.get('/api/me'))
        self.ok(self.admin.patch(f'/api/admin/users/{self.worker_id}',json={'password':'different-password'}))
        self.assertEqual(self.worker.get('/api/me').status_code,401)

    def test_document_date_uses_local_timezone(self):
        self.assertEqual(service.format_ru_date('2026-10-22T22:30:00+00:00'),'23 октября 2026 г.')

    def test_act_rejects_foreign_ticket(self):
        with service.db() as conn:
            other=service.create_user(conn,'Other client','other@test.local','password123','customer')['id']
        ticket=self.ok(self.admin.post('/api/admin/tickets',json={'title':'Чужая заявка','description':'Описание работы','customer_id':other,'status':'done','estimate':{'performer_effort_minutes':60,'amount_rub':3000,'state':'approved'}}))
        response=self.admin.post('/api/billing/invoices',json={'doc_type':'act','client_type':'user','client_id':self.client_id,'ticket_ids':[ticket['id']],'service_entry_ids':[]})
        self.assertEqual(response.status_code,409)

    def test_migration_once_and_fresh_schema(self):
        with service.db() as conn:
            conn.execute("DELETE FROM billing_migrations WHERE name='rub_balance_v1'")
            conn.execute('UPDATE customer_profiles SET balance_minutes=90,hourly_rate_rub=3000 WHERE user_id=?',(self.client_id,))
            billing_ledger.migrate(conn)
            self.assertEqual(conn.execute('SELECT deposit_balance_rub FROM customer_profiles WHERE user_id=?',(self.client_id,)).fetchone()[0],4500)
            conn.execute('UPDATE customer_profiles SET deposit_balance_rub=999 WHERE user_id=?',(self.client_id,))
            billing_ledger.migrate(conn)
            self.assertEqual(conn.execute('SELECT deposit_balance_rub FROM customer_profiles WHERE user_id=?',(self.client_id,)).fetchone()[0],999)
            self.assertIn('qr_payload',{r['name'] for r in conn.execute('PRAGMA table_info(invoices)')})


if __name__ == '__main__':unittest.main()
