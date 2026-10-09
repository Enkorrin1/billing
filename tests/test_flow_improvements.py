import unittest
import test_flows
service = test_flows.service

class FlowImprovements(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def company(self):
        owner=self.customer.get('/api/me').json()['id']
        return self.admin.post('/api/organizations',json={'name':'Company','owner_id':owner}).json()['id']

    def test_payment_permission_and_idempotence(self):
        customer=self.customer.get('/api/me').json()['id']
        invoice=self.admin.post('/api/billing/invoices',json={'doc_type':'invoice','client_type':'user','client_id':customer,'hours':1}).json()['id']
        path=f'/api/billing/invoices/{invoice}/status'
        for client in (self.customer,self.employee):
            self.assertEqual(client.patch(path,json={'status':'paid'}).status_code,403)
        for _ in range(2):
            self.assertEqual(self.admin.patch(path,json={'status':'paid'}).status_code,200)
        self.assertEqual(self.customer.get('/api/billing/overview').json()['balance_minutes'],60)
        self.assertEqual(self.admin.patch(path,json={'status':'cancelled'}).status_code,409)

    def test_existing_account_connection_preserves_login(self):
        response=self.admin.post('/api/customer-invitations',json={'name':'Existing','email':'c@example.com','company_name':'Connected Company'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertTrue(response.json()['registered'])
        self.assertNotIn('url',response.json())
        self.assertEqual(self.customer.get('/api/me').status_code,200)
        self.assertEqual(self.customer.post('/api/login',json={'email':'c@example.com','password':'password123'}).status_code,200)
        invalid=self.admin.post('/api/customer-invitations',json={'name':'Invalid','email':'invalid@example.com','company_name':'  '})
        self.assertEqual(invalid.status_code,422)

    def test_company_owner_membership_permissions(self):
        org=self.company()
        path=f'/api/organizations/{org}/members'
        self.assertEqual(self.other.post(path,json={'email':'o@example.com','role':'member'}).status_code,403)
        self.assertEqual(self.customer.post(path,json={'email':'o@example.com','role':'member'}).status_code,201)
        member=self.other.get('/api/me').json()['id']
        self.assertEqual(self.customer.patch(path+f'/{member}',json={'role':'viewer'}).status_code,200)
        owner=self.customer.get('/api/me').json()['id']
        self.assertEqual(self.customer.delete(path+f'/{owner}').status_code,409)
        self.assertEqual(self.customer.delete(path+f'/{member}').status_code,200)

    def test_service_limit_and_customer_aggregates(self):
        customer=self.customer.get('/api/me').json()['id']
        ticket=self.customer.post('/api/tickets',json={'title':'Service limit','description':'Test charges'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket}/assignee',json={'assignee_id':self.staff['id']})
        path=f'/api/tickets/{ticket}'
        self.assertEqual(self.employee.patch(path+'/service-budget',json={'limit_minutes':60}).status_code,403)
        self.assertEqual(self.customer.patch(path+'/service-budget',json={'limit_minutes':60}).status_code,200)
        payload={'customer_id':customer,'ticket_id':ticket,'kind':'call','minutes':45,'note':'Private staff note'}
        response=self.employee.post('/api/service-entries',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.employee.post('/api/service-entries',json={**payload,'minutes':16}).status_code,409)
        self.assertEqual(self.customer.patch(path+'/service-budget',json={'limit_minutes':44}).status_code,409)
        detail=self.customer.get(path).json()
        self.assertEqual(detail['ticket']['service_minutes'],45)
        self.assertEqual(detail['ticket']['service_cost_rub'],2250)
        self.assertNotIn('Private staff note',str(detail))

    def test_owner_help_is_deduplicated(self):
        org=self.company()
        ticket=self.customer.post('/api/tickets',json={'title':'Owner help','description':'Restore access','visibility':'organization'}).json()['id']
        path=f'/api/tickets/{ticket}/owner-help'
        self.assertEqual(self.customer.post(path).status_code,409)
        with service.db() as conn:
            conn.execute("UPDATE organization_members SET role='member' WHERE organization_id=?",(org,))
        for _ in range(2):
            self.assertEqual(self.customer.post(path).status_code,200)
        with service.db() as conn:
            count=conn.execute("SELECT COUNT(*) FROM ticket_events WHERE ticket_id=? AND kind='owner_help'",(ticket,)).fetchone()[0]
        self.assertEqual(count,1)

    def test_act_signature_does_not_credit_balance(self):
        customer=self.customer.get('/api/me').json()['id']
        entry=self.employee.post('/api/service-entries',json={'customer_id':customer,'kind':'call','minutes':30,'note':'Consultation'}).json()['id']
        response=self.admin.post('/api/billing/invoices',json={'doc_type':'act','client_type':'user','client_id':customer,'service_entry_ids':[entry]})
        self.assertEqual(response.status_code,201,response.text)
        path=f"/api/billing/invoices/{response.json()['id']}/status"
        before=self.customer.get('/api/billing/overview').json()['balance_minutes']
        self.assertEqual(self.admin.patch(path,json={'status':'paid'}).status_code,422)
        for _ in range(2):
            self.assertEqual(self.admin.patch(path,json={'status':'signed'}).status_code,200)
        self.assertEqual(self.customer.get('/api/billing/overview').json()['balance_minutes'],before)
        with service.db() as conn:
            row=conn.execute('SELECT signed_at,paid_at FROM invoices WHERE id=?',(response.json()['id'],)).fetchone()
        self.assertTrue(row['signed_at'])
        self.assertIsNone(row['paid_at'])

    def test_pending_invitation_status_and_owner_scope(self):
        org=self.company()
        response=self.customer.post('/api/customer-invitations',json={'name':'Invited member','email':'invited@example.com','organization_id':org,'role':'member'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertFalse(response.json()['registered'])
        listing=self.customer.get('/api/customer-invitations')
        self.assertEqual(listing.status_code,200,listing.text)
        item=next(x for x in listing.json() if x['email']=='invited@example.com')
        self.assertEqual(item['status'],'pending')
        self.assertNotIn('url',item)
        self.assertEqual(self.other.get('/api/customer-invitations').status_code,403)

    def test_resend_supersedes_queued_old_invitation(self):
        payload={'name':'Pending customer','email':'pending@example.com'}
        first=self.admin.post('/api/customer-invitations',json=payload).json()
        second=self.admin.post('/api/customer-invitations',json=payload).json()
        self.assertEqual(first['customer_id'],second['customer_id'])
        self.assertNotEqual(first['url'],second['url'])
        with service.db() as conn:
            states=[row[0] for row in conn.execute("SELECT state FROM email_outbox WHERE user_id=? AND kind='invite' ORDER BY id",(first['customer_id'],))]
        self.assertEqual(states,['superseded','pending'])
