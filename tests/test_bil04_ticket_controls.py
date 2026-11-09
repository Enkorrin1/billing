import unittest
from contextlib import contextmanager

import test_completion
import test_flows


service = test_flows.service


class TicketBulkControlTests(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def make_ticket(self, title):
        response = self.customer.post('/api/tickets', json={'title': title, 'description': 'Проверка правил заявки'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def ticket_events(self, ticket_id):
        return self.admin.get(f'/api/tickets/{ticket_id}').json()['events']

    def test_bulk_assignment_is_dispatcher_only_and_keeps_skipped_ids(self):
        open_id = self.make_ticket('Bulk assignment available')
        closed_id = self.make_ticket('Bulk assignment closed')
        target = self.admin.post('/api/staff', json={
            'name': 'Second worker', 'email': 'second-worker@example.com', 'password': 'password123'
        })
        self.assertEqual(target.status_code, 201, target.text)
        target_id = target.json()['id']
        with service.db() as conn:
            conn.execute("UPDATE tickets SET status='closed' WHERE id=?", (closed_id,))

        denied = self.employee.post('/api/tickets/bulk', json={
            'ticket_ids': [open_id], 'action': 'assignee', 'assignee_id': target_id
        })
        self.assertEqual(denied.status_code, 403)

        response = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [open_id, closed_id], 'action': 'assignee', 'assignee_id': target_id
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['updated'], [open_id])
        self.assertEqual(result['ticket_ids'], [open_id])
        self.assertEqual(result['count'], 1)
        self.assertEqual({open_id, closed_id} - set(result['updated']), {closed_id})
        assignment_events = [event for event in self.ticket_events(open_id) if event['kind'] == 'assignment']
        self.assertEqual(len(assignment_events), 1)
        self.assertEqual(assignment_events[0]['old_value'], None)
        self.assertEqual(assignment_events[0]['new_value'], str(target_id))
        self.assertFalse(any(event['kind'] == 'assignment' for event in self.ticket_events(closed_id)))

        noop = self.admin.post('/api/tickets/bulk', json={
            'ticket_ids': [open_id], 'action': 'assignee', 'assignee_id': target_id
        })
        self.assertEqual(noop.status_code, 200)
        self.assertEqual(noop.json()['updated'], [])
        self.assertEqual(len([event for event in self.ticket_events(open_id) if event['kind'] == 'assignment']), 1)
        self.assertEqual(self.admin.patch(f'/api/tickets/{closed_id}/assignee', json={'assignee_id': target_id}).status_code, 409)

    def test_priority_single_and_bulk_share_audit_and_participant_scope(self):
        single_id = self.make_ticket('Single priority')
        bulk_id = self.make_ticket('Bulk priority')
        participant_id = self.make_ticket('Executor-only priority')
        observer_data = self.admin.post('/api/staff', json={
            'name': 'Ticket observer', 'email': 'ticket-observer@example.com', 'password': 'password123'
        })
        self.assertEqual(observer_data.status_code, 201, observer_data.text)
        observer_id = observer_data.json()['id']
        observer = test_flows.TestClient(service.app)
        self.assertEqual(observer.post('/api/login', json={
            'email': 'ticket-observer@example.com', 'password': 'password123'
        }).status_code, 200)

        for ticket_id in (single_id, bulk_id):
            self.assertEqual(self.admin.patch(f'/api/tickets/{ticket_id}/assignee', json={
                'assignee_id': self.staff['id']
            }).status_code, 200)
        self.assertEqual(self.admin.patch(f'/api/admin/users/{self.staff["id"]}', json={
            'permissions': ['tasks']
        }).status_code, 200)
        self.assertEqual(self.admin.patch(f'/api/admin/tickets/{participant_id}', json={
            'executor_id': self.staff['id'], 'observer_ids': [observer_id]
        }).status_code, 200)

        single = self.employee.patch(f'/api/tickets/{single_id}/priority', json={'priority': 'high'})
        bulk = self.employee.post('/api/tickets/bulk', json={
            'ticket_ids': [bulk_id], 'action': 'priority', 'priority': 'high'
        })
        participant = self.employee.patch(f'/api/tickets/{participant_id}/priority', json={'priority': 'urgent'})
        self.assertEqual(single.status_code, 200, single.text)
        self.assertEqual(bulk.status_code, 200, bulk.text)
        self.assertEqual(bulk.json()['updated'], [bulk_id])
        self.assertEqual(participant.status_code, 200, participant.text)

        for ticket_id in (single_id, bulk_id):
            priority_events = [event for event in self.ticket_events(ticket_id) if event['kind'] == 'priority']
            self.assertEqual(len(priority_events), 1)
            self.assertEqual((priority_events[0]['old_value'], priority_events[0]['new_value']), ('normal', 'high'))

        observer_detail = observer.get(f'/api/tickets/{participant_id}')
        self.assertEqual(observer_detail.status_code, 200, observer_detail.text)
        self.assertEqual(observer.patch(f'/api/tickets/{participant_id}/priority', json={'priority': 'low'}).status_code, 404)
        observer_bulk = observer.post('/api/tickets/bulk', json={
            'ticket_ids': [participant_id], 'action': 'priority', 'priority': 'low'
        })
        self.assertEqual(observer_bulk.status_code, 200)
        self.assertEqual(observer_bulk.json()['updated'], [])

        with service.db() as conn:
            conn.execute("UPDATE tickets SET status='closed' WHERE id=?", (bulk_id,))
        closed_priority = self.employee.patch(f'/api/tickets/{bulk_id}/priority', json={'priority': 'urgent'})
        self.assertEqual(closed_priority.status_code, 409)
        closed_bulk = self.employee.post('/api/tickets/bulk', json={
            'ticket_ids': [bulk_id], 'action': 'priority', 'priority': 'urgent'
        })
        self.assertEqual(closed_bulk.json()['updated'], [])

    def test_bulk_assignment_and_priority_rollback_does_not_publish(self):
        service = test_flows.service
        for action in ('assignee', 'priority'):
            with self.subTest(action=action):
                first_id = self.make_ticket(f'{action} rollback first')
                second_id = self.make_ticket(f'{action} rollback second')
                original_notify = service.notify
                original_publish = service.realtime_bus.publish
                original_broadcast = service.realtime_bus.broadcast
                original_push = service.web_push.enqueue
                external = []
                calls = 0

                def fail_on_second_notify(conn, user_id, ticket_id, kind, message, after_commit=None):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise RuntimeError(f'unexpected {action} notification failure')
                    return original_notify(conn, user_id, ticket_id, kind, message, after_commit=after_commit)

                service.notify = fail_on_second_notify
                service.realtime_bus.publish = lambda user_id, payload: external.append(('realtime', user_id, payload))
                service.realtime_bus.broadcast = lambda user_ids, payload: external.append(('broadcast', user_ids, payload))
                service.web_push.enqueue = lambda user_id, payload: external.append(('push', user_id, payload))
                request = {'ticket_ids': [first_id, second_id], 'action': action}
                if action == 'assignee':
                    request['assignee_id'] = self.staff['id']
                else:
                    request['priority'] = 'high'
                try:
                    with self.assertRaisesRegex(RuntimeError, f'unexpected {action} notification failure'):
                        self.admin.post('/api/tickets/bulk', json=request)
                finally:
                    service.notify = original_notify
                    service.realtime_bus.publish = original_publish
                    service.realtime_bus.broadcast = original_broadcast
                    service.web_push.enqueue = original_push

                self.assertEqual(external, [])
                for ticket_id in (first_id, second_id):
                    detail = self.admin.get(f'/api/tickets/{ticket_id}').json()
                    expected_kind = 'assignment' if action == 'assignee' else 'priority'
                    self.assertFalse(any(event['kind'] == expected_kind for event in detail['events']))
                    if action == 'priority':
                        self.assertEqual(detail['ticket']['priority'], 'normal')
                    else:
                        self.assertIsNone(detail['ticket']['assignee_id'])


class AdminTicketCorrectionTests(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def ticket_events(self, ticket_id):
        return self.admin.get(f'/api/tickets/{ticket_id}').json()['events']

    def test_admin_status_correction_is_distinct_and_closed_ticket_uses_reopen(self):
        ticket_id = self.customer.post('/api/tickets', json={
            'title': 'Admin correction', 'description': 'Проверка корректировки'
        }).json()['id']
        corrected = self.admin.patch(f'/api/admin/tickets/{ticket_id}', json={'status': 'closed'})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        events = self.ticket_events(ticket_id)
        correction_events = [event for event in events if event['kind'] == 'admin_status_correction']
        self.assertEqual(len(correction_events), 1)
        self.assertEqual((correction_events[0]['old_value'], correction_events[0]['new_value']), ('new', 'closed'))
        self.assertFalse(any(event['kind'] == 'status' for event in events))

        missing_reason = self.admin.patch(f'/api/admin/tickets/{ticket_id}', json={'status': 'working'})
        self.assertEqual(missing_reason.status_code, 422)
        with service.db() as conn:
            conn.execute("UPDATE tickets SET accepted_at='2026-11-08T10:00:00', accepted_by_id=? WHERE id=?",
                         (self.customer.get('/api/me').json()['id'], ticket_id))
        reopened = self.admin.patch(f'/api/admin/tickets/{ticket_id}', json={
            'status': 'working', 'reopen_reason': 'Клиент обнаружил недочёт'
        })
        self.assertEqual(reopened.status_code, 200, reopened.text)
        detail = self.admin.get(f'/api/tickets/{ticket_id}').json()
        self.assertEqual(detail['ticket']['status'], 'new')
        self.assertIsNone(detail['ticket']['accepted_at'])
        reopen_events = [event for event in detail['events'] if event['kind'] == 'reopen']
        self.assertEqual(len(reopen_events), 1)
        self.assertEqual(reopen_events[0]['new_value'], 'Клиент обнаружил недочёт')

    def test_admin_reopen_commit_failure_does_not_publish(self):
        ticket_id = self.customer.post('/api/tickets', json={
            'title': 'Admin reopen rollback', 'description': 'Проверка отката'
        }).json()['id']
        closed = self.admin.patch(f'/api/admin/tickets/{ticket_id}', json={'status': 'closed'})
        self.assertEqual(closed.status_code, 200, closed.text)

        service = test_flows.service
        original_db = service.db
        original_publish = service.realtime_bus.publish
        original_broadcast = service.realtime_bus.broadcast
        original_push = service.web_push.enqueue
        external = []
        db_calls = 0

        @contextmanager
        def fail_admin_commit(sync_billing=True):
            nonlocal db_calls
            db_calls += 1
            with original_db(sync_billing=sync_billing) as conn:
                yield conn
                if db_calls == 2:
                    raise RuntimeError('forced admin reopen commit failure')

        service.db = fail_admin_commit
        service.realtime_bus.publish = lambda user_id, payload: external.append(('realtime', user_id, payload))
        service.realtime_bus.broadcast = lambda user_ids, payload: external.append(('broadcast', user_ids, payload))
        service.web_push.enqueue = lambda user_id, payload: external.append(('push', user_id, payload))
        try:
            with self.assertRaisesRegex(RuntimeError, 'forced admin reopen commit failure'):
                self.admin.patch(f'/api/admin/tickets/{ticket_id}', json={
                    'status': 'working', 'reopen_reason': 'Проверка ошибочного commit'
                })
        finally:
            service.db = original_db
            service.realtime_bus.publish = original_publish
            service.realtime_bus.broadcast = original_broadcast
            service.web_push.enqueue = original_push

        self.assertEqual(external, [])
        detail = self.admin.get(f'/api/tickets/{ticket_id}').json()
        self.assertEqual(detail['ticket']['status'], 'closed')
        self.assertFalse(any(event['kind'] == 'reopen' for event in detail['events']))
        self.assertEqual(len([event for event in detail['events'] if event['kind'] == 'admin_edit']), 1)


class AdminActTicketMetadataTests(unittest.TestCase):
    setUp = test_completion.CompletionTests.setUp
    tearDown = test_completion.CompletionTests.tearDown
    ok = test_completion.CompletionTests.ok

    def test_same_status_admin_metadata_edit_is_allowed_for_acted_ticket(self):
        self.ok(self.admin.post('/api/billing/deposit', json={
            'client_type': 'user', 'client_id': self.client_id, 'amount_rub': 20000, 'description': 'Test payment'
        }))
        ticket = self.ok(self.admin.post('/api/admin/tickets', json={
            'title': 'Актированная заявка', 'description': 'Описание работы', 'customer_id': self.client_id,
            'assignee_id': self.worker_id,
            'estimate': {'performer_effort_minutes': 120, 'pm_effort_minutes': 60, 'amount_rub': 11234, 'state': 'approved'}
        }))
        self.ok(self.admin.patch(f"/api/admin/tickets/{ticket['id']}", json={'status': 'done'}))
        act = self.ok(self.admin.post('/api/billing/invoices', json={
            'doc_type': 'act', 'client_type': 'user', 'client_id': self.client_id,
            'ticket_ids': [ticket['id']], 'service_entry_ids': []
        }))

        metadata = self.admin.patch(f"/api/admin/tickets/{ticket['id']}", json={
            'title': 'Исправленная тема', 'status': 'done'
        })
        self.assertEqual(metadata.status_code, 200, metadata.text)
        updated_ticket = self.ok(self.admin.get(f"/api/admin/tickets/{ticket['id']}"))['ticket']
        self.assertEqual(updated_ticket['title'], 'Исправленная тема')
        self.assertEqual(updated_ticket['act_invoice_id'], act['id'])

        self.assertEqual(self.admin.patch(f"/api/admin/tickets/{ticket['id']}", json={'status': 'closed'}).status_code, 409)
        self.assertEqual(self.admin.patch(f"/api/admin/tickets/{ticket['id']}", json={
            'customer_id': self.worker_id
        }).status_code, 409)
        self.assertEqual(self.admin.patch(f"/api/admin/tickets/{ticket['id']}", json={
            'organization_id': 999
        }).status_code, 409)
