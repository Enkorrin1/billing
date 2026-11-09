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

    def test_bulk_status_enforces_estimate_actual_and_reopen_guards(self):
        ticket_id = self.customer.post('/api/tickets', json={
            'title': 'Без оценки', 'description': 'Не начинать работу без согласования'
        }).json()['id']

        before = self.admin.get(f'/api/tickets/{ticket_id}').json()
        response = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [ticket_id], 'action': 'status', 'status': 'working'
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'count': 0, 'ticket_ids': [], 'updated': []})
        after = self.admin.get(f'/api/tickets/{ticket_id}').json()
        self.assertEqual(after['ticket']['status'], 'new')
        self.assertEqual(after['events'], before['events'])

        closed_id = self.customer.post('/api/tickets', json={
            'title': 'Закрытая заявка', 'description': 'Массовое действие не должно открыть её'
        }).json()['id']
        with test_flows.service.db() as conn:
            conn.execute("UPDATE tickets SET status='closed' WHERE id=?", (closed_id,))
        closed_before = self.admin.get(f'/api/tickets/{closed_id}').json()
        reopen = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [closed_id], 'action': 'status', 'status': 'waiting'
        })
        self.assertEqual(reopen.status_code, 200)
        self.assertEqual(reopen.json()['updated'], [])
        closed_after = self.admin.get(f'/api/tickets/{closed_id}').json()
        self.assertEqual(closed_after['ticket']['status'], 'closed')
        self.assertEqual(closed_after['events'], closed_before['events'])

        no_time_id = self.customer.post('/api/tickets', json={
            'title': 'Без фактического времени', 'description': 'Нельзя массово закрыть до учёта времени'
        }).json()['id']
        self.assertEqual(self.admin.patch(f'/api/tickets/{no_time_id}/assignee', json={
            'assignee_id': self.staff['id']
        }).status_code, 200)
        estimate = self.employee.post(f'/api/tickets/{no_time_id}/estimates', json={
            'effort_minutes': 120, 'assessment_minutes': 10
        }).json()['id']
        self.admin.post(f'/api/tickets/{no_time_id}/estimates/{estimate}/pm-review', json={
            'action': 'send_to_customer'
        })
        self.assertEqual(self.customer.post(f'/api/tickets/{no_time_id}/estimates/decision', json={
            'estimate_id': estimate, 'action': 'approve'
        }).status_code, 200)
        close_without_time = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [no_time_id], 'action': 'status', 'status': 'closed'
        })
        self.assertEqual(close_without_time.status_code, 200)
        self.assertEqual(close_without_time.json()['updated'], [])
        self.assertEqual(self.admin.get(f'/api/tickets/{no_time_id}').json()['ticket']['status'], 'working')

    def test_bulk_status_matches_single_transition_for_staff(self):
        single_id = self.customer.post('/api/tickets', json={
            'title': 'Одиночный переход', 'description': 'Обычный переход статуса'
        }).json()['id']
        bulk_id = self.customer.post('/api/tickets', json={
            'title': 'Массовый переход', 'description': 'Обычный переход статуса'
        }).json()['id']
        untouched_id = self.customer.post('/api/tickets', json={
            'title': 'Чужая заявка', 'description': 'Исполнитель не назначен'
        }).json()['id']
        for ticket_id in (single_id, bulk_id):
            assigned = self.admin.patch(f'/api/tickets/{ticket_id}/assignee', json={
                'assignee_id': self.staff['id']
            })
            self.assertEqual(assigned.status_code, 200)

        service = test_flows.service
        published = []
        deliveries = []
        dispatch = service.dispatch_webhooks
        realtime_publish = service.realtime_bus.publish
        push_enqueue = service.web_push.enqueue
        service.dispatch_webhooks = lambda event, payload, *, conn: published.append((event, payload))
        service.realtime_bus.publish = lambda user_id, payload: deliveries.append(('realtime', user_id, payload))
        service.web_push.enqueue = lambda user_id, payload: deliveries.append(('push', user_id, payload))
        try:
            single = self.employee.patch(f'/api/tickets/{single_id}/status', json={'status': 'waiting'})
            bulk = self.employee.post('/api/tickets/bulk', json={
                'ticket_ids': [bulk_id, untouched_id], 'action': 'status', 'status': 'waiting'
            })
        finally:
            service.dispatch_webhooks = dispatch
            service.realtime_bus.publish = realtime_publish
            service.web_push.enqueue = push_enqueue

        self.assertEqual(single.status_code, 200)
        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(bulk.json()['updated'], [bulk_id])
        single_detail = self.admin.get(f'/api/tickets/{single_id}').json()
        bulk_detail = self.admin.get(f'/api/tickets/{bulk_id}').json()
        untouched_detail = self.admin.get(f'/api/tickets/{untouched_id}').json()
        single_events = [event for event in single_detail['events'] if event['kind'] == 'status']
        bulk_events = [event for event in bulk_detail['events'] if event['kind'] == 'status']
        self.assertEqual(len(single_events), 1)
        self.assertEqual(len(bulk_events), 1)
        self.assertEqual((single_events[0]['old_value'], single_events[0]['new_value']), ('new', 'waiting'))
        self.assertEqual((bulk_events[0]['old_value'], bulk_events[0]['new_value']), ('new', 'waiting'))
        self.assertFalse(any(event['kind'] == 'status' for event in untouched_detail['events']))

        status_notices = [notice for notice in self.customer.get('/api/notifications').json()
                          if notice['kind'] == 'status']
        notice_ids = {notice['ticket_id'] for notice in status_notices}
        self.assertEqual(notice_ids, {single_id, bulk_id})
        self.assertEqual(len(published), 2)
        self.assertEqual([event for event, _ in published], ['ticket.status_changed'] * 2)
        self.assertEqual({payload['new_status'] for _, payload in published}, {'waiting'})
        self.assertEqual({payload['old_status'] for _, payload in published}, {'new'})
        self.assertEqual({kind for kind, _, _ in deliveries}, {'realtime', 'push'})
        self.assertEqual(len(deliveries), 4)
        self.assertEqual({payload['record_id'] for kind, _, payload in deliveries if kind == 'realtime'},
                         {single_id, bulk_id})
        self.assertEqual({payload['url'] for kind, _, payload in deliveries if kind == 'push'},
                         {f'/#ticket/{single_id}', f'/#ticket/{bulk_id}'})

    def test_bulk_status_does_not_count_noops_or_duplicate_ids(self):
        ticket_id = self.customer.post('/api/tickets', json={
            'title': 'Без перехода', 'description': 'Статус уже новый'
        }).json()['id']

        response = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [ticket_id, ticket_id], 'action': 'status', 'status': 'new'
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)
        self.assertEqual(response.json()['updated'], [])
        detail = self.admin.get(f'/api/tickets/{ticket_id}').json()
        self.assertFalse(any(event['kind'] == 'status' for event in detail['events']))

        manager_data = self.admin.post('/api/staff', json={
            'name': 'Менеджер массовых действий', 'email': 'bulk-manager@example.com',
            'password': 'password123', 'staff_role': 'manager'
        })
        self.assertEqual(manager_data.status_code, 201)
        manager = test_flows.TestClient(test_flows.service.app)
        self.assertEqual(manager.post('/api/login', json={
            'email': 'bulk-manager@example.com', 'password': 'password123'
        }).status_code, 200)
        manager_ticket = self.customer.post('/api/tickets', json={
            'title': 'Переход менеджера', 'description': 'Проверка sqlite row менеджера'
        }).json()['id']
        self.assertEqual(self.admin.patch(f'/api/tickets/{manager_ticket}/assignee', json={
            'assignee_id': manager_data.json()['id']
        }).status_code, 200)
        manager_response = manager.post('/api/tickets/bulk', json={
            'ticket_ids': [manager_ticket], 'action': 'status', 'status': 'waiting'
        })
        self.assertEqual(manager_response.status_code, 200)
        self.assertEqual(manager_response.json()['updated'], [manager_ticket])
        self.assertEqual(self.admin.get(f'/api/tickets/{manager_ticket}').json()['ticket']['status'], 'waiting')

    def test_bulk_status_propagates_unexpected_errors_and_rolls_back(self):
        first_id = self.customer.post('/api/tickets', json={
            'title': 'Первый переход', 'description': 'Должен откатиться'
        }).json()['id']
        second_id = self.customer.post('/api/tickets', json={
            'title': 'Ошибка перехода', 'description': 'Сымитировать неожиданную ошибку'
        }).json()['id']
        service = test_flows.service
        notify = service.notify
        dispatch = service.dispatch_webhooks
        realtime_publish = service.realtime_bus.publish
        push_enqueue = service.web_push.enqueue
        external = []
        calls = 0

        def fail_after_first(conn, user_id, ticket_id, kind, message, after_commit=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('unexpected status transition failure')
            return notify(conn, user_id, ticket_id, kind, message, after_commit=after_commit)

        service.notify = fail_after_first
        service.dispatch_webhooks = lambda event, payload, *, conn: external.append(('webhook', event, payload))
        service.realtime_bus.publish = lambda user_id, payload: external.append(('realtime', user_id, payload))
        service.web_push.enqueue = lambda user_id, payload: external.append(('push', user_id, payload))
        try:
            with self.assertRaisesRegex(RuntimeError, 'unexpected status transition failure'):
                self.admin.post('/api/tickets/bulk', json={
                    'ticket_ids': [first_id, second_id], 'action': 'status', 'status': 'waiting'
                })
        finally:
            service.notify = notify
            service.dispatch_webhooks = dispatch
            service.realtime_bus.publish = realtime_publish
            service.web_push.enqueue = push_enqueue

        self.assertEqual(external, [])
        self.assertFalse(any(notice['kind'] == 'status' and notice['ticket_id'] in (first_id, second_id)
                             for notice in self.customer.get('/api/notifications').json()))

        for ticket_id in (first_id, second_id):
            detail = self.admin.get(f'/api/tickets/{ticket_id}').json()
            self.assertEqual(detail['ticket']['status'], 'new')
            self.assertFalse(any(event['kind'] == 'status' for event in detail['events']))


if __name__ == '__main__':
    unittest.main()
