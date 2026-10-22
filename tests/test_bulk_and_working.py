import unittest
from tests import test_flows


class BulkAndWorkingTest(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def test_estimate_approval_auto_moves_to_working(self):
        # 1.2: Ticket moves to working upon estimate approval
        ticket_id = self.customer.post('/api/tickets', json={'title': 'Задача на оценку', 'description': 'Описание работы'}).json()['id']
        self.admin.patch(f'/api/tickets/{ticket_id}/assignee', json={'assignee_id': self.staff['id']})
        est_id = self.employee.post(f'/api/tickets/{ticket_id}/estimates', json={'effort_minutes': 120, 'assessment_minutes': 10}).json()['id']
        self.admin.post(f'/api/tickets/{ticket_id}/estimates/{est_id}/pm-review', json={'action': 'send_to_customer'})
        
        # Approve estimate
        resp = self.customer.post(f'/api/tickets/{ticket_id}/estimates/decision', json={'estimate_id': est_id, 'action': 'approve'})
        self.assertEqual(resp.status_code, 200)
        
        # Check ticket status is immediately 'working'
        ticket = self.customer.get(f'/api/tickets/{ticket_id}').json()['ticket']
        self.assertEqual(ticket['status'], 'working')

        # Verify manual time entry works on the working ticket
        time_resp = self.employee.post(f'/api/tickets/{ticket_id}/time-entries', json={'minutes': 60, 'note': 'Выполнена первая половина'})
        self.assertEqual(time_resp.status_code, 201)

    def test_bulk_ticket_actions(self):
        # 2.3: Bulk actions endpoint
        t1 = self.customer.post('/api/tickets', json={'title': 'Массовая 1', 'description': 'Тест 1'}).json()['id']
        t2 = self.customer.post('/api/tickets', json={'title': 'Массовая 2', 'description': 'Тест 2'}).json()['id']

        # Bulk change assignee
        resp = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [t1, t2],
            'action': 'assignee',
            'assignee_id': self.staff['id']
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()['updated']), {t1, t2})

        # Verify assignee changed
        t1_data = self.admin.get(f'/api/tickets/{t1}').json()['ticket']
        t2_data = self.admin.get(f'/api/tickets/{t2}').json()['ticket']
        self.assertEqual(t1_data['assignee_id'], self.staff['id'])
        self.assertEqual(t2_data['assignee_id'], self.staff['id'])

        # Bulk change status to waiting
        resp = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [t1, t2],
            'action': 'status',
            'status': 'waiting'
        })
        self.assertEqual(resp.status_code, 200)
        t1_data = self.admin.get(f'/api/tickets/{t1}').json()['ticket']
        self.assertEqual(t1_data['status'], 'waiting')


if __name__ == '__main__':
    unittest.main()
