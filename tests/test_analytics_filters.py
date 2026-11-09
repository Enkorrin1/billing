"""Analytics cohorts, actionable SLA failures and role protection."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['BACKGROUND_JOBS'] = '0'
from fastapi.testclient import TestClient

# Discovery imports this module before test_flows. Bind app's initial database
# to a process-local fixture before importing it; otherwise later legacy fixtures
# would reset the default application database despite setting APP_DB themselves.
_initial = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
_previous_app_db = os.environ.get('APP_DB')
os.environ['APP_DB'] = str(Path(_initial.name) / 'initial.db')
try:
    import app as service
finally:
    if _previous_app_db is None:
        os.environ.pop('APP_DB', None)
    else:
        os.environ['APP_DB'] = _previous_app_db


class AnalyticsFilters(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_path = service.DB_PATH
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, service, 'DB_PATH', self.old_path)
        service.DB_PATH = Path(self.temp.name) / 'analytics.db'
        service.init_db()
        with service.db() as conn:
            self.admin_id = service.create_user(conn, 'Admin', 'analytics-admin@test.local', 'password123', 'admin')['id']
            self.customer_id = service.create_user(conn, 'Client', 'analytics-client@test.local', 'password123', 'customer')['id']
            self.other_id = service.create_user(conn, 'Other', 'analytics-other@test.local', 'password123', 'customer')['id']
            self.worker_id = service.create_user(conn, 'Worker', 'analytics-worker@test.local', 'password123', 'employee')['id']
            for customer, title, created, due, response in [
                (self.customer_id, 'Late response', '2026-01-10', '2026-01-11', '2026-01-12'),
                (self.customer_id, 'Prior period', '2025-12-20', '2025-12-21', '2025-12-20'),
                (self.other_id, 'Other customer', '2026-01-10', '2026-01-11', '2026-01-10'),
                (self.customer_id, 'Pending response', '2026-01-15', '2099-01-01', None),
            ]:
                conn.execute('INSERT INTO tickets(customer_id,title,description,created_at,updated_at,response_due_at,first_staff_response_at) VALUES(?,?,?,?,?,?,?)', (customer,title,'Test description',created,created,due,response))
        self.clients = {}
        for role in ('admin', 'client', 'worker'):
            client = TestClient(service.app)
            self.addCleanup(client.close)
            self.assertEqual(client.post('/api/login', json={'email': f'analytics-{role}@test.local', 'password':'password123'}).status_code, 200)
            self.clients[role] = client
        self.params = {'date_from':'2026-01-01','date_to':'2026-01-31','customer_id':self.customer_id}

    def test_cohort_previous_period_and_csv_match(self):
        response = self.clients['admin'].get('/api/analytics/summary', params=self.params)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['total_tickets'], 2)
        self.assertEqual(data['previous_period']['total_tickets'], 1)
        self.assertEqual(data['sla_response_met_pct'], 0)
        self.assertIsNone(data['sla_estimate_met_pct'])
        detail = data['sla_details']['response']
        self.assertEqual((detail['met'],detail['total'],detail['pending']), (0,1,1))
        self.assertEqual([v['title'] for v in detail['violations']], ['Late response'])
        csv = self.clients['admin'].get('/api/analytics/export.csv', params=self.params).text
        self.assertIn('Late response', csv)
        self.assertIn('Pending response', csv)
        self.assertNotIn('Other customer', csv)
        self.assertNotIn('Prior period', csv)

    def test_no_data_target_configuration_and_validation(self):
        with patch.dict(os.environ, {'ANALYTICS_SLA_TARGET_PCT':'95'}):
            data = self.clients['admin'].get('/api/analytics/summary', params={'date_from':'2020-01-01','date_to':'2020-01-31'}).json()
        self.assertEqual(data['sla_target_pct'],95)
        self.assertIsNone(data['sla_response_met_pct'])
        self.assertIsNone(data['avg_response_minutes'])
        for route in ('summary', 'export.csv'):
            self.assertEqual(self.clients['admin'].get('/api/analytics/'+route, params={'date_from':'invalid'}).status_code,400)
            self.assertEqual(self.clients['admin'].get('/api/analytics/'+route, params={'date_from':'2026-02-01','date_to':'2026-01-01'}).status_code,400)

    def test_non_dispatchers_denied(self):
        for role in ('client','worker'):
            for route in ('summary','export.csv'):
                response = self.clients[role].get('/api/analytics/'+route, params=self.params)
                self.assertEqual(response.status_code,403,response.text)

    def test_open_overdue_delivery_is_actionable(self):
        with service.db() as conn:
            conn.execute("UPDATE tickets SET delivery_due_at='2026-01-20', estimate_due_at='2026-01-15' WHERE title='Late response'")
        data = self.clients['admin'].get('/api/analytics/summary', params=self.params).json()
        for metric in ('delivery', 'estimate'):
            self.assertEqual(data['sla_'+metric+'_met_pct'],0)
            self.assertEqual([v['title'] for v in data['sla_details'][metric]['violations']],['Late response'])

    def test_minsk_midnight_boundary_matches_csv(self):
        with service.db() as conn:
            for title, created in [('Minsk January', '2025-12-31T21:30:00+00:00'), ('Minsk February', '2026-01-31T21:30:00+00:00')]:
                conn.execute('INSERT INTO tickets(customer_id,title,description,created_at,updated_at) VALUES(?,?,?,?,?)', (self.customer_id,title,'Boundary test',created,created))
        data = self.clients['admin'].get('/api/analytics/summary', params=self.params).json()
        self.assertEqual(data['total_tickets'], 3)
        csv = self.clients['admin'].get('/api/analytics/export.csv', params=self.params).text
        self.assertIn('Minsk January', csv)
        self.assertNotIn('Minsk February', csv)


if __name__ == '__main__':
    unittest.main()
