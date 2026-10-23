const today = () => new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10);
const money = cents => new Intl.NumberFormat('ru-RU', {style: 'currency', currency: 'USD'}).format(cents / 100);
const kinds = {work:'Фактическая работа',assessment:'Оценки и переоценки',service:'Сопровождение',task:'Работа по задачам'};
const names = {pending: 'На проверке', approved: 'Подтверждено', rejected: 'Отклонено'};
let filters, currentUser, generation = 0;

export async function render(ctx) {
  const {state, api, shell, esc, hours, toast} = ctx;
  if (state.user.role === 'customer') return;
  const admin = state.user.role === 'admin';
  if (currentUser !== state.user.id) {
    currentUser = state.user.id;
    filters = {period_start: today().slice(0, 7) + '-01', period_end: today(), employee_id: '', status: 'all'};
  }
  const token = ++generation;
  shell(admin ? 'Выплаты исполнителям' : 'Мои начисления', '', '<section class="panel content" role="status">Загружаем часы и акты…</section>');
  let data;
  try {
    const query = new URLSearchParams({period_start: filters.period_start, period_end: filters.period_end});
    if (filters.employee_id) query.set('employee_id', filters.employee_id);
    data = await api('/payroll?' + query);
  } catch (error) {
    if (token !== generation || state.view !== 'payroll') return;
    shell('Выплаты исполнителям', '', `<section class="panel content"><p role="alert">${esc(error.message)}</p><button class="button" id="payroll-retry">Повторить</button></section>`);
    document.querySelector('#payroll-retry').onclick = () => render(ctx);
    return;
  }
  if (token !== generation || state.view !== 'payroll') return;
  const ready = data.entries.filter(e => e.state === 'approved' && !e.act_id);
  const pending = data.entries.filter(e => e.state === 'pending');
  const total = ready.reduce((sum, e) => sum + e.amount_cents, 0);
  const unpaid = data.acts.filter(a => !a.paid_at).reduce((sum, a) => sum + a.total_cents, 0);
  const person = data.employees.find(p => String(p.id) === filters.employee_id);
  const visible = data.entries.filter(e => filters.status === 'all' || (filters.status === 'included' ? e.act_id : e.state === filters.status && !e.act_id));
  const stats = `<div class="payroll-stats"><section class="panel content"><small>Часы на проверке</small><h2>${hours(pending.reduce((s,e)=>s+e.minutes,0))}</h2><span>Записей: ${pending.length}</span></section><section class="panel content"><small>Подтверждено, без акта</small><h2>${money(total)}</h2><span>${hours(ready.reduce((s,e)=>s+e.minutes,0))}</span></section><section class="panel content"><small>К оплате по актам периода</small><h2>${money(unpaid)}</h2><span>Актов: ${data.acts.filter(a=>!a.paid_at).length}</span></section></div>`;
  const rate = admin && person ? `<section class="panel content"><h2>Ставка · ${esc(person.name)}</h2><form id="payroll-rate" class="payroll-filters"><label>USD за час<input class="field" name="rate" type="number" min="0.01" max="1000000" step="0.01" required value="${person.cents_per_hour ? (person.cents_per_hour/100).toFixed(2) : ''}" placeholder="Например, 20.00"></label><button class="button">Сохранить ставку</button></form><p class="muted">Ставка фиксируется при подтверждении часов. Изменение ставки не пересчитывает подтверждённые записи и акты.</p></section>` : '';
  const rows = visible.map(e => `<article class="payroll-entry"><div><div class="row"><strong>${esc(e.employee_name)} · ${hours(e.minutes)}</strong><span class="badge">${e.act_id ? 'В акте ИСП-'+String(e.act_id).padStart(6,'0') : names[e.state]}</span></div><p><span class="badge">${kinds[e.source_kind]||kinds.work}</span> ${e.ticket_id?`<a href="#ticket/${e.ticket_id}">#${e.ticket_id} · ${esc(e.ticket_title)}</a>`:esc(e.ticket_title)}</p><p class="payroll-note">${esc(e.note)}</p><small>${esc(e.work_date)}${e.cents_per_hour ? ' · '+money(e.cents_per_hour)+'/час' : ''}${e.reason ? ' · Причина: '+esc(e.reason) : ''}</small></div><div class="payroll-entry-side"><strong>${e.amount_cents == null ? '—' : money(e.amount_cents)}</strong>${admin && !e.act_id ? e.state === 'pending' ? `<div class="row"><button class="button primary small" data-review="${e.id}" data-action="approve">Подтвердить</button><button class="button small" data-reject="${e.id}">Отклонить</button></div><form class="form" data-reject-form="${e.id}" hidden><label>Причина отклонения<textarea name="reason" required maxlength="2000"></textarea></label><div class="row"><button class="button">Отклонить часы</button><button class="button" type="button" data-cancel-reject="${e.id}">Отмена</button></div></form>` : `<button class="button small" data-review="${e.id}" data-action="reset">Вернуть на проверку</button>` : ''}</div></article>`).join('');
  const acts = data.acts.map(a => `<article class="payroll-entry"><div><strong>ИСП-${String(a.id).padStart(6,'0')} · ${esc(a.employee_name)}</strong><p>${esc(a.period_start)} — ${esc(a.period_end)} · ${hours(a.total_minutes)}</p><span class="badge">${a.paid_at ? 'Оплачен' : 'Ожидает оплаты'}</span></div><div class="payroll-entry-side"><strong>${money(a.total_cents)}</strong><div class="row"><a class="button small" href="/api/payroll/acts/${a.id}/print" target="_blank" rel="noopener">Открыть акт / PDF</a>${admin && !a.paid_at ? `<button class="button small" data-paid="${a.id}">Отметить оплату</button>` : ''}</div></div></article>`).join('');
  shell(admin ? 'Выплаты исполнителям' : 'Мои начисления', '', `
    <style>.payroll-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:20px 0}.payroll-filters{display:flex;flex-wrap:wrap;gap:16px;align-items:end}.payroll-filters label{display:grid;gap:6px;flex:1;min-width:150px}.payroll-entry{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;padding:22px 0;border-bottom:1px solid var(--line)}.payroll-entry-side{display:grid;gap:12px;align-content:start;justify-items:end}.payroll-entry .row{flex-wrap:wrap}.payroll-note{white-space:pre-wrap;overflow-wrap:anywhere}.payroll-stack{display:grid;gap:20px}.payroll-entry-side form{max-width:300px}.payroll-entry-side form[hidden]{display:none}@media(max-width:700px){.payroll-stats{grid-template-columns:1fr}.payroll-entry{grid-template-columns:1fr}.payroll-entry-side{justify-items:start}.payroll-filters label{min-width:100%}}</style>
    <p class="muted">Работа по заявкам и задачам, оценки, переписки и созвоны → подтверждение администратора → акт → оплата. Все суммы в USD.</p>
    <section class="panel content"><form id="payroll-filter" class="payroll-filters">${admin ? `<label>Исполнитель<select class="field" name="employee_id"><option value="">Вся команда</option>${data.employees.map(p=>`<option value="${p.id}" ${String(p.id)===filters.employee_id?'selected':''}>${esc(p.name)}${p.active?'':' (неактивен)'}</option>`).join('')}</select></label>` : ''}<label>С даты<input class="field" type="date" name="period_start" value="${filters.period_start}" required></label><label>По дату включительно<input class="field" type="date" name="period_end" value="${filters.period_end}" required></label><button class="button primary">Показать</button></form><p class="muted">Период определяется по дате работы, UTC+3. Учитываются все версии оценок, в том числе отклонённые и пересмотренные, а также внесённые переписки, созвоны и встречи.</p></section>
    ${stats}<section class="panel content"><h2>Все трудозатраты за период</h2><div class="row" style="flex-wrap:wrap;gap:20px">${Object.entries(kinds).map(([kind,label])=>`<span>${label}: <strong>${hours(data.entries.filter(e=>e.source_kind===kind).reduce((sum,e)=>sum+e.minutes,0))}</strong></span>`).join('')}<span>Всего: <strong>${hours(data.entries.reduce((sum,e)=>sum+e.minutes,0))}</strong></span></div><p class="muted">В акт включаются только подтверждённые записи. Отклонённые трудозатраты сохраняются в истории.</p></section><div id="payroll-message" role="status" aria-live="polite"></div><div class="payroll-stack">${rate}
    ${admin ? `<section class="panel content"><h2>Подготовить акт</h2><p>${person ? `${esc(person.name)} · ${filters.period_start} — ${filters.period_end}` : 'Выберите одного исполнителя в фильтре выше.'}</p><p>В акт войдут ${ready.length} подтверждённых записей, ещё не включённых в акты, на <strong>${money(total)}</strong>. ${pending.length ? `На проверке: ${pending.length}. Эти записи не войдут в акт.` : ''}</p><button class="button primary" id="payroll-create" ${!person || !ready.length ? 'disabled' : ''}>Сформировать акт</button><p class="muted">После формирования состав и суммы фиксируются. Пока используется предварительная печатная форма.</p></section>` : ''}
    <section class="panel content"><div class="row"><h2>Записи времени</h2><label>Статус <select class="field" id="payroll-status">${Object.entries({all:'Все записи',pending:'На проверке',approved:'Подтверждено, без акта',rejected:'Отклонено',included:'Включено в акт'}).map(([k,v])=>`<option value="${k}" ${filters.status===k?'selected':''}>${v}</option>`).join('')}</select></label></div>${rows || '<p class="muted">За выбранный период таких записей нет.</p>'}</section>
    <section class="panel content"><h2>Акты за период</h2>${acts || '<p class="muted">Актов за выбранный период пока нет.</p>'}</section></div>`);
  const message = (text, error=false) => {const el=document.querySelector('#payroll-message');if(el){el.className=error?'notice':'';el.textContent=text;el.setAttribute('role',error?'alert':'status');el.scrollIntoView({block:'nearest'});}};
  const mutate = async (button, path, payload, success) => {
    button.disabled = true;
    try {await api(path,{method:'POST',body:JSON.stringify(payload)});toast(success);await render(ctx);}
    catch(error){message(error.message,true);button.disabled=false;}
  };
  document.querySelector('#payroll-filter').onsubmit = e => {e.preventDefault();const values=Object.fromEntries(new FormData(e.target));if(values.period_start>values.period_end){message('Начало периода должно быть не позже окончания',true);return;}filters={...filters,...values};render(ctx);};
  document.querySelector('#payroll-status').onchange = e => {filters.status=e.target.value;render(ctx);};
  document.querySelector('#payroll-rate')?.addEventListener('submit',e=>{e.preventDefault();const cents=Math.round(Number(e.target.elements.rate.value)*100);mutate(e.target.querySelector('button'),`/payroll/rates/${person.id}`,{cents_per_hour:cents},'Ставка сохранена');});
  document.querySelectorAll('[data-review]').forEach(b=>b.onclick=()=>mutate(b,`/payroll/entries/${b.dataset.review}/review`,{action:b.dataset.action},b.dataset.action==='approve'?'Часы подтверждены':'Часы возвращены на проверку'));
  document.querySelectorAll('[data-reject]').forEach(b=>b.onclick=()=>{const f=document.querySelector(`[data-reject-form="${b.dataset.reject}"]`);f.hidden=false;f.elements.reason.focus();});
  document.querySelectorAll('[data-cancel-reject]').forEach(b=>b.onclick=()=>{document.querySelector(`[data-reject-form="${b.dataset.cancelReject}"]`).hidden=true;});
  document.querySelectorAll('[data-reject-form]').forEach(f=>f.onsubmit=e=>{e.preventDefault();mutate(f.querySelector('button'),`/payroll/entries/${f.dataset.rejectForm}/review`,{action:'reject',reason:f.elements.reason.value},'Часы отклонены');});
  // Retain the same key for retries after an ambiguous network failure.
  const actRequest = {employee_id:person?.id,period_start:filters.period_start,period_end:filters.period_end,entry_ids:ready.map(e=>e.id),expected_total_cents:total,request_id:crypto.randomUUID()};
  document.querySelector('#payroll-create')?.addEventListener('click',e=>mutate(e.currentTarget,'/payroll/acts',actRequest,'Акт сформирован'));
  document.querySelectorAll('[data-paid]').forEach(b=>b.onclick=()=>{
    if (b.dataset.confirmed !== 'yes') {b.dataset.confirmed='yes';b.textContent='Подтвердить получение оплаты';return;}
    mutate(b,`/payroll/acts/${b.dataset.paid}/paid`,{},'Оплата отмечена');
  });
}
