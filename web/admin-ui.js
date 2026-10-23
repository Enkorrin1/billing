let tab = 'users';
let search = '';
let offset = 0;
let generation = 0;

export async function render(ctx) {
  const {state, api, shell, esc, toast, showError, openTicket} = ctx;
  if (state.user.role !== 'admin') return;
  const ownGeneration = ++generation;
  const [overview, users, organizations, tickets] = await Promise.all([
    api('/admin/overview'), api('/admin/users'), api('/admin/organizations'),
    api(`/admin/tickets?limit=50&offset=${offset}&q=${encodeURIComponent(search)}`)
  ]);
  if (ownGeneration !== generation || state.view !== 'admin') return;
  const roleNames = {admin:'Администратор', employee:'Сотрудник', customer:'Заказчик'};
  const statuses = {new:'Новая',working:'В работе',waiting:'Ожидает заказчика',done:'На проверке',closed:'Закрыта'};
  const rub = n => `${Number(n || 0).toLocaleString('ru-RU')} ₽`;
  const localDate = value => { if (!value) return ''; const d = new Date(value); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0,16); };
  const input = (name,label,value='',type='text',attrs='') => `<label>${label}<input class="field" name="${name}" type="${type}" value="${esc(String(value ?? ''))}" ${attrs}></label>`;
  const select = (name,label,options,value) => `<label>${label}<select class="field" name="${name}">${options.map(([id,text])=>`<option value="${esc(String(id))}" ${String(id)===String(value)?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;
  const checks = (name,options,values=[]) => `<div class="admin-checks">${options.map(([key,label])=>`<label><input type="checkbox" name="${name}" value="${key}" ${values.includes(key)?'checked':''}> ${esc(label)}</label>`).join('')}</div>`;
  const staffOptions = [[0,'Не назначен'],...users.filter(u=>u.role!=='customer'&&u.active).map(u=>[u.id,u.name])];
  const orgOptions = [[0,'Без компании'],...organizations.map(o=>[o.id,o.name])];
  const refresh = () => render(ctx).catch(showError);
  let body;
  if (tab === 'users' || tab === 'staff') {
    const list = users.filter(u=>(tab!=='staff'||u.role!=='customer') && `${u.name} ${u.email} ${u.organization_name||''}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')));
    body = `<table class="billing-table"><thead><tr><th>Пользователь</th><th>Роль / компания</th><th>Доступ</th><th>Действия</th></tr></thead><tbody>${list.map(u=>`<tr><td><strong>${esc(u.name)}</strong><div class="muted">${esc(u.email)}</div></td><td>${roleNames[u.role]}${u.is_manager?' · Менеджер':''}<div class="muted">${esc(u.organization_name||u.job_title||'')}</div></td><td>${u.active?'Активен':'Отключён'}</td><td><button class="button small" data-edit-user="${u.id}">Изменить</button></td></tr>`).join('')||'<tr><td colspan="4">Пользователи не найдены</td></tr>'}</tbody></table>`;
  } else if (tab === 'organizations') {
    body = `<div class="admin-company-grid">${organizations.filter(o=>o.name.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru'))).map(o=>`<section class="panel content"><div class="card-head"><h2>${esc(o.name)}</h2><button class="button small" data-edit-org="${o.id}">Изменить</button></div><p>Депозит: <strong>${rub(o.deposit_balance_rub)}</strong> · резерв: ${rub(o.held_rub)}</p><h3>Участники</h3>${o.members.map(m=>`<div class="admin-member"><span>${esc(m.name)} <small class="muted">${{owner:'Владелец',member:'Участник',viewer:'Наблюдатель'}[m.role]}</small></span><button class="button small" data-remove-member="${o.id}:${m.user_id}" aria-label="Убрать ${esc(m.name)} из компании">Убрать</button></div>`).join('')||'<p class="muted">Участников нет</p>'}<div class="admin-row-actions"><button class="button small" data-add-member="${o.id}">Добавить участника</button><button class="button small" data-team="${o.id}">Команда клиента</button></div><p class="muted">${[...new Set(o.assigned_team.map(t=>esc(t.name)))].join(', ')||'Команда клиента не назначена'}</p></section>`).join('')||'<p class="empty">Компании не найдены</p>'}</div>`;
  } else {
    body = `<table class="billing-table"><thead><tr><th>Заявка</th><th>Заказчик</th><th>Статус</th><th>Ответственный</th><th>Действия</th></tr></thead><tbody>${tickets.map(t=>`<tr><td><strong>№${t.id} · ${esc(t.title)}</strong></td><td>${esc(t.organization_name||t.customer_name)}</td><td>${statuses[t.status]||esc(t.status)}</td><td>${esc(t.assignee_name||'Не назначен')}</td><td><div class="admin-row-actions"><button class="button small" data-open-ticket="${t.id}">Открыть</button><button class="button small" data-edit-ticket="${t.id}">Изменить</button></div></td></tr>`).join('')||'<tr><td colspan="5">Заявки не найдены</td></tr>'}</tbody></table><div class="toolbar"><button class="button" id="admin-prev" ${offset===0?'disabled':''}>Назад</button><span>${offset+1}–${offset+tickets.length}</span><button class="button" id="admin-next" ${tickets.length<50?'disabled':''}>Далее</button></div>`;
  }
  shell('Администрирование', `<button class="button primary" id="admin-create">${tab==='organizations'?'Создать компанию':tab==='tickets'?'Создать заявку':'Добавить пользователя'}</button>`, `<div class="billing-kpi-grid">${[['Пользователи',overview.users_total],['Активные',overview.users_active],['Компании',overview.orgs_total],['Открытые заявки',overview.tickets_active]].map(([label,value])=>`<section class="panel content"><span class="muted">${label}</span><h2>${value}</h2></section>`).join('')}</div><section class="panel"><div class="toolbar"><div class="chips">${[['users','Все пользователи'],['staff','Сотрудники'],['organizations','Компании'],['tickets','Заявки']].map(([key,label])=>`<button class="button ${key===tab?'primary':''}" data-admin-tab="${key}" aria-pressed="${key===tab}">${label}</button>`).join('')}</div><form id="admin-search" class="admin-row-actions"><input class="field" name="q" aria-label="Поиск в администрировании" placeholder="Поиск" value="${esc(search)}"><button class="button">Найти</button></form></div><div class="table-scroll">${body}</div></section>`, {kicker:'Управление доступом и данными'});

  function dialog(title, fields, save) {
    const trigger=document.activeElement;
    const el=document.createElement('dialog');el.className='admin-dialog';
    el.innerHTML=`<form class="form"><div class="card-head"><h2 id="admin-dialog-title">${esc(title)}</h2><button type="button" class="button small" data-close aria-label="Закрыть">×</button></div>${fields}<p class="error" role="alert" hidden></p><button class="button primary" type="submit">Сохранить</button></form>`;
    el.setAttribute('aria-labelledby','admin-dialog-title');document.body.append(el);el.showModal();
    const close=()=>{el.close();el.remove();if(trigger?.isConnected)trigger.focus();};
    el.querySelector('[data-close]').onclick=close;el.addEventListener('cancel',e=>{e.preventDefault();close();});
    el.querySelector('form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;
      try{await save(new FormData(e.target));close();toast('Сохранено');await refresh();}catch(error){const msg=el.querySelector('[role=alert]');msg.textContent=error.message;msg.hidden=false;button.disabled=false;}
    };
    return el;
  }
  async function editUser(id) {
    const u=id?await api(`/admin/users/${id}`):{role:tab==='staff'?'employee':'customer',active:true};
    const cp=u.customer_profile||{},sp=u.staff_profile||{},ss=u.staff_settings||{};
    const roles=id?(u.role==='customer'?[['customer','Заказчик']]:[['employee','Сотрудник'],['admin','Администратор']]):Object.entries(roleNames);
    const functions=Object.entries({programmer:'Разработка',integrator:'Интеграции',devops:'DevOps',analyst:'Аналитика',designer:'Дизайн',qa:'Тестирование',sales:'Продажи',account:'Ведение клиентов',call_host:'Созвоны',support:'Поддержка',project_manager:'Управление проектами',team_lead:'Руководство',finance:'Финансы'});
    const permissions=Object.entries({tasks:'Задачи',meetings:'Встречи',sales:'Продажи',clients:'Команды клиентов',billing_read:'Просмотр финансов',billing_manage:'Финансовые операции'});
    const el=dialog(id?'Пользователь: '+u.name:'Новый пользователь', `${input('name','Имя',u.name,'text','required minlength="2" maxlength="100"')}${input('email','Email',u.email,'email','required')}${input('password',id?'Новый пароль (необязательно)':'Пароль','','password',id?'minlength="8"':'required minlength="8"')}${select('role','Роль',roles,u.role)}<label><input type="checkbox" name="active" ${u.active?'checked':''} ${id===state.user.id?'disabled':''}> Доступ включён</label><fieldset data-staff><legend>Сотрудник</legend><label><input type="checkbox" name="is_manager" ${u.is_manager?'checked':''}> Менеджер</label>${input('job_title','Должность',sp.job_title)}${input('bio','О сотруднике',sp.bio)}${input('hourly_rate_cents','Ставка выплат, центов USD / час',u.hourly_rate_cents,'number','min="1"')}<h3>Функции</h3>${checks('functions',functions,u.functions)}<h3>Разрешения</h3>${checks('permissions',permissions,ss.permissions)}${select('scope','Область доступа',[['assigned','Назначенные клиенты'],['department','Подразделение'],['all','Вся компания']],ss.scope||'assigned')}</fieldset><fieldset data-customer><legend>Заказчик</legend>${input('company_name','Название клиента',cp.company_name)}${input('phone','Телефон',cp.phone)}${select('organization_id','Компания',orgOptions,u.organization?.organization_id||0)}${select('org_role','Роль в компании',[['member','Участник'],['owner','Владелец'],['viewer','Наблюдатель']],u.organization?.org_role||'member')}</fieldset>`,async f=>{
      const data={name:f.get('name'),email:f.get('email'),role:f.get('role'),active:id===state.user.id?true:f.has('active')};
      if(f.get('password'))data.password=f.get('password');
      if(data.role!=='customer')Object.assign(data,{is_manager:f.has('is_manager'),job_title:f.get('job_title'),bio:f.get('bio'),functions:f.getAll('functions'),permissions:f.getAll('permissions'),scope:f.get('scope')});
      else {Object.assign(data,{company_name:f.get('company_name'),phone:f.get('phone')});const org=Number(f.get('organization_id'));if(!id||org!==(u.organization?.organization_id||0))data.organization_id=org;if(!id||f.get('org_role')!==u.organization?.org_role)data.org_role=f.get('org_role');}
      if(data.role!=='customer'&&f.get('hourly_rate_cents'))data.hourly_rate_cents=Number(f.get('hourly_rate_cents'));
      await api('/admin/users'+(id?'/'+id:''),{method:id?'PATCH':'POST',body:JSON.stringify(data)});
    });
    const update=()=>{const customer=el.querySelector('[name=role]').value==='customer';el.querySelector('[data-staff]').hidden=customer;el.querySelector('[data-customer]').hidden=!customer;};el.querySelector('[name=role]').onchange=update;update();
  }
  function editOrg(id) {
    const o=organizations.find(o=>o.id===id)||{};
    dialog(id?'Компания: '+o.name:'Новая компания',`${input('name','Название',o.name,'text','required minlength="2"')}${input('hourly_rate_rub','Тариф, ₽ / час',o.hourly_rate_rub||3000,'number','required min="100"')}${input('inn','ИНН',o.inn)}${input('kpp','КПП',o.kpp)}${input('legal_address','Юридический адрес',o.legal_address)}`,f=>api('/admin/organizations'+(id?'/'+id:''),{method:id?'PATCH':'POST',body:JSON.stringify({...Object.fromEntries(f),hourly_rate_rub:Number(f.get('hourly_rate_rub'))})}));
  }
  async function editTicket(id) {
    const data=id?await api(`/admin/tickets/${id}`):{};const t=data.ticket||{};
    dialog(id?'Заявка №'+id:'Новая заявка',`${input('title','Тема',t.title,'text','required minlength="2" maxlength="200"')}<label>Описание<textarea class="field" name="description" required minlength="2">${esc(t.description||'')}</textarea></label>${id?`<p>Заказчик: ${esc(t.customer_name)}</p>`:select('customer_id','Заказчик',users.filter(u=>u.role==='customer'&&u.active).map(u=>[u.id,u.name]),'')}${select('status','Статус',Object.entries(statuses),t.status||'new')}${select('priority','Приоритет',[['low','Низкий'],['normal','Обычный'],['high','Высокий'],['urgent','Критический']],t.priority||'normal')}${select('service_type','Тип услуги',[['support','Поддержка'],['development','Доработка'],['new_development','Разработка'],['integration','Интеграция'],['maintenance','Сопровождение'],['consultation','Консультация'],['other','Другое']],t.service_type||'support')}${select('assignee_id','Ответственный',staffOptions,t.assignee_id||0)}${select('executor_id','Соисполнитель',staffOptions,data.executor?.user_id||0)}${select('reviewer_id','Проверяющий',staffOptions,data.reviewer?.user_id||0)}<h3>Наблюдатели</h3>${checks('observer_ids',staffOptions.filter(([id])=>id),(data.observers||[]).map(p=>p.user_id))}${input('delivery_due_at','Срок выполнения',localDate(t.delivery_due_at),'datetime-local')}<p class="muted">Оценка и согласование стоимости доступны в карточке заявки. Изменения сохраняются в истории.</p>`,async f=>{
      const payload={...Object.fromEntries(f),assignee_id:Number(f.get('assignee_id')),executor_id:Number(f.get('executor_id')),reviewer_id:Number(f.get('reviewer_id')),observer_ids:f.getAll('observer_ids').map(Number)};
      if (!id || f.get('delivery_due_at') !== localDate(t.delivery_due_at)) payload.delivery_due_at=f.get('delivery_due_at')?new Date(f.get('delivery_due_at')).toISOString():'';
      else delete payload.delivery_due_at;
      if(!id){payload.customer_id=Number(f.get('customer_id'));if(!payload.assignee_id)payload.assignee_id=null;}
      await api('/admin/tickets'+(id?'/'+id:''),{method:id?'PATCH':'POST',body:JSON.stringify(payload)});
    });
  }
  const action=fn=>async event=>{try{await fn(event);}catch(error){showError(error);}};
  document.querySelectorAll('[data-admin-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.adminTab;search='';offset=0;refresh();});
  document.querySelector('#admin-search').onsubmit=e=>{e.preventDefault();search=new FormData(e.target).get('q');offset=0;refresh();};
  document.querySelector('#admin-create').onclick=action(()=>tab==='organizations'?editOrg():tab==='tickets'?editTicket():editUser());
  document.querySelectorAll('[data-edit-user]').forEach(b=>b.onclick=action(()=>editUser(Number(b.dataset.editUser))));
  document.querySelectorAll('[data-edit-org]').forEach(b=>b.onclick=()=>editOrg(Number(b.dataset.editOrg)));
  document.querySelectorAll('[data-edit-ticket]').forEach(b=>b.onclick=action(()=>editTicket(Number(b.dataset.editTicket))));
  document.querySelectorAll('[data-open-ticket]').forEach(b=>b.onclick=()=>openTicket(Number(b.dataset.openTicket)));
  document.querySelector('#admin-prev')?.addEventListener('click',()=>{offset=Math.max(0,offset-50);refresh();});
  document.querySelector('#admin-next')?.addEventListener('click',()=>{offset+=50;refresh();});
  document.querySelectorAll('[data-add-member]').forEach(b=>b.onclick=()=>{
    const org=organizations.find(o=>o.id===Number(b.dataset.addMember));
    dialog('Участник: '+org.name,`${select('user_id','Заказчик',users.filter(u=>u.role==='customer'&&u.active&&!u.organization_id).map(u=>[u.id,u.name]),'')}${select('role','Роль',[['member','Участник'],['owner','Владелец'],['viewer','Наблюдатель']],'member')}`,f=>api(`/admin/organizations/${org.id}/members`,{method:'POST',body:JSON.stringify({user_id:Number(f.get('user_id')),role:f.get('role')})}));
  });
  document.querySelectorAll('[data-remove-member]').forEach(b=>b.onclick=action(async()=>{if(!confirm('Убрать участника из компании? Доступ к общим заявкам будет закрыт.'))return;const [oid,uid]=b.dataset.removeMember.split(':');await api(`/admin/organizations/${oid}/members/${uid}`,{method:'DELETE'});await refresh();}));
  document.querySelectorAll('[data-team]').forEach(b=>b.onclick=()=>{
    const org=organizations.find(o=>o.id===Number(b.dataset.team));
    const roles=[['','Не назначен'],['sales','Продажи'],['account','Ведение клиента'],['project_manager','Руководитель проекта'],['technical','Технический куратор'],['specialist','Участник команды']];
    dialog('Команда: '+org.name,staffOptions.filter(([id])=>id).map(([id,name])=>`<fieldset><legend>${esc(name)}</legend>${checks('members',roles.filter(([role])=>role).map(([role,label])=>[id+':'+role,label]),org.assigned_team.filter(t=>t.user_id===id).map(t=>id+':'+t.responsibility))}</fieldset>`).join(''),f=>api(`/admin/organizations/${org.id}/team`,{method:'PUT',body:JSON.stringify({members:f.getAll('members').map(value=>({user_id:Number(value.split(':')[0]),responsibility:value.split(':')[1]}))})}));
  });
}
