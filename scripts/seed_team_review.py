"""Prepare isolated, fictional data for browser verification of the team workspace."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['APP_DB']=str(ROOT/'output'/'team-review.db')
os.environ['BACKGROUND_JOBS']='0'
import app as domain
from fastapi.testclient import TestClient

PASSWORD='TeamReview123!'
with domain.db() as conn:
    if conn.execute("SELECT 1 FROM users WHERE email='admin@team.demo'").fetchone():
        print('Review data already exists; preserved.')
        raise SystemExit(0)
    admin=domain.create_user(conn,'Егор · руководитель','admin@team.demo',PASSWORD,'admin')
    customer=domain.create_user(conn,'Анна · Северная студия','client@team.demo',PASSWORD,'customer')
    customer2=domain.create_user(conn,'Илья · Альфа логистика','alpha@team.demo',PASSWORD,'customer')
domain.init_db()
client=TestClient(domain.app)
client.post('/api/login',json={'email':'admin@team.demo','password':PASSWORD}).raise_for_status()
staff=[]
for name,email,functions,title,department,permissions in [
    ('Мария Соколова','sales@team.demo',['sales','account','call_host'],'Менеджер по работе с клиентами','Клиенты',['sales','meetings','tasks']),
    ('Алексей Ковалёв','developer@team.demo',['programmer','integrator'],'Ведущий разработчик','Разработка',['tasks','meetings']),
    ('Виктория Морозова','pm@team.demo',['project_manager','analyst','call_host'],'Руководитель проектов','Разработка',['tasks','meetings','clients']),
    ('Дмитрий Волков','devops@team.demo',['devops','support'],'Инженер инфраструктуры','Разработка',['tasks','meetings']),
]:
    response=client.post('/api/staff',json={'name':name,'email':email,'password':PASSWORD,'functions':functions})
    response.raise_for_status();uid=response.json()['id'];staff.append(uid)
    person=next(p for p in client.get('/api/team').json()['people'] if p['id']==uid)
    client.put(f'/api/team/staff/{uid}',json={'functions':functions,'job_title':title,'department':department,'capacity_minutes':1800 if uid==staff[0] else 2400,
        'permissions':permissions,'scope':'assigned','responsibilities':'Отвечает за договорённости и следующий шаг по своим клиентам.' if uid==staff[0] else 'Отвечает за качество результата и своевременную передачу работы.',
        'version':person['updated_at']}).raise_for_status()
for cid in (customer['id'],customer2['id']):
    client.put(f'/api/team/clients/{cid}',json={'members':[{'user_id':staff[0],'responsibility':'sales'},{'user_id':staff[0],'responsibility':'account'},
        {'user_id':staff[2],'responsibility':'project_manager'},{'user_id':staff[1],'responsibility':'technical'},{'user_id':staff[3],'responsibility':'specialist'}]}).raise_for_status()
stamp=datetime.now(timezone.utc)
for title,owner,reviewer,mins,days,status in [('Подключить CRM к кабинету',staff[1],staff[2],720,2,'working'),('Согласовать требования к отчётам',staff[2],None,180,1,'new'),
    ('Проверить мониторинг сервера',staff[3],staff[1],120,-1,'new'),('Подготовить предложение клиенту',staff[0],None,120,1,'working')]:
    client.post('/api/team/tasks',json={'customer_id':customer['id'],'title':title,'owner_id':owner,'reviewer_id':reviewer,'planned_minutes':mins,
        'description':'Сохранить результат и передать его на проверку.','due_at':(stamp+timedelta(days=days)).isoformat(),'status':status}).raise_for_status()
for title,offset,status in [('Обсуждение интеграции с CRM',1,'planned'),('Итоги обследования процессов',-1,'held')]:
    client.post('/api/team/meetings',json={'customer_id':customer['id'],'title':title,'host_id':staff[0],'participants':[staff[1],staff[2]],
        'agenda':'Уточнить объём, сроки и ответственных.','starts_at':(stamp+timedelta(days=offset)).isoformat(),'duration_minutes':45,'status':status,
        'summary':'Согласовали этапы интеграции и состав данных.','next_steps':'Алексей подготовит техническую оценку.','internal_notes':'Внутренние организационные заметки.'}).raise_for_status()
for cid,title,stage in [(customer['id'],'Интеграция CRM и кабинета','proposal'),(customer2['id'],'Автоматизация отчётов','won')]:
    client.post('/api/team/deals',json={'customer_id':cid,'title':title,'owner_id':staff[0],'stage':stage,'next_action':'Согласовать план следующего этапа',
        'proposal':'Договорились об обследовании и поэтапной интеграции. Сначала оценка, затем согласование и выполнение.',
        'due_at':(stamp+timedelta(days=2)).isoformat()}).raise_for_status()
print('Isolated review database prepared: output/team-review.db')
