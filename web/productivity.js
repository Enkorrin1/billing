// Мои решения, журнал времени и регулярные заявки. Загружается по требованию из main.js.
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const WEEKDAY_NAMES = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье'];
const KIND_ICONS = { assign: 'user', pm_estimate: 'wallet', pm_hours: 'clock', revision: 'alert', reply: 'reply', overdue: 'alert', task_review: 'check', mention: 'chat', timesheet: 'clock' };

function age(since) {
  const ms = Date.now() - new Date(since).getTime();
  if (!since || Number.isNaN(ms)) return '';
  const hours = Math.floor(ms / 3600000);
  if (hours < 1) return 'только что';
  if (hours < 24) return `${hours} ч`;
  return `${Math.floor(hours / 24)} д`;
}

function isoDay(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function shiftWeek(iso, weeks) { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + weeks * 7); return isoDay(d); }

export async function renderDecisions(ctx) {
  const { state, api, shell, esc, icon, openTicket, setView, showError } = ctx;
  try { state.decisions = await api('/decisions'); } catch (error) { showError(error); }
  if (state.view !== 'decisions') return;
  const items = state.decisions || [];
  const rows = items.map((d, i) => `<button type="button" class="waiting-row decision-row tone-${esc(d.tone)}" data-decision="${i}">
      <span class="waiting-ico ${d.tone === 'late' ? 'late' : ''}">${icon(KIND_ICONS[d.kind] || 'alert', 17)}</span>
      <span class="waiting-text"><strong>${esc(d.title)}</strong><small>${esc(d.detail)}</small></span>
      <span class="waiting-age ${d.tone === 'late' ? 'late' : ''}">${esc(age(d.since))}</span>
      <span class="waiting-go">${icon('arrow', 16)}</span></button>`).join('');
  const body = items.length
    ? `<section class="waiting-panel decisions-panel" aria-label="Требует моего решения"><div class="waiting-head"><strong>${items.length} ${ctx.plural(items.length, ['дело', 'дела', 'дел'])} ждут вас</strong><span class="muted">Сначала просроченное и срочное</span></div>${rows}</section>`
    : `<section class="waiting-panel clear">${icon('check', 18)}<div><strong>Всё решено</strong><span>Новые согласования, ответы клиентам и упоминания появятся здесь.</span></div></section>`;
  shell('Требует моего решения', '', body, { lead: 'Согласования, ответы клиентам, проверки и упоминания — в одном списке' });
  document.querySelectorAll('[data-decision]').forEach(button => button.onclick = () => {
    const d = items[Number(button.dataset.decision)];
    if (d.ticket_id) openTicket(d.ticket_id);
    else if (d.task_id) location.hash = `#task/${d.task_id}`;
    else if (d.view) setView(d.view);
  });
}

export async function renderTimesheet(ctx) {
  const { state, api, shell, esc, icon, hours, toast, showError, openTicket } = ctx;
  let sheet;
  try { sheet = await api(`/timesheet${state.timesheetWeek ? `?week_start=${state.timesheetWeek}` : ''}`); }
  catch (error) { showError(error); return; }
  if (state.view !== 'timesheet') return;
  state.timesheetWeek = sheet.week_start;
  const head = sheet.days.map((d, i) => `<th scope="col" class="${d === sheet.today ? 'today' : ''}">${WEEKDAYS[i]}<small>${new Date(`${d}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</small></th>`).join('');
  const row = r => `<tr data-row="${r.id}"><th scope="row"><button type="button" class="link-button" data-open-ticket="${r.id}">№${r.id} ${esc(r.title)}</button><small>${esc(r.customer_name)} · осталось ${hours(r.remaining_minutes)}</small>
      ${r.can_log ? `<input class="field compact" data-note="${r.id}" maxlength="2000" placeholder="Что сделано" aria-label="Описание работы по заявке №${r.id}">` : '<small class="muted">Заявка не в работе</small>'}</th>
      ${sheet.days.map(d => `<td>${r.days[d] ? `<span class="ts-logged">${hours(r.days[d])}</span>` : ''}${r.can_log && d <= sheet.today ? `<input class="field compact ts-cell" inputmode="decimal" data-cell="${r.id}|${d}" placeholder="+ ч" aria-label="Часы ${d} по заявке №${r.id}">` : ''}</td>`).join('')}
      <td class="ts-total">${hours(Object.values(r.days).reduce((a, b) => a + b, 0))}</td></tr>`;
  const table = sheet.rows.length
    ? `<div class="table-scroll"><table class="timesheet"><thead><tr><th scope="col">Заявка</th>${head}<th scope="col">Итого</th></tr></thead><tbody>${sheet.rows.map(row).join('')}</tbody>
       <tfoot><tr><th scope="row">За неделю</th>${sheet.days.map(d => `<td>${sheet.totals[d] ? hours(sheet.totals[d]) : '—'}</td>`).join('')}<td class="ts-total">${hours(sheet.total_minutes)}</td></tr></tfoot></table></div>
       <div class="row ts-actions"><button type="button" class="button primary" id="ts-save">Сохранить время</button><span class="muted">Время в часах: 0,5 = 30 минут. Описание работы общее для строки.</span></div>`
    : '<div class="empty"><strong>Заявок в работе нет</strong>Когда вам назначат согласованную заявку, она появится здесь.</div>';
  const nav = `<div class="row ts-week"><button type="button" class="button small" id="ts-prev">← Неделя</button><strong>${new Date(`${sheet.days[0]}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} — ${new Date(`${sheet.days[6]}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</strong><button type="button" class="button small" id="ts-next" ${sheet.days[6] >= sheet.today ? 'disabled' : ''}>Неделя →</button></div>`;
  shell('Журнал времени', '', `${nav}<section class="panel content">${table}</section>`, { lead: 'Внесите фактическое время по всем заявкам недели одной формой' });
  document.querySelector('#ts-prev').onclick = () => { state.timesheetWeek = shiftWeek(sheet.week_start, -1); renderTimesheet(ctx); };
  document.querySelector('#ts-next').onclick = () => { state.timesheetWeek = shiftWeek(sheet.week_start, 1); renderTimesheet(ctx); };
  document.querySelectorAll('[data-open-ticket]').forEach(b => b.onclick = () => openTicket(Number(b.dataset.openTicket)));
  document.querySelector('#ts-save')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    const entries = [];
    for (const input of document.querySelectorAll('[data-cell]')) {
      const value = input.value.trim().replace(',', '.');
      if (!value) continue;
      const minutes = Math.round(Number(value) * 60);
      if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) { input.focus(); return toast('Укажите часы числом, например 1,5', 'error'); }
      const [ticket, day] = input.dataset.cell.split('|');
      const note = document.querySelector(`[data-note="${ticket}"]`).value.trim();
      if (note.length < 3) { document.querySelector(`[data-note="${ticket}"]`).focus(); return toast(`Опишите работу по заявке №${ticket}`, 'error'); }
      entries.push({ ticket_id: Number(ticket), work_date: day, minutes, note, request_id: `ts-${ticket}-${day}-${crypto.randomUUID()}` });
    }
    if (!entries.length) return toast('Введите часы хотя бы в одну ячейку', 'error');
    button.disabled = true;
    try { const result = await api('/timesheet', { method: 'POST', body: JSON.stringify({ entries }) }); toast(`Сохранено записей: ${result.saved}`); renderTimesheet(ctx); }
    catch (error) { showError(error); button.disabled = false; }
  });
}

function schedule(plan) {
  return plan.frequency === 'weekly' ? `каждую ${WEEKDAY_NAMES[plan.day - 1]}` : `каждый месяц, ${plan.day} числа`;
}

export async function renderRecurring(ctx) {
  const { state, api, shell, esc, toast, showError, openTicket, date } = ctx;
  let plans = [];
  try { plans = await api('/recurring-tickets'); } catch (error) { showError(error); }
  if (state.view !== 'recurring') return;
  const staff = state.user.role !== 'customer';
  const manager = state.user.role === 'admin' || state.user.is_manager;
  const list = plans.length ? plans.map(p => `<section class="content recurring-item ${p.active ? '' : 'paused'}"><div><strong>${esc(p.title)}</strong>
      <p class="muted">${esc(schedule(p))}${staff ? ` · ${esc(p.customer_name)}` : ''} · ${p.active ? `следующая ${esc(date(p.next_run_at))}` : 'на паузе'}</p>
      ${p.last_error ? `<p class="notice">Не удалось создать: ${esc(p.last_error)}</p>` : ''}
      ${p.last_ticket_id ? `<button type="button" class="link-button" data-open-ticket="${p.last_ticket_id}">Последняя заявка №${p.last_ticket_id}</button>` : ''}</div>
      <div class="row"><button type="button" class="button small" data-toggle-plan="${p.id}" data-active="${p.active ? 0 : 1}">${p.active ? 'Приостановить' : 'Возобновить'}</button><button type="button" class="button small" data-delete-plan="${p.id}">Удалить</button></div></section>`).join('')
    : '<div class="empty"><strong>Расписаний пока нет</strong>Регулярная работа — обслуживание, отчёты, проверки — будет создаваться заявкой автоматически.</div>';
  const customerField = staff ? `<label>Заказчик<select class="field" name="customer_id" required><option value="">Выберите заказчика</option>${(state.customers || []).map(c => `<option value="${c.id}">${esc(c.name)}${c.company_name ? ` · ${esc(c.company_name)}` : ''}</option>`).join('')}</select></label>` : '';
  const form = !staff || manager ? `<section class="panel content"><h2>Новое расписание</h2><form class="form" id="recurring-form">${customerField}
      <label>Тема заявки<input class="field" name="title" required minlength="3" maxlength="140" placeholder="Ежемесячное обслуживание сайта"></label>
      <label>Что нужно сделать<textarea class="field" name="description" required minlength="5" maxlength="10000" placeholder="Обновить модули, проверить бэкапы, прислать отчёт"></textarea></label>
      <div class="row"><label>Как часто<select class="field" name="frequency"><option value="monthly">Каждый месяц</option><option value="weekly">Каждую неделю</option></select></label>
      <label>День<select class="field" name="day"></select></label></div>
      <p class="muted">Заявка создаётся в 09:00. Стоимость каждой заявки согласуется как обычно.</p>
      <button class="button primary">Создать расписание</button></form></section>`
    : '<p class="muted">Регулярные заявки для клиентов настраивает менеджер.</p>';
  shell('Регулярные заявки', '', `<div class="detail-grid"><div><section class="panel content">${list}</section></div><div>${form}</div></div>`, { lead: 'Повторяющаяся работа создаётся заявкой сама — не нужно заводить её вручную' });
  const daySelect = document.querySelector('#recurring-form [name="day"]');
  const paintDays = () => {
    const weekly = document.querySelector('#recurring-form [name="frequency"]').value === 'weekly';
    daySelect.innerHTML = weekly ? WEEKDAYS.map((d, i) => `<option value="${i + 1}">${d}</option>`).join('') : Array.from({ length: 28 }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join('');
  };
  if (daySelect) { paintDays(); document.querySelector('#recurring-form [name="frequency"]').onchange = paintDays; }
  document.querySelector('#recurring-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    data.day = Number(data.day);
    data.customer_id = data.customer_id ? Number(data.customer_id) : null;
    try { await api('/recurring-tickets', { method: 'POST', body: JSON.stringify(data) }); toast('Расписание создано'); renderRecurring(ctx); }
    catch (error) { showError(error); }
  });
  document.querySelectorAll('[data-open-ticket]').forEach(b => b.onclick = () => openTicket(Number(b.dataset.openTicket)));
  document.querySelectorAll('[data-toggle-plan]').forEach(b => b.onclick = async () => {
    try { await api(`/recurring-tickets/${b.dataset.togglePlan}`, { method: 'PATCH', body: JSON.stringify({ active: b.dataset.active === '1' }) }); renderRecurring(ctx); }
    catch (error) { showError(error); }
  });
  document.querySelectorAll('[data-delete-plan]').forEach(b => b.onclick = async () => {
    if (b.dataset.confirm !== '1') { b.dataset.confirm = '1'; b.textContent = 'Точно удалить?'; return; }
    try { await api(`/recurring-tickets/${b.dataset.deletePlan}`, { method: 'DELETE' }); toast('Расписание удалено'); renderRecurring(ctx); }
    catch (error) { showError(error); }
  });
}
