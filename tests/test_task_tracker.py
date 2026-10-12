import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient
import test_team_management

service=test_team_management.service


class TaskTracker(unittest.TestCase):
    setUp=test_team_management.TeamManagement.setUp
    def create(self,client=None,**changes):
        payload={'title':'Small internal task','owner_id':self.uid,'request_id':'create-task-unique'}
        payload.update(changes)
        response=(client or self.employee).post('/api/tasks',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        return response.json(),payload

    def test_internal_creation_does_not_require_client_and_is_idempotent(self):
        task,payload=self.create()
        self.assertIsNone(task['customer_id'])
        self.assertEqual(task['customer_name'],'Внутренняя задача')
        again=self.employee.post('/api/tasks',json=payload)
        self.assertEqual(again.json()['id'],task['id'])
        self.assertEqual(len(self.employee.get('/api/team').json()['tasks']),1)
        self.assertEqual(self.reviewer.get(f"/api/tasks/{task['id']}").status_code,404)
        self.assertEqual(self.customer.get(f"/api/tasks/{task['id']}").status_code,403)

    def test_partial_edits_lock_version_and_preserve_unedited_fields(self):
        task,_=self.create(description='Keep this description')
        path=f"/api/tasks/{task['id']}"
        changed=self.employee.patch(path,json={'version':task['version'],'priority':'high'})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(changed.json()['description'],'Keep this description')
        self.assertEqual(self.employee.patch(path,json={'version':task['version'],'title':'Stale title'}).status_code,409)
        self.assertEqual(self.employee.patch(path,json={'version':changed.json()['version'],'title':None}).status_code,422)
        self.assertEqual(self.employee.patch(path,json={'version':changed.json()['version'],'due_at':'2026-11-02T10:00:00'}).status_code,422)

    def test_task_can_be_created_from_accessible_ticket_without_global_client_access(self):
        tid=self.customer.post('/api/tickets',json={'title':'Client request','description':'Prepare result'}).json()['id']
        self.admin.put(f'/api/team/tickets/{tid}/participants',json={'members':[{'user_id':self.uid,'participation':'executor'}]})
        task,_=self.create(customer_id=self.cid,ticket_id=tid)
        self.assertEqual(task['ticket_id'],tid)
        self.assertEqual(self.reviewer.post('/api/tasks',json={'title':'Cannot link private request','owner_id':self.second,'customer_id':self.cid,'ticket_id':tid}).status_code,404)

    def test_blocking_is_separate_and_completion_requires_checklist(self):
        task,_=self.create()
        path=f"/api/tasks/{task['id']}"
        item=self.employee.post(path+'/checklist',json={'body':'Verify result'}).json()
        task=self.employee.get(path).json()
        blocked=self.employee.patch(path,json={'version':task['version'],'blocked_reason':'Waiting for credentials'})
        self.assertEqual(blocked.status_code,200,blocked.text)
        self.assertEqual(blocked.json()['status'],'new')
        self.assertEqual(self.employee.patch(path,json={'version':blocked.json()['version'],'status':'done'}).status_code,422)
        cleared=self.employee.patch(path,json={'version':blocked.json()['version'],'blocked_reason':''}).json()
        self.assertEqual(self.employee.patch(path,json={'version':cleared['version'],'status':'done'}).status_code,409)
        checked=self.employee.patch(path+f"/checklist/{item['id']}",json={'version':item['version'],'checked':True})
        self.assertEqual(checked.status_code,200,checked.text)
        completed=self.employee.patch(path,json={'version':checked.json()['version'],'status':'done'})
        self.assertEqual(completed.status_code,200,completed.text)
        self.assertEqual(self.employee.post(path+'/checklist',json={'body':'Late new item'}).status_code,409)

    def test_review_only_notifies_reviewer_and_owner_cannot_accept(self):
        task,_=self.create(client=self.admin,reviewer_id=self.second)
        path=f"/api/tasks/{task['id']}"
        response=self.employee.patch(path,json={'version':task['version'],'status':'review'})
        self.assertEqual(response.status_code,200,response.text)
        events=self.reviewer.get('/api/team').json()['events']
        self.assertTrue(any(e['entity_id']==task['id'] and e['event_kind']=='review' for e in events))
        self.assertEqual(self.employee.patch(path,json={'version':response.json()['version'],'status':'done'}).status_code,403)
        accepted=self.reviewer.patch(path,json={'version':response.json()['version'],'status':'done'})
        self.assertEqual(accepted.status_code,200,accepted.text)

    def test_owner_can_add_initial_reviewer_but_cannot_remove_them_to_self_accept(self):
        task,_=self.create()
        path=f"/api/tasks/{task['id']}"
        self.assertEqual(self.employee.patch(path,json={'version':task['version'],'reviewer_id':self.uid}).status_code,422)
        reviewed=self.employee.patch(path,json={'version':task['version'],'reviewer_id':self.second})
        self.assertEqual(reviewed.status_code,200,reviewed.text)
        self.assertEqual(self.employee.patch(path,json={'version':reviewed.json()['version'],'reviewer_id':None,'status':'done'}).status_code,403)

    def test_checklist_requires_edit_permission_and_rejects_stale_toggle(self):
        task,_=self.create(client=self.admin,participants=[self.second])
        path=f"/api/tasks/{task['id']}"
        self.assertEqual(self.reviewer.get(path).status_code,200)
        self.assertFalse(self.reviewer.get(path).json()['can_edit'])
        self.assertEqual(self.reviewer.post(path+'/checklist',json={'body':'Not allowed'}).status_code,403)
        item=self.employee.post(path+'/checklist',json={'body':'One item'}).json()
        first=self.employee.patch(path+f"/checklist/{item['id']}",json={'version':item['version'],'checked':True})
        self.assertEqual(first.status_code,200)
        changed_item=first.json()['checklist'][0]
        renamed=self.employee.patch(path+f"/checklist/{item['id']}",json={'version':changed_item['version'],'body':'Updated checklist text'})
        self.assertEqual(renamed.status_code,200,renamed.text)
        self.assertEqual(renamed.json()['checklist'][0]['body'],'Updated checklist text')
        self.assertEqual(self.employee.patch(path+f"/checklist/{item['id']}",json={'version':item['version'],'checked':False}).status_code,409)

    def test_comments_mentions_are_scoped_deduplicated_and_quiet(self):
        task,_=self.create(client=self.admin,participants=[self.second])
        path=f"/api/tasks/{task['id']}"
        body={'body':'@Reviewer Please check the result','request_id':'comment-one-key'}
        self.assertEqual(self.employee.post(path+'/comments',json=body).status_code,201)
        self.assertEqual(self.employee.post(path+'/comments',json=body).status_code,201)
        d=self.reviewer.get(path).json()
        self.assertEqual(len(d['comments']),1)
        self.assertIn(self.second,d['comments'][0]['mentions'])
        self.employee.post(path+'/comments',json={**body,'request_id':'comment-second-key'})
        events=[e for e in self.reviewer.get('/api/team').json()['events'] if e['entity_id']==task['id'] and e['event_kind']=='mention' and not e['read_at']]
        self.assertEqual(len(events),1)
        self.reviewer.put(path+'/watch',json={'muted':True})
        self.employee.post(path+'/comments',json={**body,'request_id':'comment-third-key'})
        events2=[e for e in self.reviewer.get('/api/team').json()['events'] if e['entity_id']==task['id'] and e['event_kind']=='mention']
        self.assertEqual(len(events2),1)
        outsider=self.admin.post('/api/staff',json={'name':'Outside User','email':'outsider@example.com','password':'password123'}).json()['id']
        bad=self.employee.post(path+'/comments',json={'body':'@Outside User secret','request_id':'comment-denied-key','mention_ids':[outsider]})
        self.assertEqual(bad.status_code,422)

    def test_non_significant_edits_do_not_notify_but_deadline_changes_do(self):
        task,_=self.create(client=self.admin)
        path=f"/api/tasks/{task['id']}"
        event=self.employee.get('/api/team').json()['events'][0]
        self.employee.post(f"/api/team/notifications/{event['id']}/read")
        edited=self.admin.patch(path,json={'version':task['version'],'description':'Minor wording update'}).json()
        self.assertEqual(len([e for e in self.employee.get('/api/team').json()['events'] if not e['read_at']]),0)
        deadline=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        self.admin.patch(path,json={'version':edited['version'],'due_at':deadline})
        self.assertTrue(any(e['event_kind']=='change' and not e['read_at'] for e in self.employee.get('/api/team').json()['events']))

    def test_uploads_are_private_idempotent_and_recoverable(self):
        task,_=self.create()
        path=f"/api/tasks/{task['id']}"
        files={'file':('../result.txt',b'Private task result','text/plain')}
        first=self.employee.post(path+'/files',files=files,data={'request_id':'file-unique-key'})
        self.assertEqual(first.status_code,201,first.text)
        second=self.employee.post(path+'/files',files=files,data={'request_id':'file-unique-key'})
        self.assertEqual(len(second.json()['files']),1)
        fid=first.json()['files'][0]['id']
        download=self.employee.get(path+f'/files/{fid}')
        self.assertEqual(download.content,b'Private task result')
        self.assertEqual(download.headers['x-content-type-options'],'nosniff')
        self.assertEqual(self.reviewer.get(path+f'/files/{fid}').status_code,404)
        self.assertEqual(self.customer.get(path+f'/files/{fid}').status_code,403)
        self.assertEqual(self.employee.post(path+f'/files/{fid}/hide').status_code,200)
        self.assertEqual(self.employee.get(path+f'/files/{fid}').status_code,404)
        self.assertEqual(self.employee.post(path+f'/files/{fid}/restore').status_code,200)
        self.assertEqual(self.employee.get(path+f'/files/{fid}').content,b'Private task result')
        self.assertEqual(self.employee.post(path+'/files',files={'file':('bad.html',b'<script>bad</script>','text/html')},data={'request_id':'bad-upload-key'}).status_code,422)

    def test_archive_is_reversible_and_preserves_comments_and_checklist(self):
        task,_=self.create()
        path=f"/api/tasks/{task['id']}"
        self.employee.post(path+'/comments',json={'body':'Keep history','request_id':'archive-comment-key'})
        self.employee.post(path+'/checklist',json={'body':'Keep checklist'})
        task=self.employee.get(path).json()
        archived=self.employee.patch(path,json={'version':task['version'],'status':'cancelled'}).json()
        self.assertEqual(len(archived['comments']),1)
        restored=self.employee.patch(path,json={'version':archived['version'],'status':'new'}).json()
        self.assertEqual(len(restored['checklist']),1)
        self.assertEqual(len(restored['comments']),1)


class Migration(unittest.TestCase):
    def test_nullable_customer_migration_preserves_tasks_and_memberships(self):
        import task_tracker
        with tempfile.TemporaryDirectory() as folder:
            conn=sqlite3.connect(Path(folder)/'legacy.db');conn.row_factory=sqlite3.Row
            conn.executescript('''PRAGMA foreign_keys=ON;
            CREATE TABLE users(id INTEGER PRIMARY KEY);
            CREATE TABLE team_tasks(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES users(id),
                owner_id INTEGER REFERENCES users(id),created_by INTEGER REFERENCES users(id),status TEXT,version INTEGER);
            CREATE TABLE task_participants(task_id INTEGER REFERENCES team_tasks(id) ON DELETE CASCADE,user_id INTEGER REFERENCES users(id));
            CREATE TABLE team_notifications(id INTEGER PRIMARY KEY,user_id INTEGER,entity TEXT,entity_id INTEGER,created_at TEXT,read_at TEXT);
            INSERT INTO users VALUES(1);INSERT INTO users VALUES(2);
            INSERT INTO team_tasks VALUES(10,1,2,2,'new',4);INSERT INTO task_participants VALUES(10,2);''')
            task_tracker.init_schema(conn)
            self.assertEqual(conn.execute('SELECT version FROM team_tasks WHERE id=10').fetchone()[0],4)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM task_participants').fetchone()[0],1)
            conn.execute('INSERT INTO team_tasks(id,customer_id,owner_id,created_by,status,version) VALUES(11,NULL,2,2,\'new\',1)')
            self.assertFalse(conn.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0],1)
            conn.close()


if __name__=='__main__':unittest.main()
