import json
import os
from unittest import mock
import unittest
from tests import test_pm_billing
service = test_pm_billing.service


class CustomerFinanceProjectionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BILLING_ENABLED": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        test_pm_billing.PmBillingTests.setUp(self)

    def test_customer_finance_hides_internal_quantities(self):
        created = self.admin.post('/api/billing/invoices', json={'client_type':'user','client_id':self.client_id,'doc_type':'invoice','hours':3}).json()
        invoice_id = created['id']
        self.admin.patch(f'/api/billing/invoices/{invoice_id}/status', json={'status':'paid'})
        for path in ['/api/billing/overview', '/api/billing/invoices', f'/api/billing/invoices/{invoice_id}']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            text = json.dumps(response.json())
            for key in ['total_minutes', 'hourly_rate_rub', 'balance_minutes', 'in_progress_minutes', 'unbilled_minutes', '"minutes"', '"hours"']:
                self.assertNotIn(key, text, path)
        detail = self.client.get(f'/api/billing/invoices/{invoice_id}').json()
        self.assertEqual(detail['total_rub'], 9000)
        self.assertEqual(detail['items'][0]['qty'], 1)
        self.assertEqual(detail['items'][0]['unit'], 'усл.')
        self.assertIn('total_minutes', self.admin.get(f'/api/billing/invoices/{invoice_id}').json())
        printed = self.client.get(f'/api/billing/invoices/{invoice_id}/print').text
        self.assertNotIn('>ч<', printed)
        self.assertNotIn('3 ч', printed)

    def test_customer_requests_deposit_in_rubles_only(self):
        body = {'client_type':'user','client_id':self.client_id,'doc_type':'invoice'}
        self.assertEqual(self.client.post('/api/billing/invoices', json={**body,'hours':2}).status_code, 422)
        response = self.client.post('/api/billing/invoices', json={**body,'amount_rub':12345})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['total_rub'], 12345)
        self.assertNotIn('total_minutes', response.json())

    def test_profile_threshold_is_fixed_rubles_and_legacy_converts_once(self):
        with service.db() as conn:
            conn.execute("UPDATE customer_profiles SET auto_approve_minutes=120,auto_approve_rub=NULL WHERE user_id=?", (self.client_id,))
        profile = self.client.get('/api/customer-profile/me').json()
        self.assertEqual(profile['auto_approve_rub'], 6000)
        self.assertNotIn('auto_approve_minutes', profile)
        self.admin.patch(f'/api/billing/clients/user/{self.client_id}', json={'hourly_rate_rub':5000})
        self.assertEqual(self.client.get('/api/customer-profile/me').json()['auto_approve_rub'],6000)
        changed = self.client.patch('/api/customer-profile/me',json={'name':'Client','auto_approve_rub':12345})
        self.assertEqual(changed.json()['auto_approve_rub'],12345)

    def test_ticket_pending_actions_email_and_digest_use_client_amount(self):
        ticket_id = self.client.post('/api/tickets',json={'title':'Financial projection','description':'Check client surfaces'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket_id}/assignee',json={'assignee_id':self.worker_id})
        estimate = self.worker.post(f'/api/tickets/{ticket_id}/estimates',json={'effort_minutes':123,'assessment_minutes':15,'note':'INTERNAL EFFORT'}).json()
        sent = self.admin.post(f"/api/tickets/{ticket_id}/estimates/{estimate['id']}/pm-review",json={'action':'send_to_customer','pm_effort_minutes':17,'custom_amount_rub':9876,'client_note':'Agreed scope'})
        self.assertEqual(sent.status_code,200)
        detail = self.client.get(f'/api/tickets/{ticket_id}').json()
        self.assertNotIn('INTERNAL EFFORT',json.dumps(detail))
        for item in [detail['ticket'],*detail['estimates']]:
            self.assertFalse(any('minutes' in key or 'rate_rub' in key for key in item))
        with service.db() as conn:
            user = conn.execute('SELECT * FROM users WHERE id=?',(self.client_id,)).fetchone()
            actions = service.customer_pending_actions(conn,user)
            self.assertEqual(actions[0]['amount_rub'],9876)
            self.assertNotIn('effort_minutes',actions[0])
            self.assertIn('9 876 ₽',actions[0]['detail'])
            prompt = service.describe_email_action(conn,{'action':'approve_estimate','ref_id':estimate['id'],'ticket_id':ticket_id})
            self.assertIn('9 876 ₽',prompt)
            self.assertNotIn(' ч',prompt)
            digest = service.build_digest(conn,user,'2026-10')
            self.assertNotIn('logged_minutes',digest)
            service.render_digest(user,digest)

    def test_service_act_print_projection_preserves_agreed_sum(self):
        items = [{'title':'Support','minutes':150,'hours':2.5,'rate':3000,'sum_rub':7500}]
        projected = service.customer_document_items(items)
        self.assertEqual(projected,[{'title':'Support','qty':1,'unit':'усл.','rate':7500,'sum_rub':7500}])
        self.assertEqual(items[0]['hours'],2.5)

    def test_pm_review_clears_client_note_and_rounds_half_up(self):
        self.admin.patch(f'/api/billing/clients/user/{self.client_id}',json={'hourly_rate_rub':3030})
        ticket_id = self.client.post('/api/tickets',json={'title':'Half ruble','description':'Check rounding and note'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket_id}/assignee',json={'assignee_id':self.worker_id})
        estimate = self.worker.post(f'/api/tickets/{ticket_id}/estimates',json={'effort_minutes':1,'assessment_minutes':1,'client_note':'Old client note'}).json()
        response = self.admin.post(f"/api/tickets/{ticket_id}/estimates/{estimate['id']}/pm-review",json={'action':'send_to_customer','client_note':''})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['amount_rub'],51)
        self.assertEqual(response.json()['client_note'],'')
        decision = self.client.post(f'/api/tickets/{ticket_id}/estimates/decision',json={'estimate_id':estimate['id'],'action':'request_revision','proposed_effort_minutes':1})
        self.assertEqual(decision.status_code,422)
        decision = self.client.post(f'/api/tickets/{ticket_id}/estimates/decision',json={'estimate_id':estimate['id'],'action':'approve'})
        self.assertEqual(decision.status_code,200)
        self.assertFalse(any('minutes' in key or 'rate_rub' in key for key in decision.json()))

    def test_public_settings_and_internal_service_budget_do_not_reveal_hours(self):
        self.assertNotIn('hourly_rate_rub',self.client.get('/api/public/settings').json())
        ticket_id = self.client.post('/api/tickets',json={'title':'Internal budget','description':'Customer receives money only'}).json()['id']
        self.assertEqual(self.client.patch(f'/api/tickets/{ticket_id}/service-budget',json={'limit_minutes':60}).status_code,403)
        response = self.admin.patch(f'/api/tickets/{ticket_id}/service-budget',json={'limit_minutes':60})
        self.assertEqual(response.status_code,200)
        detail = self.client.get(f'/api/tickets/{ticket_id}').json()
        self.assertNotIn('service_limit_minutes',detail['ticket'])
        event = next(item for item in detail['events'] if item['kind']=='service_budget')
        self.assertNotIn('new_value',event)
