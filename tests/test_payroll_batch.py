import unittest
from tests import test_payroll as base


class PayrollBatchTests(unittest.TestCase):
    setUp = base.PayrollTests.setUp
    tearDown = base.PayrollTests.tearDown
    entry = base.PayrollTests.entry
    rate = base.PayrollTests.rate
    review = base.PayrollTests.review
    overview = base.PayrollTests.overview
    def preview(self, ids):
        return self.admin.post('/api/payroll/review-preview', json={'entry_ids': ids})

    def test_batch_preview_and_idempotency(self):
        self.rate()
        ids = [self.entry(30), self.entry(60)]
        preview = self.preview(ids)
        self.assertEqual(preview.status_code, 200, preview.text)
        p = preview.json()
        self.assertEqual(p['total_cents'], 3000)
        payload = {'entry_ids': ids, 'snapshot': p['snapshot'], 'request_id': 'batch-request-001'}
        for _ in range(2):
            result = self.admin.post('/api/payroll/review-batch', json=payload)
            self.assertEqual(result.status_code, 200, result.text)
        import app as service
        with service.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payroll_audit WHERE action='approve'").fetchone()[0], 2)

    def test_stale_rate_and_composition_are_atomic(self):
        self.rate()
        ids = [self.entry(30), self.entry(60)]
        p = self.preview(ids).json()
        self.rate(2100)
        payload = {'entry_ids': ids, 'snapshot': p['snapshot'], 'request_id': 'batch-request-002'}
        self.assertEqual(self.admin.post('/api/payroll/review-batch', json=payload).status_code, 409)
        self.assertTrue(all(e['state']=='pending' for e in self.overview().json()['entries']))
        p = self.preview(ids).json()
        self.review(ids[0], 'reject', 'Нужно уточнить')
        payload['snapshot'] = p['snapshot']
        self.assertEqual(self.admin.post('/api/payroll/review-batch', json=payload).status_code, 409)
        self.assertEqual(next(e for e in self.overview().json()['entries'] if e['id']==ids[1])['state'], 'pending')

    def test_exclusions_permissions_and_duplicate_ids(self):
        self.rate()
        a, b = self.entry(), self.entry()
        self.review(a, 'reject', 'Индивидуальная причина')
        p = self.preview([a,b]).json()
        self.assertEqual([e['id'] for e in p['excluded']], [a])
        self.assertIn('Индивидуальная причина', p['excluded'][0]['exclusion'])
        payload = {'entry_ids': [a,b], 'snapshot': p['snapshot'], 'request_id': 'batch-request-003'}
        for who in ('worker','other','client'):
            self.assertEqual(self.clients[who].post('/api/payroll/review-preview', json={'entry_ids':[b]}).status_code,403)
            self.assertEqual(self.clients[who].post('/api/payroll/review-batch', json=payload).status_code,403)
        self.assertEqual(self.admin.post('/api/payroll/review-batch', json=payload).status_code,200)
        self.assertEqual(self.preview([b,b]).status_code,422)

    def test_source_links_follow_current_task_access(self):
        task = self.worker.post('/api/tasks', json={'title':'Internal source','owner_id':self.ids['worker']}).json()
        import app as service
        with service.db() as conn:
            conn.execute('INSERT INTO task_time_entries(task_id,author_id,minutes,note,work_date,created_at) VALUES(?,?,30,?,?,?)', (task['id'],self.ids['worker'],'Source check',self.day,service.now()))
        row = next(e for e in self.overview(self.worker).json()['entries'] if e['source_kind']=='task')
        self.assertEqual(row['source_href'], f"#task/{task['id']}")
        with service.db() as conn:
            conn.execute('UPDATE team_tasks SET owner_id=?,created_by=? WHERE id=?', (self.ids['other'],self.ids['other'],task['id']))
        row = next(e for e in self.overview(self.worker).json()['entries'] if e['source_kind']=='task')
        self.assertIsNone(row['source_href'])
        row = next(e for e in self.overview().json()['entries'] if e['source_kind']=='task')
        self.assertEqual(row['source_href'], f"#task/{task['id']}")

    def test_concurrent_batches_cannot_double_approve(self):
        from concurrent.futures import ThreadPoolExecutor
        self.rate()
        ids = [self.entry(30), self.entry(60)]
        preview = self.preview(ids).json()
        def submit(index):
            return self.admin.post('/api/payroll/review-batch', json={'entry_ids': ids, 'snapshot': preview['snapshot'], 'request_id': f'concurrent-batch-{index}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit, range(2))), [200,409])
