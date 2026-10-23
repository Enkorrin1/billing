import unittest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import test_flows

service = test_flows.service


class MeetingLinkShare(unittest.TestCase):
    def setUp(self):
        test_flows.Flows.setUp(self)
        self.cid = self.customer.get('/api/me').json()['id']
        self.uid = self.staff['id']
        self.payload = {'customer_id': self.cid, 'title': 'Client planning meeting', 'agenda': 'Confirm requirements',
                        'host_id': self.uid, 'starts_at': (datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
                        'duration_minutes': 30, 'url': 'https://meet.example.test/room',
                        'internal_notes': 'SECRET INTERNAL NOTE', 'summary': 'UNPUBLISHED SUMMARY'}
        result=self.admin.post('/api/team/meetings', json=self.payload)
        self.assertEqual(result.status_code,201,result.text)
        self.meeting=result.json()

    def send(self, client=None, request_id='retry-request-001'):
        return (client or self.employee).post(f"/api/team/meetings/{self.meeting['id']}/share-link", json={'request_id':request_id})

    def test_host_can_send_without_chat_access_and_retry_is_idempotent(self):
        self.assertEqual(self.employee.get('/api/chats').json(),[])
        first=self.send(); self.assertEqual(first.status_code,200,first.text)
        again=self.send(); self.assertEqual(first.json()['message_id'],again.json()['message_id'])
        chat_id=first.json()['target_id']
        response=self.customer.get(f'/api/chats/{chat_id}')
        self.assertEqual(response.status_code,200,response.text)
        messages=response.json()['messages']
        self.assertEqual(len(messages),1)
        self.assertIn(self.payload['url'],messages[0]['body'])
        self.assertNotIn('SECRET INTERNAL',response.text)
        self.assertNotIn('UNPUBLISHED SUMMARY',response.text)
        self.assertEqual(self.employee.get(f'/api/chats/{chat_id}').status_code,404)
        self.assertEqual(self.other.get(f'/api/chats/{chat_id}').status_code,404)
        with service.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM service_entries').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM billing_transactions').fetchone()[0],0)

    def test_company_invitation_is_shared_in_company_chat(self):
        org=self.admin.post('/api/organizations',json={'name':'Audit company','owner_id':self.cid}).json()
        self.assertEqual(self.admin.post(f"/api/organizations/{org['id']}/members",json={'email':'o@example.com','role':'member'}).status_code,201)
        response=self.send(); self.assertEqual(response.status_code,200,response.text)
        chat_id=response.json()['target_id']
        chat=self.customer.get(f'/api/chats/{chat_id}').json()
        self.assertEqual(chat['chat']['organization_id'],org['id'])
        self.assertEqual(self.other.get(f'/api/chats/{chat_id}').status_code,200)
        self.assertEqual(len(chat['messages']),1)

    def test_unauthorized_and_customer_cannot_send(self):
        outsider=self.admin.post('/api/staff',json={'name':'Other employee','email':'outside-share@example.com','password':'password123'}).json()
        client=TestClient(service.app); client.post('/api/login',json={'email':'outside-share@example.com','password':'password123'})
        self.assertEqual(self.send(client).status_code,404)
        self.assertEqual(self.send(self.customer).status_code,403)

    def test_cancelled_and_empty_link_are_rejected(self):
        payload={**self.payload,'status':'cancelled','version':self.meeting['version']}
        result=self.admin.put(f"/api/team/meetings/{self.meeting['id']}",json=payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.send().status_code,409)
        payload.update(status='planned',url='',version=result.json()['version'])
        self.assertEqual(self.admin.put(f"/api/team/meetings/{self.meeting['id']}",json=payload).status_code,200)
        self.assertEqual(self.send().status_code,422)

    def test_linked_ticket_gets_one_message(self):
        ticket=self.customer.post('/api/tickets',json={'title':'Integration request','description':'Build integration'}).json()
        payload={**self.payload,'ticket_id':ticket['id'],'version':self.meeting['version']}
        result=self.admin.put(f"/api/team/meetings/{self.meeting['id']}",json=payload)
        self.assertEqual(result.status_code,200,result.text)
        first=self.send(); self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['target'],'ticket')
        self.assertEqual(self.send().json()['message_id'],first.json()['message_id'])
        messages=self.customer.get(f"/api/tickets/{ticket['id']}").json()['messages']
        self.assertEqual(sum(self.payload['url'] in m['body'] for m in messages),1)

if __name__ == '__main__': unittest.main()
