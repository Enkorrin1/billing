import unittest
import test_flows

service = test_flows.service


class TeamRoles(unittest.TestCase):
    setUp = test_flows.Flows.setUp

    def test_create_each_specialty_without_elevating_access(self):
        for role in ('programmer', 'integrator', 'devops'):
            response = self.admin.post('/api/staff', json={'name':'Specialist', 'email':f'{role}@example.com', 'password':'password123', 'team_role':role})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['team_role'], role)
            self.assertEqual(response.json()['role'], 'employee')
            self.assertFalse(response.json()['is_manager'])
        self.assertIsNone(self.staff['team_role'])

    def test_assignment_profile_and_clearing(self):
        path = f"/api/staff/{self.staff['id']}/team-role"
        self.assertEqual(self.employee.patch('/api/profile/me', json={'name':'Worker', 'job_title':'Senior', 'bio':'Experience'}).status_code, 200)
        for role in ('programmer', 'integrator', 'devops', None):
            response = self.admin.patch(path, json={'team_role':role})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.employee.get('/api/profile/me').json()['team_role'], role)
            self.assertEqual(self.employee.get('/api/profile/me').json()['job_title'], 'Senior')
            self.assertFalse(self.employee.get('/api/me').json()['is_manager'])
        with service.db() as conn:
            self.assertEqual(conn.execute('SELECT role FROM users WHERE id=?', (self.staff['id'],)).fetchone()['role'], 'employee')

    def test_permissions_and_validation(self):
        path = f"/api/staff/{self.staff['id']}/team-role"
        for client in (self.employee, self.customer, self.other):
            self.assertEqual(client.patch(path, json={'team_role':'devops'}).status_code, 403)
        self.assertEqual(self.admin.patch(path, json={'team_role':'admin'}).status_code, 422)
        self.assertEqual(self.admin.patch(path, json={}).status_code, 422)
        self.assertEqual(self.admin.patch(f"/api/staff/{self.customer.get('/api/me').json()['id']}/team-role", json={'team_role':'devops'}).status_code, 404)
        self.admin.patch(f"/api/staff/{self.staff['id']}/availability", json={'active':False})
        self.assertEqual(self.admin.patch(path, json={'team_role':'integrator'}).status_code, 200)
        service.init_db()
        people = self.admin.get('/api/staff?include_inactive=true').json()
        self.assertEqual(next(p for p in people if p['id']==self.staff['id'])['team_role'], 'integrator')
