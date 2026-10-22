import unittest
from urllib.parse import urlsplit, parse_qs
from fastapi.testclient import TestClient
import test_flows

service = test_flows.service


class FlowReliability(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def shared_ticket(self):
        owner = self.customer.get('/api/me').json()['id']
        org = self.admin.post('/api/organizations', json={'name':'Компания', 'owner_id':owner}).json()['id']
        self.admin.post(f'/api/organizations/{org}/members', json={'email':'o@example.com','role':'member'})
        ticket = self.other.post('/api/tickets', json={'title':'Общая задача','description':'Работа для всей компании','visibility':'organization'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket}/assignee', json={'assignee_id':self.staff['id']})
        quote = self.employee.post(f'/api/tickets/{ticket}/estimates', json={'effort_minutes':120,'assessment_minutes':10}).json()['id']
        self.admin.post(f'/api/tickets/{ticket}/estimates/{quote}/pm-review', json={'action': 'send_to_customer'})
        return org, ticket, quote

    def test_shared_author_cannot_decide_but_owner_can(self):
        org, ticket, quote = self.shared_ticket()
        path = f'/api/tickets/{ticket}'
        self.assertEqual(self.other.post(path+'/estimates/decision', json={'estimate_id':quote,'action':'approve'}).status_code,403)
        detail = self.other.get(path).json()['ticket']
        self.assertFalse(detail['can_decide'])
        self.assertIn('владельца',detail['next_step'])
        self.assertEqual(self.customer.post(path+'/estimates/decision', json={'estimate_id':quote,'action':'approve'}).status_code,200)
        self.employee.patch(path+'/status', json={'status':'working'})
        request = self.employee.post(path+'/hour-requests',json={'minutes':30,'reason':'Дополнительная работа'}).json()['id']
        self.admin.post(path+f'/hour-requests/{request}/pm-decision', json={'action': 'approve', 'bill_customer': True, 'customer_minutes': 30})
        self.assertEqual(self.other.post(path+f'/hour-requests/{request}/decision',json={'action':'approve'}).status_code,403)
        self.customer.post(path+f'/hour-requests/{request}/decision',json={'action':'approve'})
        self.employee.post(path+'/time-entries',json={'minutes':30,'note':'Работа выполнена'})
        self.employee.patch(path+'/status',json={'status':'done'})
        self.assertEqual(self.other.post(path+'/acceptance',json={'action':'accept'}).status_code,403)
        self.assertEqual(self.customer.post(path+'/acceptance',json={'action':'accept'}).status_code,200)
        self.assertEqual(self.employee.patch(path+'/status',json={'status':'working'}).status_code,409)
        self.assertEqual(self.admin.patch(path+'/status',json={'status':'working'}).status_code,409)
        self.assertEqual(self.employee.post(path+'/reopen',json={'reason':'Новая доработка'}).status_code,403)
        reopened = self.admin.post(path+'/reopen',json={'reason':'Новая доработка'})
        self.assertEqual(reopened.status_code,200,reopened.text)
        self.assertIsNone(reopened.json()['accepted_at'])
        self.assertIsNone(reopened.json()['accepted_by_id'])
        self.assertTrue(any(e['kind']=='reopen' for e in self.customer.get(path).json()['events']))

    def test_inactive_or_expired_owner_cannot_replace_last_owner(self):
        org, ticket, quote = self.shared_ticket()
        owner_id=self.customer.get('/api/me').json()['id']
        member_id=self.other.get('/api/me').json()['id']
        self.admin.patch(f'/api/organizations/{org}/members/{member_id}',json={'role':'owner'})
        with service.db() as conn:
            conn.execute('UPDATE users SET active=0 WHERE id=?',(member_id,))
        self.assertEqual(self.admin.delete(f'/api/organizations/{org}/members/{owner_id}').status_code,409)
        with service.db() as conn:
            conn.execute('UPDATE users SET active=1,must_change_credentials=1,temporary_credentials_expires_at=? WHERE id=?',('2000-01-01',member_id))
        self.assertEqual(self.admin.patch(f'/api/organizations/{org}/members/{owner_id}',json={'role':'member'}).status_code,409)
        with service.db() as conn:
            conn.execute('DELETE FROM organization_members WHERE organization_id=? AND role=?',(org,'owner'))
        self.assertFalse(self.admin.get('/api/organizations').json()[0]['has_available_owner'])
        with service.db() as conn:
            message=service.customer_next_step({'status':'new','visibility':'organization','organization_id':org}, {'state':'pending'}, conn, {'role':'customer','id':123})
        self.assertIn('Нет доступного владельца',message)

    def test_invitation_preserves_pending_ticket_and_is_single_use(self):
        data={'name':'Новый клиент','email':'new@example.com'}
        self.assertEqual(self.employee.post('/api/customer-invitations',json=data).status_code,403)
        first=self.admin.post('/api/customer-invitations',json=data)
        self.assertEqual(first.status_code,201,first.text)
        access=first.json()
        pending=next(c for c in self.admin.get('/api/customers').json() if c['id']==access['customer_id'])
        self.assertFalse(pending['can_own_company'])
        client=TestClient(service.app)
        token=parse_qs(urlsplit(access['url']).query)['invite'][0]
        ticket=self.admin.post('/api/tickets',json={'customer_id':access['customer_id'],'title':'До первого входа','description':'Клиент ещё не зарегистрирован'}).json()['id']
        second=self.admin.post('/api/customer-invitations',json=data).json()
        self.assertEqual(access['customer_id'],second['customer_id'])
        self.assertEqual(client.post('/api/account/activate/invite',json={'token':token,'password':'newpassword123'}).status_code,409)
        token=parse_qs(urlsplit(second['url']).query)['invite'][0]
        accepted=client.post('/api/account/activate/invite',json={'token':token,'password':'newpassword123'})
        self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(client.get(f'/api/tickets/{ticket}').status_code,200)
        activated=next(c for c in self.admin.get('/api/customers').json() if c['id']==access['customer_id'])
        self.assertTrue(activated['can_own_company'])
        self.assertEqual(client.post('/api/account/activate/invite',json={'token':token,'password':'newpassword123'}).status_code,409)
        connected=self.admin.post('/api/customer-invitations',json=data)
        self.assertEqual(connected.status_code,201)
        self.assertTrue(connected.json()['registered'])

    def test_pending_owner_invitation_does_not_unlock_removal_and_expired_token_is_denied(self):
        org, ticket, quote=self.shared_ticket()
        data={'name':'Future Owner','email':'future@example.com','organization_id':org,'role':'owner'}
        access=self.admin.post('/api/customer-invitations',json=data).json()
        owner_id=self.customer.get('/api/me').json()['id']
        self.assertEqual(self.admin.delete(f'/api/organizations/{org}/members/{owner_id}').status_code,409)
        token=parse_qs(urlsplit(access['url']).query)['invite'][0]
        with service.db() as conn:
            conn.execute("UPDATE account_tokens SET expires_at=? WHERE user_id=?",('2000-01-01',access['customer_id']))
        self.assertEqual(TestClient(service.app).post('/api/account/activate/invite',json={'token':token,'password':'newpassword123'}).status_code,409)

    def test_reset_generic_response_rate_limit_and_revokes_sessions(self):
        known=TestClient(service.app).post('/api/account/reset-request',json={'email':'c@example.com'})
        unknown=TestClient(service.app).post('/api/account/reset-request',json={'email':'unknown@example.com'})
        self.assertEqual(known.json(),unknown.json())
        TestClient(service.app).post('/api/account/reset-request',json={'email':'c@example.com'})
        with service.db() as conn:
            mails=conn.execute("SELECT text_body FROM email_outbox WHERE kind='reset'").fetchall()
            self.assertEqual(len(mails),1)
            link=mails[0]['text_body'].split('пароль: ')[1].split('\n')[0]
        token=parse_qs(urlsplit(link).query)['reset'][0]
        client=TestClient(service.app)
        self.assertEqual(client.post('/api/account/activate/reset',json={'token':token,'password':'resetpassword123'}).status_code,200)
        self.assertEqual(self.customer.get('/api/me').status_code,401)
        self.assertEqual(client.post('/api/account/activate/reset',json={'token':token,'password':'resetpassword123'}).status_code,409)

    def test_staff_deactivation_transfers_work_and_can_restore(self):
        ticket=self.customer.post('/api/tickets',json={'title':'Передача задачи','description':'Передать открытые работы'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket}/assignee',json={'assignee_id':self.staff['id']})
        chat=self.customer.post('/api/chats').json()['id']
        self.admin.patch(f'/api/chats/{chat}/assignee',json={'assignee_id':self.staff['id']})
        replacement=self.admin.post('/api/staff',json={'name':'Replacement','email':'replacement@example.com','password':'password123'}).json()['id']
        url=f"/api/staff/{self.staff['id']}/availability"
        self.assertEqual(self.employee.patch(url,json={'active':False}).status_code,403)
        result=self.admin.patch(url,json={'active':False,'replacement_id':replacement})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['transferred_tickets'],1)
        self.assertEqual(result.json()['transferred_chats'],1)
        self.assertEqual(self.admin.get(f'/api/tickets/{ticket}').json()['ticket']['assignee_id'],replacement)
        self.assertEqual(self.admin.get(f'/api/chats/{chat}').json()['chat']['assignee_id'],replacement)
        self.assertEqual(self.employee.get('/api/me').status_code,401)
        self.assertFalse(any(p['id']==self.staff['id'] for p in self.admin.get('/api/staff').json()))
        self.assertEqual(self.admin.patch(url,json={'active':True}).status_code,200)
        self.assertEqual(self.employee.post('/api/login',json={'email':'w@example.com','password':'password123'}).status_code,200)

    def test_staff_deactivation_returns_work_to_queue_and_rejects_bad_replacement(self):
        ticket=self.customer.post('/api/tickets',json={'title':'Вернуть в очередь','description':'Нужно назначить нового исполнителя'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket}/assignee',json={'assignee_id':self.staff['id']})
        url=f"/api/staff/{self.staff['id']}/availability"
        self.assertEqual(self.admin.patch(url,json={'active':False,'replacement_id':self.staff['id']}).status_code,422)
        self.assertEqual(self.employee.get('/api/me').status_code,200)
        self.assertEqual(self.admin.patch(url,json={'active':False}).status_code,200)
        self.assertIsNone(self.admin.get(f'/api/tickets/{ticket}').json()['ticket']['assignee_id'])
        admin_id=self.admin.get('/api/me').json()['id']
        self.assertEqual(self.admin.patch(f'/api/staff/{admin_id}/availability',json={'active':False}).status_code,409)

    def test_empty_company_name_and_temporary_access_renewal(self):
        self.assertEqual(self.admin.post('/api/organizations',json={'name':'   ','owner_id':self.customer.get('/api/me').json()['id']}).status_code,422)
        access=self.admin.post('/api/company-owners',json={'name':'Owner','company_name':'Company'}).json()
        client=TestClient(service.app)
        client.post('/api/login',json={'email':access['login'],'password':access['temporary_password']})
        with service.db() as conn:
            conn.execute('UPDATE users SET temporary_credentials_expires_at=? WHERE id=?',('2000-01-01',access['id']))
        renewed=self.admin.post(f"/api/company-owners/{access['id']}/temporary-access").json()
        self.assertEqual(renewed['id'],access['id'])
        self.assertEqual(client.get('/api/me').status_code,401)
        self.assertEqual(client.post('/api/login',json={'email':access['login'],'password':access['temporary_password']}).status_code,401)
        self.assertEqual(client.post('/api/login',json={'email':renewed['login'],'password':renewed['temporary_password']}).status_code,200)
