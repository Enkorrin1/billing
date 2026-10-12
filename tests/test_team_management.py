import unittest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import test_flows

service = test_flows.service


class TeamManagement(unittest.TestCase):
    def setUp(self):
        test_flows.Flows.setUp(self)
        self.cid = self.customer.get('/api/me').json()['id']
        self.other_cid = self.other.get('/api/me').json()['id']
        self.uid = self.staff['id']
        self.second = self.admin.post('/api/staff',json={'name':'Reviewer','email':'review@example.com','password':'password123'}).json()['id']
        self.reviewer = TestClient(service.app)
        self.reviewer.post('/api/login',json={'email':'review@example.com','password':'password123'})

    def config(self, uid=None, **changes):
        uid=uid or self.uid
        p=next(p for p in self.admin.get('/api/team').json()['people'] if p['id']==uid)
        payload={k:p[k] for k in ('functions','job_title','department','manager_id','capacity_minutes','availability','permissions','scope','responsibilities')}
        payload['version']=p['updated_at'];payload['access_level']='manager' if p['is_manager'] else 'employee'
        payload.update(changes)
        response=self.admin.put(f'/api/team/staff/{uid}',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        return response.json(),payload

    def assign(self,uid=None,cid=None,role='specialist'):
        response=self.admin.put(f'/api/team/clients/{cid or self.cid}',json={'members':[{'user_id':uid or self.uid,'responsibility':role}]})
        self.assertEqual(response.status_code,200,response.text)

    def task(self,**changes):
        payload={'customer_id':self.cid,'title':'Prepare solution','owner_id':self.uid,'description':'Clear result','planned_minutes':120,
                 'due_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
        payload.update(changes)
        result=self.admin.post('/api/team/tasks',json=payload)
        self.assertEqual(result.status_code,201,result.text)
        return result.json(),payload

    def meeting(self,**changes):
        payload={'customer_id':self.cid,'title':'Requirements call','agenda':'Confirm requirements','host_id':self.uid,'participants':[self.second],
                 'starts_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),'duration_minutes':30,'internal_notes':'PRIVATE NOTE'}
        payload.update(changes)
        result=self.admin.post('/api/team/meetings',json=payload)
        self.assertEqual(result.status_code,201,result.text)
        return result.json(),payload

    def test_functions_migrate_and_never_elevate_access(self):
        self.config(functions=['sales','call_host','programmer'],permissions=[])
        me=self.employee.get('/api/me').json()
        self.assertEqual(me['role'],'employee');self.assertFalse(me['is_manager'])
        self.assign()
        self.assertEqual(self.employee.post('/api/team/deals',json={'customer_id':self.cid,'title':'New sale','owner_id':self.uid,'next_action':'Call client'}).status_code,403)
        self.config(functions=[])
        service.init_db()
        self.assertEqual(self.employee.get('/api/profile/me').json()['functions'],[])
        self.assertEqual(self.customer.get('/api/team').status_code,403)

    def test_custom_functions_optimistic_lock_and_reporting_cycle(self):
        self.assertEqual(self.employee.post('/api/team/functions',json={'code':'presales','name':'Предпродажи','category':'Клиенты'}).status_code,403)
        self.assertEqual(self.admin.post('/api/team/functions',json={'code':'presales','name':'Предпродажи','category':'Клиенты'}).status_code,201)
        result,payload=self.config(functions=['presales'],manager_id=self.second,capacity_minutes=1800)
        self.assertEqual(self.admin.put(f'/api/team/staff/{self.uid}',json=payload).status_code,409)
        p=next(p for p in self.admin.get('/api/team').json()['people'] if p['id']==self.second)
        payload.update(version=p['updated_at'],manager_id=self.uid)
        self.assertEqual(self.admin.put(f'/api/team/staff/{self.second}',json=payload).status_code,422)

    def test_client_and_department_scope(self):
        self.assign()
        self.task()
        self.task(customer_id=self.other_cid,title='Unrelated confidential work',owner_id=self.admin.get('/api/me').json()['id'])
        self.assertEqual(len(self.employee.get('/api/team').json()['tasks']),1)
        self.assertEqual(len(self.reviewer.get('/api/team').json()['tasks']),0)
        self.config(self.uid,department='Delivery')
        self.config(self.second,department='Delivery',scope='department')
        self.assertEqual(len(self.reviewer.get('/api/team').json()['tasks']),1)
        self.assertEqual(self.employee.post('/api/team/tasks',json={'customer_id':self.other_cid,'title':'Steal scope','owner_id':self.uid}).status_code,404)
        self.assertEqual(self.employee.put(f'/api/team/clients/{self.cid}',json={'members':[]}).status_code,403)

    def test_meeting_participant_cannot_access_rest_of_client(self):
        self.meeting()
        self.task()
        workspace=self.reviewer.get('/api/team').json()
        self.assertEqual(len(workspace['meetings']),1)
        self.assertEqual(workspace['tasks'],[])
        self.assertEqual(workspace['clients'],[])
        m=workspace['meetings'][0]
        self.assertFalse(m['can_edit'])
        response=self.employee.post('/api/team/tasks',json={'customer_id':self.cid,'title':'Follow up on this meeting','owner_id':self.uid,'meeting_id':m['id']})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.employee.post('/api/team/tasks',json={'customer_id':self.other_cid,'title':'Wrong client task','owner_id':self.uid,'meeting_id':m['id']}).status_code,404)

    def test_financial_permissions_are_explicit_and_independent(self):
        self.config(functions=['finance','sales'],permissions=['sales'])
        self.assertEqual(self.employee.get('/api/billing/overview').status_code,403)
        self.assertEqual(self.employee.get('/api/billing/invoices').status_code,403)
        self.config(permissions=['billing_read'])
        self.assertEqual(self.employee.get('/api/billing/overview').status_code,200)
        payload={'client_type':'user','client_id':self.cid,'minutes':60,'description':'Test deposit'}
        self.assertEqual(self.employee.post('/api/billing/deposit',json=payload).status_code,403)
        self.config(permissions=['billing_manage'])
        self.assertEqual(self.employee.post('/api/billing/deposit',json=payload).status_code,200)
        self.assertFalse(self.employee.get('/api/me').json()['is_manager'])

    def test_assignment_notifications_follow_current_access(self):
        task,payload=self.task()
        d=self.employee.get('/api/team').json()
        event=next(e for e in d['events'] if e['entity']=='tasks' and e['entity_id']==task['id'])
        self.assertIsNone(event['read_at'])
        self.assertEqual(self.reviewer.post(f"/api/team/notifications/{event['id']}/read").status_code,404)
        self.assertEqual(self.employee.post(f"/api/team/notifications/{event['id']}/read").status_code,200)
        self.admin.put(f"/api/team/tasks/{task['id']}",json={**payload,'version':task['version'],'owner_id':self.second})
        self.assertEqual(self.employee.get('/api/team').json()['events'],[])
        self.assertEqual(self.employee.post(f"/api/team/notifications/{event['id']}/read").status_code,404)

    def test_review_requires_reviewer_and_stale_update_rejected(self):
        task,payload=self.task(reviewer_id=self.second)
        self.assign()
        request={**payload,'reviewer_id':self.second,'status':'done','version':task['version']}
        self.assertEqual(self.employee.put(f"/api/team/tasks/{task['id']}",json=request).status_code,403)
        self.assertEqual(self.employee.put(f"/api/team/tasks/{task['id']}",json={**request,'reviewer_id':None}).status_code,403)
        response=self.reviewer.put(f"/api/team/tasks/{task['id']}",json=request)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.reviewer.put(f"/api/team/tasks/{task['id']}",json=request).status_code,409)

    def test_publication_is_private_non_billable_and_idempotent(self):
        m,payload=self.meeting(status='held',summary='Agreed public result',next_steps='Implement integration')
        path=f"/api/team/meetings/{m['id']}/publish"
        self.assertEqual(self.employee.post(path).status_code,200)
        self.assertEqual(self.employee.post(path).status_code,200)
        chat=self.customer.get('/api/chats').json()[0]
        response=self.customer.get(f"/api/chats/{chat['id']}")
        self.assertEqual(len(response.json()['meeting_summaries']),1)
        self.assertNotIn('PRIVATE NOTE',response.text)
        self.assertNotIn('duration_minutes',response.text)
        self.assertEqual(self.other.get(f"/api/chats/{chat['id']}").status_code,404)
        self.assertEqual(self.admin.get(f'/api/service-entries?client_type=user&client_id={self.cid}&unbilled=true').json(),[])
        with service.db() as conn:
            self.assertEqual(service.unbilled_service_minutes(conn,'user',self.cid),0)
            entry=conn.execute('SELECT id FROM service_entries WHERE is_billable=0').fetchone()['id']
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM billing_transactions').fetchone()[0],0)
        self.assertEqual(self.admin.delete(f'/api/service-entries/{entry}').status_code,409)
        self.assertEqual(self.admin.patch(f'/api/service-entries/{entry}/summary',json={'summary':'Alter published record','next_steps':''}).status_code,409)
        self.assertEqual(self.admin.post('/api/billing/invoices',json={'client_type':'user','client_id':self.cid,'doc_type':'act','ticket_ids':[],'service_entry_ids':[entry]}).status_code,422)

    def test_sales_loss_validation_and_single_handoff(self):
        self.config(permissions=['sales','meetings'])
        self.assign(role='sales')
        payload={'customer_id':self.cid,'title':'Integration sale','owner_id':self.uid,'next_action':'Deliver scope','stage':'won','proposal':'Agreed integration and deadline'}
        result=self.employee.post('/api/team/deals',json=payload)
        self.assertEqual(result.status_code,201,result.text)
        did=result.json()['id']
        self.assertEqual(self.reviewer.get('/api/team').json()['deals'],[])
        path=f'/api/team/deals/{did}/handoff'
        handoff={'owner_id':self.second,'title':'Implement integration','description':'Check agreement','planned_minutes':240}
        first=self.employee.post(path,json=handoff);second=self.employee.post(path,json=handoff)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['task_id'],second.json()['task_id'])
        self.assertTrue(second.json()['already_transferred'])
        self.assertEqual(len(self.reviewer.get('/api/team').json()['tasks']),1)
        self.assertEqual(self.employee.post('/api/team/deals',json={**payload,'stage':'lost','loss_reason':''}).status_code,422)

    def test_ticket_observer_read_executor_write_and_revocation(self):
        tid=self.customer.post('/api/tickets',json={'title':'Collaborative work','description':'Implement change'}).json()['id']
        path=f'/api/team/tickets/{tid}/participants'
        self.assertEqual(self.admin.put(path,json={'members':[{'user_id':self.uid,'participation':'observer'}]}).status_code,200)
        self.assertEqual(self.employee.get(f'/api/tickets/{tid}').status_code,200)
        self.assertFalse(self.employee.get(f'/api/tickets/{tid}').json()['ticket']['can_write'])
        self.assertEqual(len(self.employee.get('/api/tickets').json()),1)
        self.assertEqual(self.employee.post(f'/api/tickets/{tid}/messages',json={'body':'Must be denied','request_id':'observer-message'}).status_code,404)
        self.assertEqual(self.employee.post('/api/service-entries',json={'customer_id':self.cid,'ticket_id':tid,'kind':'call','minutes':30,'note':'Observer cannot charge'}).status_code,403)
        self.assertEqual(self.employee.post(f'/api/tickets/{tid}/read',json={}).status_code,200)
        self.admin.put(path,json={'members':[{'user_id':self.uid,'participation':'executor'}]})
        self.assertEqual(self.employee.post(f'/api/tickets/{tid}/messages',json={'body':'Executor contribution','request_id':'executor-message'}).status_code,201)
        self.admin.put(path,json={'members':[]})
        self.assertEqual(self.employee.get(f'/api/tickets/{tid}').status_code,404)

    def test_handover_transfers_all_live_work_and_keeps_authorship(self):
        self.assign();task,_=self.task();m,_=self.meeting()
        deal=self.admin.post('/api/team/deals',json={'customer_id':self.cid,'title':'Open sale','owner_id':self.uid,'next_action':'Call client'}).json()
        response=self.admin.patch(f'/api/staff/{self.uid}/availability',json={'active':False,'replacement_id':self.second})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.employee.get('/api/me').status_code,401)
        d=self.admin.get('/api/team').json()
        self.assertEqual(next(t for t in d['tasks'] if t['id']==task['id'])['owner_id'],self.second)
        self.assertEqual(next(t for t in d['meetings'] if t['id']==m['id'])['host_id'],self.second)
        self.assertEqual(next(t for t in d['deals'] if t['id']==deal['id'])['owner_id'],self.second)
        self.assertTrue(all(member['user_id']!=self.uid for c in d['clients'] for member in c['members']))
        self.assertEqual(next(t for t in d['tasks'] if t['id']==task['id'])['created_by'],self.admin.get('/api/me').json()['id'])

    def test_vacation_handover_keeps_session_and_new_owner_sees_task(self):
        self.assign();task,_=self.task()
        self.config(availability='vacation')
        response=self.admin.patch(f'/api/staff/{self.uid}/availability',json={'active':True,'replacement_id':self.second,'transfer_work':True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.employee.get('/api/me').status_code,200)
        self.assertTrue(any(t['id']==task['id'] for t in self.reviewer.get('/api/team').json()['tasks']))


if __name__=='__main__':
    unittest.main()
