"""Task time is payable internally and linked ticket time is never counted twice."""
import unittest
from datetime import timedelta
import test_payroll as existing

service=existing.service
payroll=existing.payroll


class TaskTimeTests(unittest.TestCase):
    setUp=existing.PayrollTests.setUp
    tearDown=existing.PayrollTests.tearDown

    def create(self, **fields):
        r=self.admin.post('/api/tasks',json={'title':'Внутренняя работа','owner_id':self.ids['worker'],**fields})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def overview(self, client=None):
        return (client or self.admin).get('/api/payroll',params={'period_start':self.day,'period_end':self.day}).json()['entries']

    def test_internal_task_time_is_payable_idempotent_and_not_invoiced(self):
        task=self.create()
        path=f"/api/tasks/{task['id']}"
        detail=self.worker.get(path).json()
        self.assertTrue(detail['can_log_time'])
        payload={'minutes':30,'summary':'Подготовка внутренней документации','entry_date':self.day,'request_id':'task-time-entry-1'}
        response=self.worker.post(path+'/time-entries',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        again=self.worker.post(path+'/time-entries',json=payload)
        self.assertEqual(again.json()['id'],response.json()['id'])
        rows=[r for r in self.overview() if r['source_kind']=='task']
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual((row['minutes'],row['work_date'],row['ticket_id']),(30,self.day,None))
        self.assertEqual(len(self.worker.get(path).json()['time_entries']),1)
        self.assertEqual(self.overview(self.clients['other']),[])
        self.assertEqual(self.clients['other'].post(path+'/time-entries',json=payload).status_code,404)
        self.assertEqual(self.clients['client'].post(path+'/time-entries',json=payload).status_code,403)
        self.assertEqual(self.admin.post(f"/api/payroll/rates/{self.ids['worker']}",json={'cents_per_hour':2500}).status_code,200)
        self.assertEqual(self.admin.post(f"/api/payroll/entries/{row['id']}/review",json={'action':'approve'}).status_code,200)
        act=self.admin.post('/api/payroll/acts',json={'employee_id':self.ids['worker'],'period_start':self.day,'period_end':self.day,'entry_ids':[row['id']],'expected_total_cents':1250,'request_id':'task-payroll-act-1'})
        self.assertEqual(act.status_code,201,act.text)
        self.assertEqual(act.json()['items'][0]['source_kind'],'task')
        self.assertEqual(self.admin.post(f"/api/payroll/acts/{act.json()['id']}/paid").status_code,200)
        service.init_db()
        with service.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM service_entries').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM billing_transactions').fetchone()[0],0)
            self.assertFalse(conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_linked_ticket_limits_and_single_payroll_source(self):
        task=self.create(customer_id=self.ids['client'],ticket_id=self.ticket)
        path=f"/api/tasks/{task['id']}"
        payload={'minutes':30,'summary':'Реализация связанной задачи','entry_date':self.day,'request_id':'linked-task-time-1'}
        response=self.worker.post(path+'/time-entries',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        self.assertIsNotNone(response.json()['ticket_time_entry_id'])
        self.assertEqual(self.worker.post(path+'/time-entries',json=payload).json()['id'],response.json()['id'])
        self.assertEqual(sum(r['minutes'] for r in self.overview() if r['source_kind']=='work'),30)
        self.assertFalse(any(r['source_kind']=='task' for r in self.overview()))
        rejected=self.worker.post(path+'/time-entries',json={**payload,'minutes':1000,'request_id':'too-many-task-time'})
        self.assertEqual(rejected.status_code,409,rejected.text)
        detail=self.worker.get(path).json()
        self.assertEqual(len(detail['time_entries']),1)
        with service.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM time_entries').fetchone()[0],1)
        # The task editor does not gain ticket time permissions through a task link.
        other_task=self.create(customer_id=self.ids['client'],ticket_id=self.ticket,owner_id=self.ids['other'])
        other_path=f"/api/tasks/{other_task['id']}"
        self.assertFalse(self.clients['other'].get(other_path).json()['can_log_time'])
        self.assertIn(self.clients['other'].post(other_path+'/time-entries',json=payload).status_code,(403,404))

    def test_client_task_without_ticket_does_not_charge_customer_and_validates_date(self):
        task=self.create(customer_id=self.ids['client'])
        path=f"/api/tasks/{task['id']}/time-entries"
        payload={'minutes':15,'summary':'Внутренняя подготовка клиента'}
        self.assertEqual(self.worker.post(path,json={**payload,'entry_date':(payroll.work_today()+timedelta(days=1)).isoformat()}).status_code,422)
        self.assertEqual(self.worker.post(path,json={**payload,'minutes':True}).status_code,422)
        self.assertEqual(self.worker.post(path,json=payload).status_code,201)
        with service.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM service_entries').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM billing_transactions').fetchone()[0],0)
        self.assertEqual(sum(r['minutes'] for r in self.overview() if r['source_kind']=='task'),15)

    def test_legacy_payroll_registry_upgrade_preserves_reviews_and_act(self):
        # Simulate the pre-task registry with an already approved/issued work line.
        entry=self.worker.post(f'/api/tickets/{self.ticket}/time-entries',json={'minutes':30,'note':'Работа до обновления'}).json()['id']
        self.admin.post(f"/api/payroll/rates/{self.ids['worker']}",json={'cents_per_hour':2000})
        self.admin.post(f'/api/payroll/entries/{entry}/review',json={'action':'approve'})
        act=self.admin.post('/api/payroll/acts',json={'employee_id':self.ids['worker'],'period_start':self.day,'period_end':self.day,'entry_ids':[entry],'expected_total_cents':1000,'request_id':'legacy-task-migration-act'})
        self.assertEqual(act.status_code,201,act.text)
        act_id=act.json()['id']
        paid=self.admin.post(f'/api/payroll/acts/{act_id}/paid').json()['paid_at']
        with service.db() as conn:
            conn.commit()
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.executescript("""CREATE TABLE payroll_sources_old(id INTEGER PRIMARY KEY,source_kind TEXT NOT NULL CHECK(source_kind IN ('work','assessment','service')),source_id INTEGER NOT NULL,UNIQUE(source_kind,source_id));
            INSERT INTO payroll_sources_old SELECT * FROM payroll_sources;
            DROP TABLE payroll_sources;
            ALTER TABLE payroll_sources_old RENAME TO payroll_sources;""")
            conn.execute('PRAGMA foreign_keys=ON')
        service.init_db()
        rows=self.overview()
        self.assertEqual(next(r for r in rows if r['id']==entry)['amount_cents'],1000)
        restored=self.admin.get(f'/api/payroll/acts/{act_id}').json()
        self.assertEqual((restored['total_cents'],restored['paid_at'],restored['items'][0]['entry_id']),(1000,paid,entry))
        task=self.create()
        r=self.worker.post(f"/api/tasks/{task['id']}/time-entries",json={'minutes':15,'summary':'Работа после обновления'})
        self.assertEqual(r.status_code,201,r.text)
        row=next(r for r in self.overview() if r['source_kind']=='task')
        self.assertEqual(self.admin.post(f"/api/payroll/entries/{row['id']}/review",json={'action':'approve'}).status_code,200)
        with service.db() as conn:self.assertFalse(conn.execute('PRAGMA foreign_key_check').fetchall())
