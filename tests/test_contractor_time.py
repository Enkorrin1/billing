import unittest
import test_flows


class ContractorTime(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def test_all_estimates_count_without_changing_customer_billing(self):
        customer_id = self.customer.get('/api/me').json()['id']
        ticket = self.customer.post('/api/tickets', json={
            'title': 'Full contractor time', 'description': 'Include estimation and discussion'
        }).json()['id']
        path = f'/api/tickets/{ticket}'
        self.admin.patch(path + '/assignee', json={'assignee_id': self.staff['id']}).raise_for_status()
        empty = self.employee.get(path).json()['ticket']
        self.assertEqual(empty['contractor_total_minutes'], 0)
        for assessment, action in ((25, 'request_revision'), (15, 'reject'), (20, 'approve')):
            response = self.employee.post(path + '/estimates', json={
                'effort_minutes': 180, 'assessment_minutes': assessment, 'note': 'Estimate'
            })
            self.assertEqual(response.status_code, 201, response.text)
            self.customer.post(path + '/estimates/decision', json={
                'estimate_id': response.json()['id'], 'action': action, 'comment': 'Please review'
            }).raise_for_status()
        self.employee.patch(path + '/status', json={'status': 'working'}).raise_for_status()
        work = {'minutes': 90, 'note': 'Implemented changes', 'request_id': 'work-once'}
        for _ in range(2):
            self.employee.post(path + '/time-entries', json=work).raise_for_status()
        discussion = self.employee.post('/api/service-entries', json={
            'customer_id': customer_id, 'ticket_id': ticket, 'kind': 'chat',
            'minutes': 30, 'note': 'Clarified requirements', 'request_id': 'chat-once'
        })
        discussion.raise_for_status()
        self.employee.post('/api/service-entries', json={
            'customer_id': customer_id, 'kind': 'call', 'minutes': 45, 'note': 'Unrelated general call'
        }).raise_for_status()
        for client in (self.employee, self.admin):
            detail = client.get(path).json()['ticket']
            self.assertEqual(detail['assessment_minutes'], 60)
            self.assertEqual(detail['actual_minutes'], 90)
            self.assertEqual(detail['contractor_total_minutes'], 180)
            listing = next(t for t in client.get('/api/tickets').json() if t['id'] == ticket)
            self.assertEqual(listing['contractor_total_minutes'], 180)
        customer = self.customer.get(path).json()['ticket']
        self.assertNotIn('contractor_total_minutes', customer)
        self.assertNotIn('assessment_minutes', customer)
        self.assertEqual(customer['approved_minutes'], 180)
        self.assertEqual(customer['total_cost_rub'], 10500)
        self.employee.delete(f"/api/service-entries/{discussion.json()['id']}").raise_for_status()
        self.assertEqual(self.employee.get(path).json()['ticket']['contractor_total_minutes'], 150)


if __name__ == '__main__':
    unittest.main()
