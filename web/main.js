const app = document.querySelector('#app');
const state = { user: null, profile: null, tickets: [], chats: [], queue: [], staff: [], customers: [], organizations: [], notifications: [], current: null, currentChat: null, view: 'tickets', filter: 'all', priorityFilter: 'all', search: '', authMode: 'login', error: '', internalNotes: [], cannedResponses: [], analytics: null, kbCategories: [], kbArticles: [], kbActiveCategory: null, kbSearch: '', kbReadingArticle: null, kbEditingArticle: null, gitLinks: [], webhooks: [], billing: null, billingTab: 'docs', billingFilter: 'all', billingModal: null, owner: 'all', queueScope: 'all', queueSource: 'all', queueGroup: null, detailTab: 'messages', chatSearch: '', inboxSection: 'general', ticketChatSearch: '', waiting: [], replyTo: null, specialists: [], selectedTickets: new Set() };

async function claimTicket(id) {
  try {
    await api(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify({ assignee_id: state.user.id, status: 'working' }) });
    toast(`Заявка №${id} взята вами в работу`);
    await reload();
    if (state.view === 'detail' && state.current?.ticket?.id === id) openTicket(id);
    else if (state.view === 'tickets') renderTickets();
  } catch (err) {
    toast(err.message, 'error');
  }
}
const statusNames = { new: 'Новая', working: 'В работе', waiting: 'Ожидает заказчика', done: 'На проверке', closed: 'Закрыта' };
const priorityNames = { low: 'Низкий', normal: 'Обычный', high: 'Высокий', urgent: 'Критический' };
const teamRoleNames = {programmer:'Программист',integrator:'Интегратор',devops:'Девопс',analyst:'Аналитик',designer:'Дизайнер',qa:'Тестировщик',sales:'Продажи',account:'Ведение клиентов',call_host:'Проведение созвонов',support:'Поддержка',project_manager:'Управление проектами',team_lead:'Руководство командой',finance:'Финансовый учёт'};
const staffLabel = person => `${person.name}${(person.functions||[person.team_role]).filter(Boolean).length?' · '+(person.functions||[person.team_role]).filter(Boolean).map(c=>state.teamWorkspace?.functions.find(f=>f.code===c)?.name||teamRoleNames[c]||c).join(', '):''}`;
const teamRoleOptions = selected => `<option value="">Не назначена</option>${Object.entries(teamRoleNames).map(([value,label])=>`<option value="${value}" ${selected===value?'selected':''}>${label}</option>`).join('')}`;
const estimateNames = {
  pending_pm: 'Ожидает согласования PM',
  pending: 'Ожидает решения заказчика',
  approved: 'Одобрена',
  rejected: 'Отклонена',
  rejected_by_pm: 'Отклонена PM',
  pm_revision_requested: 'Возвращена PM на доработку',
  revision_requested: 'Запрошена корректировка'
};
const serviceNames = {development:'Доработка',new_development:'Разработка',integration:'Интеграция',support:'Поддержка',maintenance:'Сопровождение',consultation:'Консультация',other:'Другое'};
const serviceLabel = value => value?.startsWith('custom:') ? value.slice(7) : serviceNames[value] || 'Другое';
const ticketServiceType = form => form.elements.service_type.value === 'other' ? `custom:${form.elements.service_topic.value.trim()}` : form.elements.service_type.value;
const serviceHints = {development:'Что нужно изменить? Как должен выглядеть готовый результат? Где это работает сейчас?',new_development:'Что нужно разработать? Какие функции нужны и каким должен быть готовый результат?',integration:'Какие системы нужно связать? Какие данные передавать и в каком направлении? Есть ли документация API?',support:'Что не работает? Когда возникла проблема? Какие действия её повторяют?',maintenance:'Что нужно сопровождать? Какие регулярные работы и уровень обслуживания нужны?',consultation:'По какому вопросу нужна помощь? Какое решение вы хотите принять?',other:'Что нужно сделать? Какой результат вы ожидаете?'};
const serviceKindNames = {chat:'Переписка',call:'Созвон',meeting:'Встреча',other:'Прочее'};
const hours = minutes =>`${(minutes/60).toLocaleString('ru-RU',{maximumFractionDigits:2})} ч`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const avatar = (person, extra='') => `<span class="person-avatar ${extra}">${person?.avatar_url?`<img src="${esc(person.avatar_url)}" alt="">`:esc((person?.name||'?').trim().split(/\s+/).slice(0,2).map(word=>word[0]).join('').toUpperCase())}</span>`;
const date = value => new Date(value).toLocaleString('ru-RU', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
const statusChipNames = { new: 'Новые', working: 'В работе', waiting: 'Ожидают', done: 'На проверке', closed: 'Закрыты' };
const ICONS = {
  queue: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  ticket: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"/><path d="M20 17v5H6.5A2.5 2.5 0 0 1 4 19.5"/>',
  briefcase: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  wallet: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
  chart: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  more: '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  print: '<path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a7 7 0 0 1 16 0v1"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7M12 17h.01"/>',
  reply: '<path d="M9 17 4 12l5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
  checks: '<path d="M17 7 6.5 17.5 2 13"/><path d="m22 8-9.5 9.5-1.5-1.5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
};
const icon = (name, size = 18) => `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
const initials = name => esc((name || '?').trim().split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase());
const plural = (n, [one, few, many]) => { const a = Math.abs(n) % 100, b = a % 10; return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many; };
const canManageFinance = () => isDispatcher() || Boolean(state.teamWorkspace?.my_permissions.includes('billing_manage'));
const billingOn = () => Boolean(state.settings?.billing_enabled) && (state.user?.role==='customer' || isDispatcher() || Boolean(state.teamWorkspace?.my_permissions.some(p=>['billing_read','billing_manage'].includes(p))));
const isDispatcher = () => state.user.role === 'admin' || Boolean(state.user.is_manager);
const personById = id => state.staff.find(person => person.id === id);
const avatarOf = (id, name) => id ? avatar(personById(id) || { name }, 'small') : '<span class="person-avatar small vacant" title="Не назначен" aria-label="Не назначен">+</span>';
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let lastViewKey = '';
function toast(text, tone = 'success') {
  let host = document.querySelector('#toasts');
  if (!host) { host = document.createElement('div'); host.id = 'toasts'; host.className = 'toasts'; host.setAttribute('role', 'status'); host.setAttribute('aria-live', 'polite'); document.body.append(host); }
  const el = document.createElement('div');
  el.className = `toast ${tone}`;
  el.innerHTML = `${icon(tone === 'error' ? 'alert' : tone === 'info' ? 'bell' : 'check', 16)}<span>${esc(text)}</span><button type="button" class="toast-close" aria-label="Закрыть уведомление">${icon('close', 16)}</button>`;
  host.append(el);
  let timer;
  const dismiss = () => {
    clearTimeout(timer);
    el.classList.add('leaving');
    setTimeout(() => el.remove(), reduceMotion() ? 0 : 180);
  };
  const schedule = () => {
    clearTimeout(timer);
    if (!el.matches(':hover, :focus-within') && tone !== 'error') timer = setTimeout(dismiss, 5000);
  };
  el.querySelector('.toast-close').onclick = dismiss;
  el.addEventListener('pointerenter', () => clearTimeout(timer));
  el.addEventListener('pointerleave', schedule);
  el.addEventListener('focusin', () => clearTimeout(timer));
  el.addEventListener('focusout', () => queueMicrotask(schedule));
  schedule();
}
function countUp(el) {
  const text = el.textContent;
  const m = text.match(/^(\D*?)(\d[\d\s ]*(?:[.,]\d+)?)(.*)$/s);
  if (!m) return;
  const raw = m[2].replace(/[\s ]/g, '').replace(',', '.');
  const target = Number(raw);
  if (!target || !isFinite(target)) return;
  const decimals = (raw.split('.')[1] || '').length;
  const started = performance.now();
  const frame = now => {
    const p = Math.min(1, (now - started) / 700);
    const value = target * (1 - Math.pow(1 - p, 3));
    el.textContent = p < 1 ? m[1] + value.toLocaleString('ru-RU', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + m[3] : text;
    if (p < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}
function animateEntrance() {
  const main = document.querySelector('#main.is-entering');
  if (!main) return;
  main.querySelectorAll('.top, .panel, .stat, .billing-kpi, .focus-panel, .activity-panel, .ticket-progress, .next-step, .profile-note, .form-help, .kb-card, .webhook-card, .csat-box').forEach((el, i) => el.style.setProperty('--i', Math.min(i, 12)));
  main.querySelectorAll('.qrow, .trow, .chat-item, .ticket-row').forEach((el, i) => el.style.setProperty('--i', Math.min(i, 14) + 2));
  if (!reduceMotion()) main.querySelectorAll('.stat strong, .billing-kpi-value, .overview-card strong.big').forEach(countUp);
  setTimeout(() => main.classList.remove('is-entering'), 1500);
}
function popLastMessage(box) {
  if (!state.justSent || !box) return;
  state.justSent = false;
  const mine = box.querySelectorAll('.message.mine');
  mine[mine.length - 1]?.classList.add('pop');
}
function openPalette() {
  if (!state.user || document.querySelector('.palette-backdrop')) return;
  const staff = state.user.role !== 'customer';
  const returnFocus = document.activeElement;
  const pages = [
    ...[...document.querySelectorAll('aside [data-nav]')].map(b => ({ group: 'Разделы', svg: b.querySelector('svg')?.outerHTML || '', label: b.querySelector('span')?.textContent || '', run: () => b.click() })),
    { group: 'Разделы', svg: icon('bell'), label: 'Уведомления', run: () => setView('notifications') },
    { group: 'Разделы', svg: icon('user'), label: 'Мой профиль', run: () => setView('profile') },
    { group: 'Действия', svg: icon('plus'), label: staff?'Создать задачу':'Создать заявку', run: () => staff?TasksUI.quickCreate():setView('new') },
    ...(staff ? [] : [{ group: 'Действия', svg: icon('help'), label: 'Пройти обучение по кабинету', run: () => startTour() }]),
    { group: 'Действия', svg: icon(effectiveTheme() === 'dark' ? 'sun' : 'moon'), label: effectiveTheme() === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему', run: () => toggleTheme() },
  ].map(item => ({ ...item, hay: item.label.toLocaleLowerCase('ru-RU') }));
  const tickets = state.tickets.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(t => ({ group: 'Заявки', svg: icon('ticket'), label: `№${t.id} · ${t.title}`, hint: statusNames[t.status], run: () => openTicket(t.id), hay: [t.id, t.title, t.customer_name, t.customer_company].join(' ').toLocaleLowerCase('ru-RU') }));
  const tasks = staff ? (state.teamWorkspace?.tasks||[]).map(t=>({group:'Задачи',svg:icon('check'),label:`№${t.id} · ${t.title}`,hint:({new:'Новая',working:'В работе',review:'На проверке',done:'Выполнена',cancelled:'В архиве'})[t.status],run:()=>TasksUI.open(t.id),hay:[t.id,t.title,t.description].join(' ').toLocaleLowerCase('ru-RU')})):[];
  const chats = staff ? state.chats.map(c => ({ group: 'Чаты', svg: icon('chat'), label: c.customer_name, hint: c.last_message || '', run: () => openChat(c.id), hay: [c.customer_name, c.last_message].join(' ').toLocaleLowerCase('ru-RU') })) : [];
  document.body.insertAdjacentHTML('beforeend', `<div class="palette-backdrop"><div class="palette" role="dialog" aria-modal="true" aria-label="Быстрый переход"><div class="palette-search">${icon('search', 18)}<input id="palette-input" role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list" autocomplete="off" placeholder="Найти задачу, заявку или раздел…"><kbd>Esc</kbd></div><div class="palette-list" id="palette-list" role="listbox" aria-label="Результаты"></div><div class="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> выбрать</span><span><kbd>Enter</kbd> открыть</span><span><kbd>Esc</kbd> закрыть</span></div></div></div>`);
  const backdrop = document.querySelector('.palette-backdrop');
  const input = backdrop.querySelector('#palette-input');
  const list = backdrop.querySelector('#palette-list');
  let results = [];
  let active = 0;
  const close = () => { backdrop.classList.add('closing'); setTimeout(() => backdrop.remove(), 160); returnFocus?.focus?.(); };
  const runItem = item => { close(); item?.run(); };
  const paint = () => {
    let group = '';
    list.innerHTML = results.map((item, i) => { const head = item.group !== group ? `<div class="palette-group">${item.group}</div>` : ''; group = item.group; return `${head}<div class="palette-item ${i === active ? 'active' : ''}" role="option" id="pal-opt-${i}" aria-selected="${i === active}" data-index="${i}">${item.svg}<span class="palette-label">${esc(item.label)}</span>${item.hint ? `<span class="palette-hint">${esc(item.hint)}</span>` : ''}</div>`; }).join('') || '<div class="palette-empty">Ничего не найдено</div>';
    input.setAttribute('aria-activedescendant', results.length ? `pal-opt-${active}` : '');
    list.querySelector('.palette-item.active')?.scrollIntoView({ block: 'nearest' });
  };
  const search = () => {
    const q = input.value.trim().toLocaleLowerCase('ru-RU');
    const match = item => !q || item.hay.includes(q);
    results = [...pages.filter(match).slice(0, q ? 6 : 8), ...tickets.filter(match).slice(0, q ? 6 : 5), ...chats.filter(match).slice(0, q ? 4 : 0)];
    if (q) results.push({ group: 'Поиск', svg: icon('search'), label: `Искать «${input.value.trim()}» во всех заявках`, run: () => { state.search = input.value.trim(); state.filter = 'all'; state.owner = 'all'; setView('tickets'); } });
    active = 0;
    paint();
  };
  input.addEventListener('input', search);
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (!results.length) return; active = (active + (e.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length; paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); runItem(results[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'Tab') e.preventDefault();
  });
  list.addEventListener('mousemove', e => { const el = e.target.closest('.palette-item'); if (el && Number(el.dataset.index) !== active) { active = Number(el.dataset.index); paint(); } });
  list.addEventListener('click', e => { const el = e.target.closest('.palette-item'); if (el) runItem(results[Number(el.dataset.index)]); });
  backdrop.addEventListener('mousedown', e => { if (e.target === backdrop) close(); });
  search();
  input.focus();
}
const tour = { steps: [], index: 0, layer: null, onKey: null, onMove: null };
const tourKey = () => `linia-tour-done-${state.user?.id}`;
function tourDone() { try { return localStorage.getItem(tourKey()) === '1'; } catch { return true; } }
function markTourDone() { try { localStorage.setItem(tourKey(), '1'); } catch {} }
function maybeStartTour() {
  if (state.user?.role !== 'customer' || tourDone() || document.querySelector('#tour-invitation')) return;
  document.querySelector('#main')?.insertAdjacentHTML('afterbegin', '<section class="notice" id="tour-invitation"><p>Впервые в кабинете? Покажем, как создать заявку и согласовать работу.</p><div class="row"><button class="button" id="tour-start">Пройти обучение</button><button class="button" id="tour-later">Позже</button></div></section>');
  document.querySelector('#tour-start')?.addEventListener('click', () => { document.querySelector('#tour-invitation').remove(); startTour(); });
  document.querySelector('#tour-later')?.addEventListener('click', () => { markTourDone(); document.querySelector('#tour-invitation').remove(); });
}
function visibleTarget(selectors) {
  for (const selector of [].concat(selectors || [])) {
    for (const el of document.querySelectorAll(selector)) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.right > 0 && r.left < innerWidth && getComputedStyle(el).visibility !== 'hidden') return el;
    }
  }
  return null;
}
function customerTourSteps() {
  const pick = () => state.tickets.find(t => t.estimate_state === 'pending') || state.tickets.find(t => !['done', 'closed'].includes(t.status)) || state.tickets[0];
  const toTickets = async () => { if (state.view !== 'tickets') { history.replaceState(null, '', location.pathname); state.filter = 'all'; state.owner = 'all'; setView('tickets'); } };
  const toDetail = async () => { const t = pick(); if (t && !(state.view === 'detail' && state.current?.ticket?.id === t.id)) await openTicket(t.id); };
  const noTickets = () => !state.tickets.length;
  return [
    { hero: true, title: 'Добро пожаловать в кабинет', text: 'За пару минут покажем, как создать заявку, согласовать оценку и следить за работой. Пройти обучение снова можно в любой момент — кнопкой «?» в верхней панели.', next: 'Начать', before: toTickets },
    { target: ['aside .nav', '.tabbar'], title: 'Разделы кабинета', text: 'Здесь все разделы: ваши заявки, общий чат с командой, компания, база знаний и счета.', before: toTickets },
    { target: '#top-new-ticket', title: 'Новая заявка', text: 'Нажмите, чтобы описать задачу. Выберите тип работы, расскажите, какой результат нужен, и при необходимости приложите файлы.', before: toTickets },
    { target: '.waiting-panel', title: 'Ждём от вас', text: 'Здесь собрано всё, что ждёт вашего решения: оценки, дополнительные часы, приёмка работы и вопросы команды. Пока список не пуст, работа по этим заявкам стоит.', before: toTickets, skip: () => !(state.waiting?.length || state.tickets.some(t => t.status !== 'closed')) },
    { target: '.overview-card', title: 'Сводка по заявкам', text: 'Сколько задач на каждом этапе, сколько часов уже согласовано и сколько оценок ждут вашего решения.', before: toTickets },
    { target: ['#ticket-list .trow', '#ticket-list'], title: 'Список заявок', text: 'Фильтруйте по статусу и ищите по номеру или теме. Нажмите на заявку, чтобы открыть её. Сейчас откроем одну для примера.', before: toTickets },
    { target: '.ticket-progress', title: 'Этапы заявки', text: 'Каждая заявка проходит пять шагов: создание, оценка, согласование, работа и приёмка. Когда работа готова, вы проверяете результат и принимаете его или возвращаете на доработку.', before: toDetail, skip: noTickets },
    { target: '.estimate-panel', title: 'Согласуйте оценку', text: 'Команда оценивает задачу в часах. Вы можете одобрить оценку, отклонить её или предложить свой вариант — без вашего решения работа не начнётся.', before: toDetail, skip: noTickets },
    { target: '.conversation', title: 'Переписка по заявке', text: 'Задавайте вопросы и уточняйте детали прямо в заявке. Чтобы ответить на конкретное сообщение, нажмите «Ответить» под ним. Отметка «Прочитано командой» показывает, что сообщение увидели.', before: toDetail, skip: noTickets },
    { target: '.detail-grid > div:last-child > .operations-panel', title: 'Сроки работы', text: 'Сроки ответа, оценки и сдачи. Если срок подходит, полоска становится жёлтой, если прошёл — красной.', before: toDetail, skip: noTickets },
    { target: ['aside [data-nav="chats"]', '.tabbar [data-nav="chats"]'], title: 'Общий чат', text: 'Для вопросов без привязки к заявке. Если из разговора вырастет задача, команда оформит её как заявку.', before: toTickets },
    { skip: () => !billingOn(), target: '.billing-kpi-grid', title: 'Часы и счета', text: 'Баланс депозита, ставка и часы в работе. Здесь же можно купить пакет часов и открыть счета и акты.', before: async () => { if (state.view !== 'billing') await openBilling(); } },
    { target: ['aside [data-nav="messengers"]'], title: 'Telegram и MAX', text: 'Подключите бота в разделе «Мессенджеры», чтобы создавать заявки и отвечать прямо из мессенджера.' },
    { target: '#open-palette', title: 'Быстрый поиск', text: 'Нажмите Ctrl + K, чтобы найти заявку или раздел за секунду.' },
    { target: '#help-tour', title: 'Всё готово!', text: 'Если что-то забудется, нажмите «?» — обучение запустится снова.', next: 'Завершить' },
  ];
}
function startTour() {
  if (!state.user || tour.layer) return;
  document.querySelector('.palette-backdrop')?.remove();
  document.body.classList.remove('nav-open');
  tour.steps = customerTourSteps().filter(step => !step.skip?.());
  tour.index = 0;
  document.body.insertAdjacentHTML('beforeend', `<div class="tour-layer"><div class="tour-spot" aria-hidden="true"></div><div class="tour-pop" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-text" tabindex="-1"><button type="button" class="tour-close" aria-label="Закрыть обучение">×</button><div class="tour-hero" aria-hidden="true"><span class="brand-mark">Л</span></div><div class="tour-count" id="tour-count"></div><h2 id="tour-title"></h2><p id="tour-text"></p><div class="tour-foot"><div class="tour-dots" aria-hidden="true">${tour.steps.map(() => '<i></i>').join('')}</div><button type="button" class="button small tour-prev">Назад</button><button type="button" class="button small primary tour-next">Далее</button></div></div></div>`);
  tour.layer = document.querySelector('.tour-layer');
  tour.layer.querySelector('.tour-next').onclick = () => tour.index === tour.steps.length - 1 ? endTour(true) : showTourStep(tour.index + 1);
  tour.layer.querySelector('.tour-prev').onclick = () => showTourStep(tour.index - 1);
  tour.layer.querySelector('.tour-close').onclick = () => endTour(false);
  tour.onKey = e => {
    if (e.key === 'Escape') { e.preventDefault(); endTour(false); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); tour.layer.querySelector('.tour-next').click(); }
    else if (e.key === 'ArrowLeft' && tour.index > 0) { e.preventDefault(); showTourStep(tour.index - 1); }
    else if (e.key === 'Tab') {
      const items = [...tour.layer.querySelectorAll('.tour-pop button:not([hidden])')];
      const i = items.indexOf(document.activeElement);
      e.preventDefault();
      items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length]?.focus();
    }
  };
  tour.onMove = () => { cancelAnimationFrame(tour.raf); tour.raf = requestAnimationFrame(positionTour); };
  document.addEventListener('keydown', tour.onKey, true);
  addEventListener('resize', tour.onMove);
  addEventListener('scroll', tour.onMove, true);
  showTourStep(0);
}
async function showTourStep(index) {
  const step = tour.steps[index];
  if (!step || !tour.layer) return;
  tour.index = index;
  const pop = tour.layer.querySelector('.tour-pop');
  pop.classList.add('switching');
  try { await step.before?.(); } catch (error) {}
  if (!tour.layer) return;
  const el = step.target ? visibleTarget(step.target) : null;
  if (el) { const r = el.getBoundingClientRect(); const header = document.querySelector('.topbar')?.offsetHeight || 0; const offset = r.height > (innerHeight - header) * .6 ? header + 16 : header + (innerHeight - header - r.height) / 2; if (getComputedStyle(el).position !== 'fixed' && !el.closest('aside, .tabbar, .topbar')) window.scrollTo({ top: Math.max(0, r.top + scrollY - offset), behavior: reduceMotion() ? 'auto' : 'smooth' }); }
  tour.layer.querySelector('#tour-count').textContent = `Шаг ${index + 1} из ${tour.steps.length}`;
  tour.layer.querySelector('#tour-title').textContent = step.title;
  tour.layer.querySelector('#tour-text').textContent = step.text;
  tour.layer.querySelector('.tour-prev').hidden = index === 0;
  tour.layer.querySelector('.tour-next').textContent = step.next || 'Далее';
  tour.layer.querySelectorAll('.tour-dots i').forEach((dot, i) => dot.className = i === index ? 'active' : i < index ? 'passed' : '');
  tour.layer.classList.toggle('is-hero', Boolean(step.hero));
  positionTour();
  setTimeout(positionTour, reduceMotion() ? 0 : 480);
  setTimeout(() => { pop.classList.remove('switching'); pop.querySelector('.tour-next').focus({ preventScroll: true }); }, reduceMotion() ? 0 : 200);
}
function positionTour() {
  if (!tour.layer) return;
  const step = tour.steps[tour.index];
  const spot = tour.layer.querySelector('.tour-spot');
  const pop = tour.layer.querySelector('.tour-pop');
  const el = step?.target ? visibleTarget(step.target) : null;
  const gap = 14, margin = 16;
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  if (!el) {
    tour.layer.classList.add('no-target');
    Object.assign(spot.style, { top: `${innerHeight / 2}px`, left: `${innerWidth / 2}px`, width: '0px', height: '0px' });
    Object.assign(pop.style, { top: `${Math.max(margin, (innerHeight - ph) / 2)}px`, left: `${Math.max(margin, (innerWidth - pw) / 2)}px` });
    return;
  }
  tour.layer.classList.remove('no-target');
  const r = el.getBoundingClientRect();
  const pad = 8;
  const box = { top: Math.max(6, r.top - pad), left: Math.max(6, r.left - pad) };
  box.bottom = Math.min(innerHeight - 6, r.bottom + pad);
  box.right = Math.min(innerWidth - 6, r.right + pad);
  Object.assign(spot.style, { top: `${box.top}px`, left: `${box.left}px`, width: `${box.right - box.left}px`, height: `${box.bottom - box.top}px` });
  const clampX = x => Math.min(Math.max(margin, x), innerWidth - pw - margin);
  const clampY = y => Math.min(Math.max(margin, y), innerHeight - ph - margin);
  let top, left;
  if (box.bottom + gap + ph <= innerHeight - margin) { top = box.bottom + gap; left = clampX(box.left); }
  else if (box.top - gap - ph >= margin) { top = box.top - gap - ph; left = clampX(box.left); }
  else if (box.right + gap + pw <= innerWidth - margin) { left = box.right + gap; top = clampY(box.top); }
  else if (box.left - gap - pw >= margin) { left = box.left - gap - pw; top = clampY(box.top); }
  else { top = innerHeight - ph - margin; left = clampX((innerWidth - pw) / 2); }
  Object.assign(pop.style, { top: `${top}px`, left: `${left}px` });
}
function endTour(completed) {
  if (!tour.layer) return;
  const layer = tour.layer;
  tour.layer = null;
  document.removeEventListener('keydown', tour.onKey, true);
  removeEventListener('resize', tour.onMove);
  removeEventListener('scroll', tour.onMove, true);
  layer.classList.add('closing');
  setTimeout(() => layer.remove(), 220);
  markTourDone();
  if (state.view !== 'tickets') { history.replaceState(null, '', location.pathname); setView('tickets'); }
  toast(completed ? 'Обучение пройдено. Запустить снова — кнопка «?» вверху' : 'Обучение можно пройти позже — кнопка «?» вверху', 'info');
}
const SCROLL_AREAS = '.messages, .inbox-items, .internal-notes-list';
function captureUi() {
  const active = document.activeElement;
  return {
    scrollY: window.scrollY,
    scrolls: [...document.querySelectorAll(SCROLL_AREAS)].map(el => el.scrollHeight - el.scrollTop - el.clientHeight < 40 ? 'bottom' : el.scrollTop),
    focus: active?.id && active !== document.body ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null,
  };
}
function restoreUi(ui) {
  window.scrollTo(0, ui.scrollY);
  document.querySelectorAll(SCROLL_AREAS).forEach((el, i) => { const value = ui.scrolls[i]; if (value !== undefined) el.scrollTop = value === 'bottom' ? el.scrollHeight : value; });
  const el = ui.focus && document.getElementById(ui.focus.id);
  if (!el) return;
  el.focus({ preventScroll: true });
  if (ui.focus.start != null) try { el.setSelectionRange(ui.focus.start, ui.focus.end); } catch {}
}
const draftKey = name => `linia-draft-${state.user?.id}-${name}`;
function bindDrafts(root = document) {
  root.querySelectorAll('textarea[data-draft]').forEach(el => {
    if (el.dataset.draftBound) return;
    el.dataset.draftBound = '1';
    try { const saved = localStorage.getItem(draftKey(el.dataset.draft)); if (saved && !el.value) el.value = saved; } catch {}
    el.addEventListener('input', () => { try { el.value.trim() ? localStorage.setItem(draftKey(el.dataset.draft), el.value) : localStorage.removeItem(draftKey(el.dataset.draft)); } catch {} });
  });
}
function bindTicketDraft(form){
  const key=draftKey('ticket-form');
  try{const data=JSON.parse(localStorage.getItem(key)||'null');if(data){Object.entries(data).forEach(([name,value])=>{const field=form.elements.namedItem(name);if(field&&field.type!=='file')field.value=value;});form.elements.service_type.dispatchEvent(new Event('change'));form.elements.customer_id?.dispatchEvent(new Event('change'));if(data.effort_hours)form.querySelector('.estimate-inline')?.setAttribute('open','');}}
  catch{}
  const save=()=>{const data={};for(const field of form.elements){if(field.name&&!['file','password'].includes(field.type))data[field.name]=field.value;}try{localStorage.setItem(key,JSON.stringify(data));}catch{}};
  form.addEventListener('input',save);form.addEventListener('change',save);
}
function clearDraft(name) { try { localStorage.removeItem(draftKey(name)); } catch {} }
/* ---------- Тема ---------- */
const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');
const effectiveTheme = () => document.documentElement.dataset.theme || (themeMedia.matches ? 'dark' : 'light');
function syncThemeUi() {
  const dark = effectiveTheme() === 'dark';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0a1314' : '#122527');
  const button = document.querySelector('#theme-toggle');
  if (button) { button.innerHTML = icon(dark ? 'sun' : 'moon'); button.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему'); button.title = button.getAttribute('aria-label'); }
}
function toggleTheme() {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  const root = document.documentElement;
  if (!reduceMotion()) { root.classList.add('theme-switching'); setTimeout(() => root.classList.remove('theme-switching'), 350); }
  root.dataset.theme = next;
  try { localStorage.setItem('linia-theme', next); } catch {}
  syncThemeUi();
  toast(next === 'dark' ? 'Тёмная тема включена' : 'Светлая тема включена');
}

/* ---------- Скелетоны ---------- */
let loadingTimer = null;
function skeletonLines(count = 3) { return `<div class="skeleton-wrap" aria-busy="true"><span class="visually-hidden" role="status">Загрузка…</span>${Array.from({ length: count }, (_, i) => `<span class="skeleton" style="width:${[92, 76, 84, 64][i % 4]}%;height:12px"></span>`).join('')}</div>`; }
function skeleton(kind) {
  const line = (w, h = 12, extra = '') => `<span class="skeleton" style="width:${w};height:${h}px;${extra}"></span>`;
  const stat = () => `<div class="stat skeleton-card">${line('55%')}${line('38%', 26)}${line('72%')}</div>`;
  const rows = n => Array.from({ length: n }, () => `<div class="skeleton-row">${line('36px', 36, 'border-radius:10px')}<div class="skeleton-stack">${line('62%', 13)}${line('40%', 11)}</div>${line('96px', 24, 'border-radius:7px')}</div>`).join('');
  const panel = n => `<section class="panel"><div class="toolbar">${line('30%', 16)}</div>${rows(n)}</section>`;
  const card = () => `<section class="panel content skeleton-stack">${line('40%', 16)}${line('100%')}${line('86%')}${line('64%')}</section>`;
  const stats = n => `<div class="stats ${n === 5 ? 'five' : ''}">${Array.from({ length: n }, stat).join('')}</div>`;
  const inner = {
    dashboard: `${stats(4)}<div class="workspace-grid">${panel(6)}<div class="context-stack">${card()}${card()}</div></div>`,
    analytics: `${stats(5)}<div class="split"><div class="context-stack">${card()}${panel(4)}</div><div class="context-stack">${card()}${card()}</div></div>`,
    billing: `<div class="billing-kpi-grid">${Array.from({ length: 4 }, stat).join('')}</div>${panel(5)}`,
    cards: `<div class="kb-grid">${Array.from({ length: 6 }, card).join('')}</div>`,
    detail: `<section class="ticket-progress">${line('100%', 28, 'border-radius:14px')}</section><div class="detail-grid"><div>${card()}${panel(3)}</div><div>${card()}${card()}</div></div>`,
    list: panel(6),
  }[kind] || panel(6);
  return `<div class="skeleton-wrap" aria-busy="true"><span class="visually-hidden" role="status">Загрузка…</span>${inner}</div>`;
}
function delayedLoading(title, kind) {
  clearTimeout(loadingTimer);
  loadingTimer = setTimeout(() => { if (state.user) shell(title, '', skeleton(kind)); }, 180);
}

/* ---------- Перетаскивание файлов ---------- */
const ALLOWED_FILES = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.zip'];
function attachmentLink(file) {
  const image = /\.(png|jpe?g|webp|gif)$/i.test(file.filename);
  return `<a class="attachment-link${image ? ' attachment-preview' : ''}" href="/api/attachments/${file.id}">${image ? `<img src="/api/attachments/${file.id}" alt="${esc(file.filename)}" loading="lazy">` : icon('paperclip', 14)}<span>${esc(file.filename)}</span></a>`;
}
function checkFiles(files) {
  const ok = [], rejected = [];
  files.forEach(file => { const ext = '.' + (file.name.split('.').pop() || '').toLowerCase(); (file.size > 10 * 1024 * 1024 || !ALLOWED_FILES.includes(ext) ? rejected : ok).push(file); });
  if (rejected.length) toast(`Не подходят по формату или размеру (до 10 МБ): ${rejected.map(f => f.name).join(', ')}`, 'error');
  return ok;
}
function bindDropzone(area, label, onFiles) {
  if (!area) return;
  area.classList.add('dropzone');
  area.insertAdjacentHTML('beforeend', `<div class="drop-overlay" aria-hidden="true"><div>${icon('paperclip', 28)}<strong>${label}</strong><span>PNG, JPG, PDF, документы и архивы до 10 МБ</span></div></div>`);
  let depth = 0;
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
  area.addEventListener('dragenter', e => { if (!hasFiles(e)) return; e.preventDefault(); depth += 1; area.classList.add('dragging'); });
  area.addEventListener('dragover', e => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
  area.addEventListener('dragleave', e => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) area.classList.remove('dragging'); });
  area.addEventListener('drop', e => { if (!hasFiles(e)) return; e.preventDefault(); e.stopPropagation(); depth = 0; area.classList.remove('dragging'); const files = checkFiles([...e.dataTransfer.files]); if (files.length) onFiles(files); });
}
function bindFilePicker(form, textarea, input, list, dropArea = form) {
  if (!form) return;
  let selected = [];
  const sync = () => { const dt = new DataTransfer(); selected.forEach(file => dt.items.add(file)); input.files = dt.files; };
  const paint = () => {
    list.innerHTML = selected.map((file, i) => `<span class="file-chip">${icon('paperclip', 13)}<span>${esc(file.name)}</span><button type="button" data-remove-file="${i}" aria-label="Убрать ${esc(file.name)}">×</button></span>`).join('');
    list.querySelectorAll('.file-chip').forEach((chip, i) => {
      if (!/^image\/(png|jpeg|webp|gif)$/.test(selected[i].type)) return;
      const img = document.createElement('img'); img.alt = selected[i].name; img.width = 64; img.height = 48; img.style.objectFit = 'contain';
      const url = URL.createObjectURL(selected[i]); img.onload = img.onerror = () => URL.revokeObjectURL(url); img.src = url; chip.prepend(img);
    });
    list.querySelectorAll('[data-remove-file]').forEach(button => button.onclick = () => { selected.splice(Number(button.dataset.removeFile), 1); sync(); paint(); });
    if (textarea.name === 'body') textarea.required = !selected.length;
  };
  const add = files => { selected.push(...files); sync(); paint(); };
  input.addEventListener('change', () => add(checkFiles([...input.files])));
  textarea.addEventListener('paste', e => {
    const clipboard = e.clipboardData;
    const raw = [...(clipboard?.files || [])];
    if (!raw.length) for (const item of clipboard?.items || []) { if (item.kind === 'file') { const file = item.getAsFile(); if (file) raw.push(file); } }
    if (!raw.length) return;
    e.preventDefault();
    const files = checkFiles(raw);
    if (files.length) { add(files); toast(`Прикреплено файлов: ${files.length}`); }
  });
  bindDropzone(dropArea, 'Отпустите, чтобы прикрепить файлы', add);
  paint();
}
function bindChatFiles() {
  const form = document.querySelector('#chat-message-form');
  if (form) bindFilePicker(form, form.elements.body, form.elements.files, form.querySelector('#chat-files'), document.querySelector('.inbox-thread'));
}

/* ---------- Push-уведомления ---------- */
const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const base64ToBytes = value => { const raw = atob((value + '='.repeat((4 - value.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(raw, c => c.charCodeAt(0)); };
async function currentPushSubscription() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? reg.pushManager.getSubscription() : null;
}
async function savePushSubscription(subscription) {
  const json = subscription.toJSON();
  await api('/push/subscribe', { method: 'POST', body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }) });
  state.pushEnabled = true;
}
async function enablePush() {
  if (!pushSupported()) throw new Error(isIos() && !isStandalone() ? 'На iPhone сначала добавьте кабинет на экран «Домой» и откройте его оттуда' : 'Этот браузер не поддерживает push-уведомления');
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error('Уведомления не разрешены в браузере');
  const { public_key } = await api('/push/key');
  const key = base64ToBytes(public_key);
  const reg = await navigator.serviceWorker.ready;
  let subscription = await reg.pushManager.getSubscription();
  const sameKey = subscription?.options?.applicationServerKey && new Uint8Array(subscription.options.applicationServerKey).every((byte, i) => byte === key[i]);
  if (subscription && !sameKey) { await subscription.unsubscribe(); subscription = null; }
  if (!subscription) subscription = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await savePushSubscription(subscription);
}
async function disablePush() {
  const subscription = await currentPushSubscription().catch(() => null);
  if (subscription) {
    await api('/push/unsubscribe', { method: 'POST', body: JSON.stringify({ endpoint: subscription.endpoint }) }).catch(() => {});
    await subscription.unsubscribe().catch(() => {});
  }
  state.pushEnabled = false;
}
async function syncPush() {
  try {
    if (!pushSupported() || Notification.permission !== 'granted') return;
    const subscription = await currentPushSubscription();
    if (subscription) await savePushSubscription(subscription);
  } catch {}
}
async function mountPushCard() {
  const note = document.querySelector('.profile-layout > .profile-note');
  if (!note) return;
  const stack = document.createElement('div');
  stack.className = 'context-stack';
  note.replaceWith(stack);
  stack.append(note);
  stack.insertAdjacentHTML('beforeend', '<section class="panel content push-card" id="push-card" aria-live="polite"><div class="eyebrow">Уведомления на этом устройстве</div><h2>Push-уведомления</h2><div id="push-body">' + skeletonLines(2) + '</div></section>');
  mountEmailCard(stack);
  const body = stack.querySelector('#push-body');
  const paint = async () => {
    const subscription = await currentPushSubscription().catch(() => null);
    state.pushEnabled = Boolean(subscription);
    if (!pushSupported()) {
      body.innerHTML = isIos() && !isStandalone()
        ? '<p>На iPhone уведомления работают из приложения на экране «Домой».</p><ol class="push-steps"><li>Нажмите «Поделиться» в Safari.</li><li>Выберите «На экран „Домой“».</li><li>Откройте кабинет с экрана «Домой» и вернитесь сюда.</li></ol>'
        : '<p>Этот браузер не поддерживает push-уведомления. Попробуйте Chrome, Edge, Firefox или Safari.</p>';
    } else if (Notification.permission === 'denied') {
      body.innerHTML = '<p>Уведомления запрещены в настройках браузера. Разрешите их для этого сайта и обновите страницу.</p>';
    } else if (subscription) {
      body.innerHTML = `<p class="push-on">${icon('check', 16)}Включены — новые события придут, даже если кабинет закрыт.</p><div class="row"><button class="button small" id="push-test">Проверить</button><button class="button small" id="push-off">Отключить</button></div>`;
    } else {
      body.innerHTML = '<p>Получайте новые сообщения, оценки и смены статуса на телефон или компьютер, даже когда кабинет закрыт.</p><button class="button primary" id="push-on">Включить уведомления</button>';
    }
    body.querySelector('#push-on')?.addEventListener('click', async e => { e.target.disabled = true; try { await enablePush(); toast('Уведомления включены'); } catch (error) { toast(error.message, 'error'); } paint(); });
    body.querySelector('#push-off')?.addEventListener('click', async e => { e.target.disabled = true; await disablePush(); toast('Уведомления на этом устройстве отключены', 'info'); paint(); });
    body.querySelector('#push-test')?.addEventListener('click', async e => { e.target.disabled = true; try { const { devices } = await api('/push/test', { method: 'POST' }); toast(devices ? 'Тестовое уведомление отправлено' : 'Устройство не подписано', devices ? 'success' : 'error'); } catch (error) { toast(error.message, 'error'); } e.target.disabled = false; });
  };
  paint();
}
function mountEmailCard(stack) {
  stack.insertAdjacentHTML('beforeend', '<section class="panel content push-card email-card" id="email-card" aria-live="polite"><div class="eyebrow">Почта</div><h2>Письма о заявках</h2><div id="email-body">' + skeletonLines(2) + '</div></section>');
  const body = stack.querySelector('#email-body');
  const customer = state.user.role === 'customer';
  const paint = async () => {
    let p;
    try { p = await api('/email/preferences'); } catch (error) { body.innerHTML = `<p>${esc(error.message)}</p>`; return; }
    if (!p.available) {
      body.innerHTML = `<p>${customer ? 'Отправка писем пока не настроена командой. Уведомления приходят в кабинет, push и мессенджеры.' : 'Почта не настроена: задайте SMTP_HOST и EMAIL_FROM на сервере (см. .env.example).'}</p>`;
      return;
    }
    body.innerHTML = `<form class="form" id="email-form"><p>Письма приходят на <strong>${esc(p.email)}</strong>, только если вы не увидели событие в кабинете в течение пары минут.${p.replies ? ' На письмо можно просто ответить — ответ попадёт в переписку.' : ''}</p><label class="check-row"><input type="checkbox" name="notify" ${p.notify ? 'checked' : ''}>Сообщения, оценки и другие события по заявкам</label>${customer ? `<label class="check-row"><input type="checkbox" name="digest" ${p.digest ? 'checked' : ''}>Ежемесячная сводка: что сделано, что в работе и что ждёт вас</label><label>Копия сводки руководителю<input class="field" name="digest_emails" type="text" inputmode="email" autocomplete="off" value="${esc(p.digest_emails.join(', '))}" placeholder="director@company.ru"><small>До трёх адресов через запятую. Удобно для тех, кто не заходит в кабинет.</small></label><a class="text-link" href="/api/digest/preview" target="_blank" rel="noopener">Посмотреть сводку за этот месяц ↗</a>` : ''}<div class="row"><button class="button primary small">Сохранить</button><button class="button small" type="button" id="email-test">${icon('mail', 14)}Тестовое письмо</button></div></form>`;
    const form = body.querySelector('#email-form');
    form.onsubmit = async e => {
      e.preventDefault();
      const button = form.querySelector('button.primary');
      button.disabled = true;
      const emails = (form.elements.digest_emails?.value || '').split(/[,;\s]+/).map(x => x.trim()).filter(Boolean);
      try { await api('/email/preferences', { method: 'PUT', body: JSON.stringify({ notify: form.elements.notify.checked, digest: Boolean(form.elements.digest?.checked), digest_emails: emails }) }); toast('Настройки писем сохранены'); paint(); }
      catch (error) { toast(error.message, 'error'); button.disabled = false; }
    };
    form.querySelector('#email-test').onclick = async e => {
      e.currentTarget.disabled = true;
      try { const r = await api('/email/test', { method: 'POST' }); toast(`Письмо отправлено на ${r.email}`); } catch (error) { toast(error.message, 'error'); }
      e.target.closest('button').disabled = false;
    };
  };
  paint();
}
function bindCtrlEnter(formSelector) {
  document.querySelector(`${formSelector} textarea`)?.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.target.form.requestSubmit(); } });
}

let audioCtx = null;
function playNotificationSound() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const now = audioCtx.currentTime;
    const osc1 = audioCtx.createOscillator();
    const gain1 = audioCtx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(659.25, now);
    gain1.gain.setValueAtTime(0.08, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
    osc1.connect(gain1);
    gain1.connect(audioCtx.destination);
    osc1.start(now);
    osc1.stop(now + 0.35);

    const osc2 = audioCtx.createOscillator();
    const gain2 = audioCtx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(880, now + 0.12);
    gain2.gain.setValueAtTime(0.08, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
    osc2.connect(gain2);
    gain2.connect(audioCtx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.5);
  } catch (e) {}
}

function showBrowserNotification(title, body) {
  if ('Notification' in window && Notification.permission === 'granted') {
    try {
      new Notification(title, { body, icon: '/icon.svg' });
    } catch (e) {}
  }
}

function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

function formatDuration(ms) {
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins} мин`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h < 24) return m ? `${h} ч ${m} м` : `${h} ч`;
  const d = Math.floor(h / 24);
  return `${d} д ${h % 24} ч`;
}

function ticketSla(t) {
  const now = Date.now();
  const items = [];
  const add = (label, due, warnMs) => {
    const diff = new Date(due).getTime() - now;
    items.push({ label, due, diff, tone: diff < 0 ? 'late' : diff < warnMs ? 'soon' : 'ok', text: diff < 0 ? `${label} −${formatDuration(-diff)}` : `${label} ${formatDuration(diff)}` });
  };
  if (!t.first_staff_response_at && t.response_due_at) add('Ответ', t.response_due_at, 2 * 3600 * 1000);
  if (!t.effort_minutes && t.estimate_due_at) add('Оценка', t.estimate_due_at, 4 * 3600 * 1000);
  if (t.delivery_due_at && t.status !== 'done' && t.status !== 'closed') add('Сдача', t.delivery_due_at, 24 * 3600 * 1000);
  return items;
}
function nearestSla(t) { return ticketSla(t).sort((a, b) => a.diff - b.diff)[0] || null; }
function slaTag(s) { return s ? `<span class="sla ${s.tone}" title="Срок: ${date(s.due)}">${icon('clock', 13)}${esc(s.text)}</span>` : ''; }
function ticketSlaBadges(t) { return ticketSla(t).map(slaTag).join(' '); }
function slaCard(t) {
  if (t.declined) return '<p class="muted">Заказчик отказался от заявки — сроки больше не отслеживаются.</p>';
  const now = Date.now();
  const created = new Date(t.created_at).getTime();
  const track = due => {
    const end = new Date(due).getTime();
    const diff = end - now;
    const pct = Math.min(100, Math.max(4, (now - created) / Math.max(1, end - created) * 100));
    return { text: diff < 0 ? `−${formatDuration(-diff)}` : `осталось ${formatDuration(diff)}`, tone: diff < 0 ? 'late' : pct > 75 ? 'soon' : 'ok', pct: diff < 0 ? 100 : pct, hint: `${diff < 0 ? 'Срок истёк' : 'Срок'}: ${date(due)}` };
  };
  const rows = [
    ['Первый ответ', t.first_staff_response_at ? { text: '✓ ответили', tone: 'met', pct: 100, hint: date(t.first_staff_response_at) } : t.response_due_at ? track(t.response_due_at) : null],
    ['Оценка', t.effort_minutes ? { text: '✓ подготовлена', tone: 'met', pct: 100 } : t.estimate_due_at ? track(t.estimate_due_at) : null],
    ['Сдача', ['done', 'closed'].includes(t.status) ? { text: '✓ выполнена', tone: 'met', pct: 100 } : t.delivery_due_at ? track(t.delivery_due_at) : null],
  ];
  return rows.map(([label, s]) => `<div class="sla-row"><div class="sla-row-head"><strong>${label}</strong><span class="${s ? s.tone : 'none'}">${s ? esc(s.text) : 'не задан'}</span></div><div class="meter"><span class="${s && ['late', 'soon'].includes(s.tone) ? s.tone : ''}" style="width:${s ? s.pct : 0}%"></span></div>${s?.hint ? `<small>${esc(s.hint)}</small>` : ''}</div>`).join('');
}
function paintConnection(){
  const el=document.querySelector('#connection-state');if(el)el.textContent=state.connection==='reconnecting'?'Связь потеряна · восстанавливаем':state.connection==='connecting'?'Подключаем обновления…':'Обновления включены';
}
function composerHasDraft(selector) {
  const form = document.querySelector(selector);
  return Boolean(form && (form.querySelector('textarea')?.value || form.elements.files?.files.length || form.getAttribute('aria-busy') === 'true'));
}
let eventSource = null;
function initRealtime() {
  if (eventSource) {
    try { eventSource.close(); } catch(e) {}
    eventSource = null;
  }
  if (!state.user) return;
  try {
    eventSource = new EventSource('/api/events');
    state.connection='connecting';
    eventSource.onopen=()=>{state.connection='connected';paintConnection();};
    eventSource.onerror=()=>{state.connection='reconnecting';paintConnection();};
    eventSource.addEventListener('update', async (e) => {
      try {
        const data = JSON.parse(e.data);
        if(data.type==='team_updated'){if(!document.querySelector('#team-dialog'))await TeamUI.reload();return;}
        if (data.type === 'read') {
          const current = data.target === 'ticket' ? (['detail', 'ticket-chat'].includes(state.view) && state.current?.ticket.id === data.record_id ? state.current : null) : (state.view === 'chat' && state.currentChat?.chat.id === data.record_id ? state.currentChat : null);
          if (current) { current.read_state = { customer_read_id: data.customer_read_id, team_read_id: data.team_read_id }; paintReadTicks(current.read_state); }
          return;
        }
        if (data.type === 'meeting_summary') {
          if (data.ticket_id && ['detail', 'ticket-chat'].includes(state.view) && state.current?.ticket.id === data.ticket_id && !composerHasDraft('#message-form')) await (state.view === 'ticket-chat' ? openTicketChat(data.ticket_id) : openTicket(data.ticket_id));
          if (data.chat_id && state.view === 'chat' && state.currentChat?.chat.id === data.chat_id && !composerHasDraft('#chat-message-form')) await openChat(data.chat_id);
          return;
        }
        playNotificationSound();
        if (data.type === 'notification') {
          if (!state.pushEnabled) showBrowserNotification('Линия · Новое уведомление', data.text);
          toast(data.text, 'info');
          await loadNotifications();
        } else if (data.type === 'ticket_message') {
          if (['detail', 'ticket-chat'].includes(state.view) && state.current && state.current.ticket.id === data.ticket_id) {
            if (!composerHasDraft('#message-form')) {
              await (state.view === 'ticket-chat' ? openTicketChat(data.ticket_id) : openTicket(data.ticket_id));
            }
          }
          await loadNotifications();
        } else if (data.type === 'chat_message') {
          if (state.view === 'chat' && state.currentChat && state.currentChat.chat.id === data.chat_id) {
            if (!composerHasDraft('#chat-message-form')) {
              const fresh = await api(`/chats/${data.chat_id}`);
              if (state.view !== 'chat' || state.currentChat?.chat.id !== data.chat_id || composerHasDraft('#chat-message-form')) return;
              state.currentChat = fresh;
              renderChatDetail();
            }
          }
          await loadNotifications();
        } else if (data.type === 'internal_note') {
          if (state.view === 'detail' && state.current && state.current.ticket.id === data.ticket_id) {
            await loadInternalNotes(data.ticket_id);
          }
        } else if (data.type === 'ticket_rated') {
          if (state.view === 'detail' && state.current && state.current.ticket.id === data.ticket_id) {
            await openTicket(data.ticket_id);
          }
        } else if (data.type === 'git_link_added') {
          if (state.view === 'detail' && state.current && state.current.ticket.id === data.ticket_id) {
            await loadGitLinks(data.ticket_id);
          }
        }
      } catch (err) {}
    });
  } catch (e) {}
}
async function api(path, options={}) {
  let response;
  try{response=await fetch('/api' + path, {headers:options.body instanceof FormData?{}:{'Content-Type':'application/json'}, ...options});}
  catch{throw new Error('Нет связи с сервером. Введённые данные сохранены; попробуйте ещё раз');}
  if (!response.ok) { const data = await response.json().catch(()=>({})); const error=new Error(typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)?data.detail.map(x=>`${x.loc?.at(-1)||'Поле'}: ${x.msg}`).join('; '):`Ошибка ${response.status}`);error.status=response.status;throw error; }
  return response.json();
}
function notice() { return state.error ? `<div class="notice" role="alert">${esc(state.error)}</div>` : ''; }
async function upload(path, file, extra={}) {
  const body=new FormData();body.append('file',file);Object.entries(extra).forEach(([key,value])=>body.append(key,value));
  const response=await fetch('/api'+path,{method:'POST',body});
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(typeof data.detail==='string'?data.detail:`Ошибка ${response.status}`);}
  return response.json();
}
function showError(error) {
  state.error = error.message || String(error);
  let host=document.querySelector('#billing-modal[open] .form')||document.querySelector('form[aria-busy="true"]')||document.querySelector('main')||document.querySelector('.auth-card')||app;
  let alert=host.querySelector('.notice[role="alert"]');
  if(!alert){alert=document.createElement('div');alert.className='notice';alert.setAttribute('role','alert');host.prepend(alert);}
  alert.textContent=state.error;
  host.querySelectorAll('button[data-submit-busy]').forEach(button=>{button.disabled=false;if(button.dataset.idleLabel){button.textContent=button.dataset.idleLabel;delete button.dataset.idleLabel;}button.removeAttribute('aria-busy');delete button.dataset.submitBusy;});
  if(host.matches('form'))host.removeAttribute('aria-busy');
  alert.scrollIntoView({block:'nearest'});
}
function syncRoute(){
  if(!state.user||state.user.must_change_credentials||state.restoringRoute)return;
  const route=state.view==='ticket-chat'?`ticket-chat/${state.current?.ticket.id}`:state.view==='detail'?`ticket/${state.current?.ticket.id}`:state.view==='chat'?`chat/${state.currentChat?.chat.id}`:state.view==='task'?`task/${state.currentTaskId}`:state.view;
  if(route&&!route.includes('undefined')&&location.hash!==`#${route}`)history.pushState(null,'',`#${route}`);
}
document.addEventListener('submit', event => {
  const form = event.target;
  const enhanced = form.matches('#profile-form, #customer-profile-form, #message-form, #chat-message-form, #billing-modal form');
  if (enhanced && form.getAttribute('aria-busy') === 'true') { event.preventDefault(); event.stopImmediatePropagation(); return; }
  form.querySelectorAll('button:not(:disabled)').forEach(button => { button.dataset.submitBusy = 'true'; });
  if (!enhanced) return;
  form.querySelector('.notice[role="alert"]')?.remove();
  form.setAttribute('aria-busy', 'true');
  const button = form.querySelector('button.primary');
  if (button) { button.dataset.idleLabel = button.textContent; button.textContent = form.classList.contains('composer') ? 'Отправляем…' : 'Сохраняем…'; button.disabled = true; button.setAttribute('aria-busy', 'true'); }
}, true);
document.addEventListener('click',event=>{const button=event.target.closest('button');if(button&&!button.disabled)button.dataset.submitBusy='true';},true);
function setView(view) { state.view=view; state.error=''; syncRoute(); render(); }
async function fetchNotifications() {
  const [tickets, chats] = await Promise.all([api('/notifications'), api('/chat-notifications')]);
  return [...tickets.map(n=>({...n,target:'ticket'})), ...chats.map(n=>({...n,target:'chat'}))].sort((a,b)=>b.created_at.localeCompare(a.created_at));
}
async function loadNotifications() {
  if (!state.user) return;
  const incoming = await fetchNotifications();
  const changed = JSON.stringify(incoming) !== JSON.stringify(state.notifications);
  state.notifications = incoming;
  const unread = state.notifications.filter(n=>!n.read_at).length+(state.user.role!=='customer'?(state.teamWorkspace?.events||[]).filter(e=>e.entity==='tasks'&&!e.read_at).length:0);
  const count = document.querySelector('#notification-count');
  const previous = Number(count?.textContent || 0);
  if (count) count.textContent = unread ? String(unread) : '';
  count?.closest('button')?.setAttribute('aria-label', `Уведомления${unread ? `: ${unread} новых` : ''}`);
  if (count && unread > previous) { count.classList.remove('bump'); void count.offsetWidth; count.classList.add('bump'); }
  if (changed && state.view === 'notifications') renderNotifications();
  if (changed && ['chats', 'chat', 'ticket-chat'].includes(state.view)) paintInboxUnread();
}
function resetAccountState() {
  TasksUI.reset();state.currentTaskId=null;TeamUI.reset();state.teamWorkspace=null;
  for (const key of ['tickets','chats','queue','staff','customers','organizations','notifications','internalNotes','cannedResponses','kbCategories','kbArticles','gitLinks','webhooks','waiting']) state[key]=[];
  for (const key of ['profile','current','currentChat','analytics','billing','bots','settings','kbReadingArticle','kbEditingArticle','replyTo']) state[key]=null;
  state.pairings={};state.pendingOps={};state.loadFailures=[];state.readSent={};
  state.inboxSection='general';state.chatSearch='';state.ticketChatSearch='';
  state.notificationFilter='all';state.notificationExpanded=new Set();
}
async function refresh() {
  const accountId=state.user?.id;
  if(state.user?.must_change_credentials)return renderCredentials();
  const staff=state.user.role!=='customer';
  const requests={tickets:()=>api('/tickets'),chats:()=>api('/chats'),organizations:()=>api('/organizations'),profile:()=>api(staff?'/profile/me':'/customer-profile/me'),notifications:fetchNotifications,settings:()=>api('/public/settings')};
  if(staff)Object.assign(requests,{staff:()=>api('/staff'),customers:()=>api('/customers'),queue:()=>api('/work-queue'),teamWorkspace:()=>api('/team')});
  else requests.waiting=()=>api('/waiting-on-me');
  const keys=Object.keys(requests);const results=await Promise.allSettled(keys.map(key=>requests[key]()));
  if(!state.user||state.user.id!==accountId)return;
  if(results.some(result=>result.status==='rejected'&&result.reason?.status===401)){state.user=null;resetAccountState();initRealtime();state.error='Сессия закончилась. Войдите снова.';renderAuth();return;}
  state.loadFailures=[];
  results.forEach((result,i)=>{const key=keys[i];if(result.status==='fulfilled')state[key]=result.value;else state.loadFailures.push(key);});
  state.profile ||= {name:state.user.name,email:state.user.email,job_title:'',bio:''};
  state.user.name=state.profile.name;
  render();
}

function renderAuth() {
  const params = new URLSearchParams(location.search);
  const tokenKind = params.has('invite') ? 'invite' : params.has('reset') ? 'reset' : null;
  if (tokenKind || state.authMode === 'reset') { renderAccountAccess(tokenKind, params.get(tokenKind)); return; }
  const registration = state.authMode === 'register';
  const feature = (ic, title, text) => `<div class="auth-feature"><i>${icon(ic)}</i><div><strong>${title}</strong><span>${text}</span></div></div>`;
  app.innerHTML = `<div class="auth"><section class="auth-brand"><div class="brand"><span class="brand-mark" aria-hidden="true">Л</span><span><span class="brand-name">Линия<span class="brand-dot">.</span></span><small>Кабинет заявок</small></span></div><div><h2>Заявки, переписка и часы — в одном кабинете</h2><div class="auth-features">${feature('ticket', 'Статус каждой задачи', 'От оценки до сдачи видно, на каком этапе работа и что будет дальше.')}${feature('clock', 'Часы согласуете вы', 'Работа начинается после того, как вы одобрите оценку трудозатрат.')}${feature('send', 'Уведомления в мессенджерах', 'Заявки и переписка доступны в Telegram и MAX.')}</div></div><a class="auth-foot" href="/landing">О сервисе →</a></section><main class="auth-main"><div class="auth-card"><div class="auth-mobile-brand"><span class="brand-mark" aria-hidden="true">Л</span>Линия</div><div class="top-text"><h1>${registration ? 'Создать кабинет' : 'Вход в кабинет'}</h1><p class="lead">${registration ? 'Уже есть кабинет?' : 'Нет кабинета?'} <button class="auth-switch" id="auth-switch" type="button">${registration ? 'Войти' : 'Зарегистрироваться'}</button></p></div>${notice()}<form class="form" id="auth-form">${registration ? '<label>Ваше имя<input class="field" name="name" required minlength="2" maxlength="100" autocomplete="name"></label>' : ''}<label>Email<input class="field" name="email" type="email" required autocomplete="email" placeholder="name@company.ru"></label><label>Пароль<input class="field" name="password" type="password" required minlength="8" autocomplete="${registration ? 'new-password' : 'current-password'}"></label><label class="row" style="display:flex;font-weight:600"><input type="checkbox" id="show-password" style="width:18px;height:18px;accent-color:var(--accent)">Показать пароль</label><button class="button primary">${registration ? 'Зарегистрироваться' : 'Войти'}</button></form></div></main></div>`;
  document.querySelector('#auth-switch').onclick = () => { state.authMode = registration ? 'login' : 'register'; state.error = ''; renderAuth(); };
  document.querySelector('#show-password').onchange = e => { document.querySelector('#auth-form [name="password"]').type = e.target.checked ? 'text' : 'password'; };
  document.querySelector('#auth-form').insertAdjacentHTML('beforeend', '<button type="button" class="auth-switch" id="forgot-password">Забыли пароль?</button>');
  document.querySelector('#forgot-password').onclick = () => { state.authMode='reset';state.error='';renderAuth(); };
  document.querySelector('#auth-form').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button.primary'); button.disabled = true; const data = Object.fromEntries(new FormData(e.target)); try { resetAccountState(); state.user = await api(registration ? '/register' : '/login', { method: 'POST', body: JSON.stringify(data) }); state.view = state.user.role === 'customer' ? 'tickets' : 'tasks'; state.error = ''; if(state.user.must_change_credentials){renderCredentials();return;} initRealtime();syncPush();state.restoringRoute=true;await refresh(); await openHash(); maybeStartTour(); } catch (error) { showError(error); } };
}
function renderAccountAccess(kind, token) {
  const title = kind === 'invite' ? 'Добро пожаловать в кабинет' : kind === 'reset' ? 'Новый пароль' : 'Восстановить доступ';
  app.innerHTML = `<main class="auth-main"><section class="auth-card"><h1>${title}</h1><p>${kind ? 'Задайте пароль от 8 символов. Ваши заявки и переписка сохранятся.' : 'Введите email для входа. Мы отправим ссылку для смены пароля.'}</p><div id="access-message" role="status" aria-live="polite"></div><form class="form" id="access-form">${kind ? '<label>Новый пароль<input class="field" name="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"></label><label>Повторите пароль<input class="field" name="repeat" type="password" required minlength="8" autocomplete="new-password"></label>' : '<label>Email<input class="field" name="email" type="email" required autocomplete="email"></label>'}<button class="button primary">${kind ? 'Сохранить пароль и войти' : 'Получить ссылку'}</button><button class="button" type="button" id="access-back">Ко входу</button></form></section></main>`;
  document.querySelector('#access-back').onclick=()=>{history.replaceState(null,'',location.pathname);state.authMode='login';state.error='';renderAuth();};
  document.querySelector('#access-form').onsubmit=async e=>{
    e.preventDefault();const form=e.target;const button=form.querySelector('button.primary');button.disabled=true;
    try{
      if(kind){
        if(form.elements.password.value!==form.elements.repeat.value)throw new Error('Пароли должны совпадать');
        state.user=await api(`/account/activate/${kind}`,{method:'POST',body:JSON.stringify({token,password:form.elements.password.value})});
        history.replaceState(null,'',location.pathname);state.view=state.user.role==='customer'?'tickets':'tasks';state.error='';initRealtime();syncPush();await refresh();maybeStartTour();
      }else{
        const result=await api('/account/reset-request',{method:'POST',body:JSON.stringify({email:form.elements.email.value})});
        document.querySelector('#access-message').textContent=result.message;
      }
    }catch(error){document.querySelector('#access-message').textContent=error.message;}finally{button.disabled=false;}
  };
}

function mountCustomerInvitation(host, organizationId = null, after = null) {
  host.innerHTML=`<form class="form customer-invite-form"><p class="muted">Укажите имя и email. Если кабинет уже есть, подключим его; для нового клиента отправим приглашение. История сохраняется.</p><label>Имя<input class="field" name="name" required minlength="2" maxlength="100"></label><label>Email<input class="field" name="email" type="email" required></label>${organizationId?'<label>Роль в компании<select class="field" name="role"><option value="member">Участник</option><option value="viewer">Наблюдатель</option><option value="owner">Владелец</option></select></label>':'<label>Название компании (необязательно)<input class="field" name="company_name" maxlength="150" minlength="2"><small>Если указать компанию, клиент станет её владельцем. Без компании будет личный кабинет.</small></label>'}<button class="button primary">Добавить клиента</button></form><div class="invite-result" role="status" aria-live="polite"></div>`;
  const form=host.querySelector('form');const result=host.querySelector('.invite-result');
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;try{
    const data=Object.fromEntries(new FormData(form));data.organization_id=organizationId;data.company_name=data.company_name||null;
    const access=await api('/customer-invitations',{method:'POST',body:JSON.stringify(data)});
    paintInvitationResult(result,access);
    if(state.user.role!=='customer')state.customers=await api('/customers');state.organizations=await api('/organizations');if(after)after(access);
    if(state.view==='organizations'){const saved=result.innerHTML;renderOrganizations();const target=document.querySelector(`[data-invite-host="${organizationId||'new'}"] .invite-result`);if(target){paintInvitationResult(target,access);const disclosure=target.closest('details');if(disclosure)disclosure.open=true;target.scrollIntoView({block:'nearest'});}}
  }catch(error){result.textContent=error.message;}finally{button.disabled=false;}};
}
function paintInvitationResult(result,access){
  result.innerHTML=access.registered?'<p>Кабинет уже существует. Клиент подключён; пароль и история сохранены.</p>':`<p>Кабинет создан. Приглашение поставлено в очередь почты.</p><label>Ссылка приглашения<input class="field" readonly value="${esc(access.url)}"></label><button type="button" class="button small" data-copy-invite>Скопировать ссылку</button><p class="muted">До ${date(access.expires_at)}. Для активации клиент задаст пароль.</p>`;
  result.querySelector('[data-copy-invite]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(access.url);toast('Ссылка скопирована');}catch{result.querySelector('input').select();toast('Выделили ссылку — скопируйте её');}});
}
async function mountInvitationList(){
  const host=document.querySelector('#invitation-list');if(!host)return;
  try{const list=await api('/customer-invitations');if(!host.isConnected)return;
    const statuses={pending:'Ожидает первого входа',expired:'Приглашение истекло',activated:'Кабинет активирован'};
    const deliveries={pending:'В очереди отправки',sending:'Отправляется',sent:'Письмо отправлено',failed:'Ошибка доставки',dead:'Ошибка доставки'};
    host.innerHTML=list.length?list.map(item=>`<section class="content"><strong>${esc(item.name)}</strong><p>${esc(item.email)} · ${statuses[item.status]}</p><p class="muted">${deliveries[item.delivery_state]||'Статус доставки уточняется'}${item.expires_at?' · до '+date(item.expires_at):''}</p>${item.status!=='activated'?`<button class="button small" data-resend-invite="${item.customer_id}">Отправить новое приглашение</button><div data-invite-result="${item.customer_id}" role="status"></div>`:''}</section>`).join(''):'<p class="muted">Приглашений пока нет.</p>';
    host.querySelectorAll('[data-resend-invite]').forEach(button=>button.onclick=async()=>{const item=list.find(x=>x.customer_id===Number(button.dataset.resendInvite));button.disabled=true;try{const access=await api('/customer-invitations',{method:'POST',body:JSON.stringify({name:item.name,email:item.email,organization_id:item.organization_id,role:item.role||'member'})});paintInvitationResult(host.querySelector(`[data-invite-result="${item.customer_id}"]`),access);button.textContent='Новое приглашение подготовлено';}catch(error){showError(error);}finally{button.disabled=false;}});
  }catch(error){host.textContent=error.message;}
}

function shell(title, action, body, opts = {}) {
  const staff = state.user.role !== 'customer';
  const admin = state.user.role === 'admin';
  const dispatcher = isDispatcher();
  const v = state.view;
  const unread = state.notifications.filter(n => !n.read_at).length+(staff?(state.teamWorkspace?.events||[]).filter(e=>e.entity==='tasks'&&!e.read_at).length:0);
  const chatUnread = state.notifications.filter(n => ['chat', 'ticket'].includes(n.target) && !n.read_at).length;
  const activeTasks=(state.teamWorkspace?.tasks||[]).filter(t=>t.status!=='done'&&t.status!=='cancelled'&&(t.owner_id===state.user.id||(t.participants||[]).includes(state.user.id)||(t.reviewer_id===state.user.id&&t.status==='review'))).length;
  const activeDeals = (state.teamWorkspace?.deals || []).filter(d => !['won', 'lost'].includes(d.stage)).length;
  const activeMeetings = (state.teamWorkspace?.meetings || []).filter(m => m.status === 'planned').length;
  const activeTickets = state.tickets.filter(t => !['done', 'closed'].includes(t.status)).length;
  const ticketsActive = ['tickets', 'detail', 'new'].includes(v);
  const chatsActive = ['chats', 'chat', 'ticket-chat'].includes(v);
  const item = (id, label, ic, active, count, tone = '') => `<button class="nav-item ${active ? 'active' : ''}" data-nav="${id}" ${active ? 'aria-current="page"' : ''}>${icon(ic)}<span>${label}</span>${count ? `<span class="nav-count ${tone}">${count}</span>` : ''}</button>`;

  const groups = staff ? [
    ['Совместная работа', [
      item('tasks', 'Задачи и Проекты', 'check', ['tasks','task'].includes(v), activeTasks, 'accent'),
      item('deals', 'CRM и Сделки', 'briefcase', v === 'deals', activeDeals),
      item('meetings', 'Календарь и Встречи', 'calendar', v === 'meetings', activeMeetings),
      item('chats', 'Чат и Сообщения', 'chat', chatsActive, chatUnread, 'accent'),
    ]],
    ['Поддержка и Клиенты', [
      item('tickets', 'Заявки клиентов', 'ticket', ticketsActive || v === 'queue', activeTickets),
      item('organizations', 'Клиенты и Компании', 'building', v === 'organizations'),
      item('kb', 'База знаний', 'book', v === 'kb'),
    ]],
    ['Компания и Учет', [
      item('team', 'Сотрудники и Структура', 'users', v === 'team'),
      item('payroll', admin ? 'Выплаты исполнителям' : 'Мои начисления', 'wallet', v === 'payroll'),
      billingOn() && item('billing', 'Биллинг и счета', 'wallet', v === 'billing'),
      dispatcher && item('analytics', 'Аналитика и SLA', 'chart', v === 'analytics'),
    ]],
    ['Настройки', [
      item('profile', 'Мой профиль', 'user', v === 'profile'),
      item('messengers', 'Мессенджеры', 'send', v === 'messengers'),
      admin && item('webhooks', 'Вебхуки', 'link', v === 'webhooks'),
    ]],
  ].map(([label, items]) => { const list = items.filter(Boolean); return list.length ? `<div class="nav-group-label">${label}</div>${list.join('')}` : ''; }).join('')
  : [
    ['Мой кабинет', [
      item('tickets', 'Мои заявки', 'ticket', ticketsActive, activeTickets),
      item('specialists', 'Наша команда', 'users', v === 'specialists'),
      item('chats', 'Чат с поддержкой', 'chat', chatsActive, chatUnread, 'accent'),
      state.organizations.length && item('organizations', 'Моя компания', 'building', v === 'organizations'),
      item('kb', 'База знаний', 'book', v === 'kb'),
      billingOn() && item('billing', 'Счета и Биллинг', 'wallet', v === 'billing'),
      item('profile', 'Мой профиль', 'user', v === 'profile'),
      item('messengers', 'Мессенджеры', 'send', v === 'messengers'),
    ]]
  ].map(([label, items]) => { const list = items.filter(Boolean); return list.length ? `<div class="nav-group-label">${label}</div>${list.join('')}` : ''; }).join('');

  const tab = (id, label, ic, active, count) => `<button class="${active ? 'active' : ''}" data-nav="${id}" ${active ? 'aria-current="page"' : ''}>${icon(ic, 22)}${label}${count ? `<span class="dot-count">${count}</span>` : ''}</button>`;
  const tabs = [
    staff ? tab('tasks', 'Задачи', 'check', ['tasks','task'].includes(v)) : tab('tickets', 'Заявки', 'ticket', ticketsActive),
    staff ? tab('deals', 'Сделки', 'briefcase', v === 'deals', activeDeals) : tab('notifications', 'События', 'bell', v === 'notifications', unread),
    tab('chats', 'Чат', 'chat', chatsActive, chatUnread),
    staff ? tab('tickets', 'Заявки', 'ticket', ticketsActive) : (billingOn() ? tab('billing', 'Счета', 'wallet', v === 'billing') : tab('profile', 'Профиль', 'user', v === 'profile')),
    `<button data-nav-toggle aria-controls="sidebar" aria-expanded="false">${icon('more', 22)}Ещё</button>`,
  ].join('');

  const role = admin ? 'Администратор' : state.user.is_manager ? 'Менеджер' : 'Сотрудник';
  const subtitle = staff ? (state.profile?.job_title || role) : (state.organizations[0]?.name || state.profile?.company_name || 'Заказчик');
  const kicker = opts.kicker ?? (staff ? 'Рабочее место' : 'Личный кабинет');
  const viewKey = `${v}:${['detail', 'ticket-chat'].includes(v) ? state.current?.ticket?.id : v === 'chat' ? state.currentChat?.chat?.id : v==='task'?state.currentTaskId:''}`;
  clearTimeout(loadingTimer);
  const preserved = viewKey === lastViewKey ? captureUi() : null;
  const entering = viewKey !== lastViewKey && !reduceMotion();
  lastViewKey = viewKey;
  document.body.classList.remove('nav-open');

  const mePerson = staff ? (state.teamWorkspace?.people || []).find(p => p.id === state.user.id) : null;
  const myAvailability = mePerson?.availability || 'available';
  const availabilityLabels = { available: 'На работе', vacation: 'В отпуске', sick: 'Больничный', away: 'Отсутствует' };
  const workdayWidget = staff ? `
    <div class="workday-widget" id="workday-widget">
      <button type="button" class="workday-btn" id="workday-btn" title="Статус рабочего дня">
        <span class="workday-dot ${myAvailability}"></span>
        <span class="workday-label">${availabilityLabels[myAvailability] || 'На работе'}</span>
      </button>
      <div class="workday-menu bitrix-quick-menu" id="workday-menu" hidden>
        <button type="button" data-set-status="available"><span class="workday-dot available"></span>На работе</button>
        <button type="button" data-set-status="vacation"><span class="workday-dot vacation"></span>В отпуске</button>
        <button type="button" data-set-status="sick"><span class="workday-dot sick"></span>Больничный</button>
        <button type="button" data-set-status="away"><span class="workday-dot away"></span>Отсутствует</button>
      </div>
    </div>
  ` : '';

  const createButton = staff ? `
    <div class="bitrix-create-wrap">
      <button class="button primary bitrix-top-create" id="bitrix-create-btn" aria-haspopup="menu" aria-expanded="false" title="Быстрое создание">
        ${icon('plus', 16)}<span>Создать</span>${icon('chevron', 12)}
      </button>
      <div class="bitrix-quick-menu" id="bitrix-create-menu" hidden>
        <button type="button" data-bitrix-create="task">${icon('check', 16)}<span>Новая задача</span></button>
        <button type="button" data-bitrix-create="deal">${icon('briefcase', 16)}<span>Новая сделка</span></button>
        <button type="button" data-bitrix-create="meeting">${icon('calendar', 16)}<span>Запланировать встречу</span></button>
        <button type="button" data-bitrix-create="ticket">${icon('ticket', 16)}<span>Новая заявка</span></button>
      </div>
    </div>
  ` : `<button class="button primary" id="top-new-ticket" aria-label="Новая заявка">${icon('plus', 16)}<span>Новая заявка</span></button>`;

  app.innerHTML = `<a class="skip-link" href="#main">Перейти к содержимому</a>
  <div class="shell">
    <aside id="sidebar" aria-label="Основное меню">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">Л</span>
        <span><span class="brand-name">Линия<span class="brand-dot">.</span></span><small>${staff ? 'Рабочее пространство' : 'Кабинет заявок'}</small></span>
      </div>
      <nav class="nav">${groups}</nav>
      <div class="aside-bottom aside-user">
        <button type="button" class="aside-profile ${v === 'profile' ? 'active' : ''}" data-nav="profile" aria-label="Открыть мой профиль" title="Мой профиль" ${v === 'profile' ? 'aria-current="page"' : ''}>
          ${avatar(state.profile, 'small')}
          <span class="aside-user-meta"><strong>${esc(state.user.name)}</strong><small>${esc(subtitle)}</small></span>
        </button>
        <button id="theme-toggle" class="aside-logout" aria-label="Сменить тему">${icon(effectiveTheme() === 'dark' ? 'sun' : 'moon')}</button>
        <button id="logout" class="aside-logout" aria-label="Выйти" title="Выйти">${icon('logout')}</button>
      </div>
    </aside>
    <div class="nav-backdrop" data-nav-close></div>
    <div class="workspace">
      <header class="topbar">
        <button class="icon-btn menu-btn" data-nav-toggle aria-controls="sidebar" aria-expanded="false" aria-label="Открыть меню">${icon('menu')}</button>
        <button type="button" class="global-search" id="open-palette" aria-haspopup="dialog">${icon('search', 17)}<span class="global-search-text">Поиск задач, сделок, заявок, контактов...</span><kbd>Ctrl K</kbd></button>
        <span class="topbar-spacer"></span>
        ${workdayWidget}
        <span id="connection-state" class="muted connection-state" role="status"></span>
        ${createButton}
        ${staff ? '' : `<button class="icon-btn" id="help-tour" aria-label="Пройти обучение по кабинету" title="Обучение по кабинету">${icon('help')}</button>`}
        <button class="icon-btn ${v === 'notifications' ? 'active' : ''}" data-nav="notifications" aria-label="Уведомления${unread ? `: ${unread} новых` : ''}">${icon('bell')}<span class="dot-count" id="notification-count">${unread || ''}</span></button>
        <button class="top-profile ${v === 'profile' ? 'active' : ''}" data-nav="profile" aria-label="Мой профиль">${avatar(state.profile, 'small')}${icon('chevron', 14)}</button>
      </header>
      <main id="main" tabindex="-1" class="${entering ? 'is-entering' : ''}">
        ${opts.crumbs ? `<nav class="crumbs" aria-label="Навигационная цепочка">${opts.crumbs}</nav>` : ''}
        <div class="top">
          <div class="top-text">
            ${opts.badges ? `<div class="top-badges">${opts.badges}</div>` : kicker ? `<div class="eyebrow">${kicker}</div>` : ''}
            <h1>${esc(title)}</h1>
            ${opts.lead ? `<p class="lead">${opts.lead}</p>` : ''}
          </div>
          ${action ? `<div class="top-actions">${action}</div>` : ''}
        </div>
        ${notice()}
        ${state.loadFailures?.length ? '<div class="notice" role="status">Часть данных не обновилась. Доступные данные сохранены. <button class="button small" id="retry-load">Повторить загрузку</button></div>' : ''}
        ${body}
      </main>
    </div>
    <nav class="tabbar" aria-label="Быстрая навигация">${tabs}</nav>
  </div>`;

  document.querySelector('.skip-link').onclick = event => {
    event.preventDefault();
    document.querySelector('#main').focus();
    document.querySelector('#main').scrollIntoView({ block: 'start', behavior: 'instant' });
  };
  document.querySelector('#retry-load')?.addEventListener('click', () => refresh());

  const navActions = {
    tasks: () => setView('tasks'),
    deals: () => setView('deals'),
    meetings: () => setView('meetings'),
    queue: () => setView('queue'),
    tickets: () => setView('tickets'),
    notifications: () => setView('notifications'),
    profile: () => setView('profile'),
    organizations: () => setView('organizations'),
    team: () => setView('team'),
    kb: () => openKb(),
    billing: () => billingOn() ? openBilling() : setView('tickets'),
    payroll: () => setView('payroll'),
    analytics: () => openAnalytics(),
    webhooks: () => openWebhooks(),
    messengers: () => openMessengers(),
    specialists: () => openSpecialists(),
    chats: async () => { if (staff || state.inboxSection === 'tickets') return setView('chats'); try { const chat = await api('/chats', { method: 'POST' }); await refresh(); await openChat(chat.id); } catch (error) { showError(error); } },
  };

  document.querySelectorAll('[data-nav]').forEach(button => button.onclick = () => {
    if (document.body.classList.contains('nav-open')) document.querySelector('[data-nav-close]')?.click();
    navActions[button.dataset.nav]?.();
  });

  document.querySelectorAll('[data-nav-toggle]').forEach(button => button.onclick = () => {
    const open = document.body.classList.toggle('nav-open');
    document.querySelectorAll('[data-nav-toggle]').forEach(toggle => toggle.setAttribute('aria-expanded', String(open)));
    document.querySelector('.workspace').inert = open;
    document.querySelector('.tabbar').inert = open;
    if (open) requestAnimationFrame(() => (document.querySelector('#sidebar .nav-item.active') || document.querySelector('#sidebar .nav-item'))?.focus());
  });

  document.querySelector('[data-nav-close]').onclick = () => {
    document.body.classList.remove('nav-open');
    document.querySelector('.workspace').inert = false;
    document.querySelector('.tabbar').inert = false;
    document.querySelectorAll('[data-nav-toggle]').forEach(toggle => toggle.setAttribute('aria-expanded', 'false'));
    document.querySelector('.menu-btn')?.focus();
  };

  document.querySelector('#sidebar').onkeydown = event => {
    if (event.key !== 'Tab' || !document.body.classList.contains('nav-open')) return;
    const buttons = [...document.querySelectorAll('#sidebar button:not(:disabled)')];
    if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
    else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
  };

  const createBtnEl = document.querySelector('#bitrix-create-btn');
  const createMenuEl = document.querySelector('#bitrix-create-menu');
  if (createBtnEl && createMenuEl) {
    createBtnEl.onclick = e => {
      e.stopPropagation();
      const open = createMenuEl.hidden;
      createMenuEl.hidden = !open;
      createBtnEl.setAttribute('aria-expanded', String(open));
    };
    document.querySelectorAll('[data-bitrix-create]').forEach(b => b.onclick = e => {
      createMenuEl.hidden = true;
      createBtnEl.setAttribute('aria-expanded', 'false');
      const action = b.dataset.bitrixCreate;
      if (action === 'task') TasksUI.quickCreate();
      else if (action === 'deal') TeamUI.workDialog('deals');
      else if (action === 'meeting') TeamUI.workDialog('meetings');
      else if (action === 'ticket') setView('new');
    });
  }
  const topNewTicket = document.querySelector('#top-new-ticket');
  if (topNewTicket) {
    topNewTicket.onclick = () => setView('new');
  }

  const workdayBtnEl = document.querySelector('#workday-btn');
  const workdayMenuEl = document.querySelector('#workday-menu');
  if (workdayBtnEl && workdayMenuEl) {
    workdayBtnEl.onclick = e => {
      e.stopPropagation();
      workdayMenuEl.hidden = !workdayMenuEl.hidden;
    };
    document.querySelectorAll('[data-set-status]').forEach(b => b.onclick = async e => {
      workdayMenuEl.hidden = true;
      const status = b.dataset.setStatus;
      try {
        await api('/team/me/availability', { method: 'PATCH', body: JSON.stringify({ availability: status }) });
        await TeamUI.reload();
        toast('Статус обновлён: ' + (availabilityLabels[status] || status));
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  document.addEventListener('click', () => {
    if (createMenuEl) createMenuEl.hidden = true;
    if (workdayMenuEl) workdayMenuEl.hidden = true;
  });

  document.querySelector('#open-palette').onclick = () => openPalette();
  document.querySelector('#help-tour')?.addEventListener('click', () => startTour());
  document.querySelector('#theme-toggle').onclick = toggleTheme;
  syncThemeUi();paintConnection();
  if (entering) queueMicrotask(animateEntrance);
  queueMicrotask(() => { bindDrafts(); if (preserved) restoreUi(preserved); });
  document.querySelector('#logout').onclick = async () => { await disablePush(); await api('/logout', { method: 'POST' }); state.user = null; resetAccountState();initRealtime();state.current = null; state.bots = null; state.pairings = {}; state.pendingOps = {}; state.error = ''; renderAuth(); };
}
function recentActivity() {
  const items = state.notifications.slice(0, 3).map(n => `<div class="activity-item"><span class="activity-dot ${n.read_at ? '' : 'fresh'}"></span><div><strong>${esc(n.text)}</strong><small>${date(n.created_at)}</small></div></div>`).join('');
  return `<section class="activity-panel"><div class="activity-heading"><h2>Последние события</h2><span>${state.notifications.length ? `всего ${state.notifications.length}` : ''}</span></div>${items || '<p class="muted">Новых событий пока нет.</p>'}</section>`;
}
function portfolioOverview(all) {
  const staff = state.user.role !== 'customer';
  const total = all.length;
  const done = all.filter(t => ['done', 'closed'].includes(t.status)).length;
  const approvedTickets = all.filter(t => t.estimate_state === 'approved');
  const approved = approvedTickets.reduce((sum, t) => sum + (t.effort_minutes || 0), 0);
  const pending = all.filter(t => t.estimate_state === 'pending' && (staff || t.can_decide));
  const pendingMinutes = pending.reduce((sum, t) => sum + (t.effort_minutes || 0), 0);
  const approvedSum = approvedTickets.reduce((sum, t) => sum + (t.cost_rub || t.estimate_amount_rub || 0), 0);
  const pendingSum = pending.reduce((sum, t) => sum + (t.estimate_amount_rub || 0), 0);
  const parts = Object.keys(statusChipNames).map(key => ({ key, label: statusChipNames[key], count: all.filter(t => t.status === key).length }));
  const chart = parts.filter(p => p.count).map(p => `<button class="portfolio-segment ${p.key}" data-overview-filter="${p.key}" style="width:${p.count / total * 100}%" aria-label="${p.label}: ${p.count}" title="${p.label}: ${p.count}"></button>`).join('');
  const col2 = staff
    ? `<div><span class="eyebrow">Согласовано часов</span><strong class="big">${hours(approved)}</strong><span class="muted">${approvedTickets.length ? `по ${approvedTickets.length} ${plural(approvedTickets.length, ['заявке', 'заявкам', 'заявкам'])}` : 'Пока нет согласованных оценок'}</span></div>`
    : `<div><span class="eyebrow">Согласовано</span><strong class="big">${approvedSum.toLocaleString('ru-RU')} ₽</strong><span class="muted">${approvedTickets.length ? `по ${approvedTickets.length} ${plural(approvedTickets.length, ['заявке', 'заявкам', 'заявкам'])}` : 'Пока нет согласованных оценок'}</span></div>`;
  const col3 = staff
    ? `<div><span class="eyebrow">Ждут решения заказчика</span><strong class="big">${pending.length} ${plural(pending.length, ['оценка', 'оценки', 'оценок'])}</strong><span class="muted">${pending.length ? `на ${hours(pendingMinutes)}` : 'Нет оценок на согласовании'}</span></div>`
    : `<div><span class="eyebrow">Ждут вашего решения</span><strong class="big">${pending.length} ${plural(pending.length, ['оценка', 'оценки', 'оценок'])}</strong><span class="muted">${pending.length ? `на ${pendingSum.toLocaleString('ru-RU')} ₽` : 'Нет оценок на согласовании'}</span></div>`;
  return `<section class="panel overview-card" aria-label="Сводка по заявкам"><div><div class="overview-head"><span class="eyebrow">По статусам</span><strong>${total} ${plural(total, ['заявка', 'заявки', 'заявок'])} · ${done} завершено</strong></div><div class="portfolio-track" role="group" aria-label="Фильтр по статусам заявок">${chart}</div><div class="portfolio-legends">${parts.map(p => `<span>${p.label} <strong>${p.count}</strong></span>`).join('')}</div></div>${col2}${col3}</section>`;
}
function queueItemSla(item) {
  if (item.source === 'ticket') { const t = state.tickets.find(x => x.id === item.id); const s = t && nearestSla(t); if (s) return s; }
  if (item.deadline) { const diff = new Date(item.deadline).getTime() - Date.now(); return { due: item.deadline, diff, tone: diff < 0 ? 'late' : diff < 24 * 3600 * 1000 ? 'soon' : 'ok', text: diff < 0 ? `Срок −${formatDuration(-diff)}` : `Срок ${formatDuration(diff)}` }; }
  return null;
}
function workloadPanel() {
  const people = state.staff.filter(person => person.role !== 'admin' || state.queue.some(item => item.assignee_id === person.id));
  const load = people.map(person => { const assigned = state.queue.filter(item => item.source === 'ticket' && item.assignee_id === person.id); return { person, count: assigned.length, urgent: assigned.filter(item => item.priority <= 1).length }; });
  const unassigned = state.queue.filter(item => item.source === 'ticket' && !item.assignee_id).length;
  const max = Math.max(1, unassigned, ...load.map(x => x.count));
  const rows = load.map(({ person, count, urgent }) => `${avatar(person, 'small')}<div class="workload-name">${esc(person.name)}<div class="meter"><span style="width:${count / max * 100}%"></span></div></div><span class="workload-count"><strong>${count}</strong>${urgent ? ` · <span class="workload-urgent">${urgent} срочно</span>` : ''}</span>`).join('');
  const none = unassigned ? `<span class="person-avatar small vacant" aria-hidden="true">+</span><div class="workload-name unassigned">Не назначены<div class="meter"><span class="soon" style="width:${unassigned / max * 100}%"></span></div></div><span class="workload-count"><strong>${unassigned}</strong></span>` : '';
  return `<section class="activity-panel"><div class="activity-heading"><h2>Нагрузка команды</h2><span>заявки в очереди</span></div>${rows || none ? `<div class="workload">${rows}${none}</div>` : '<p class="muted">Нет назначенных заявок.</p>'}</section>`;
}
const waitingIcons = { estimate: 'clock', hours: 'clock', acceptance: 'check', answer: 'chat' };
function waitingAge(iso) {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  return { days, text: days < 1 ? 'с сегодняшнего дня' : `ждёт ${days} ${plural(days, ['день', 'дня', 'дней'])}` };
}
function waitingPanel() {
  const items = state.waiting || [];
  if (!items.length) return state.tickets.some(t => t.status !== 'closed') ? `<section class="waiting-panel clear" aria-label="Ждём от вас">${icon('check', 18)}<div><strong>От вас сейчас ничего не нужно</strong><span>Команда работает. Если понадобится ваше решение, заявка появится здесь.</span></div></section>` : '';
  const rows = items.map(w => {
    const age = waitingAge(w.since);
    return `<button type="button" class="waiting-row" data-waiting-ticket="${w.ticket_id}"><span class="waiting-ico ${w.kind}">${icon(waitingIcons[w.kind] || 'alert', 17)}</span><span class="waiting-text"><strong>${esc(w.action)}</strong><small>№${w.ticket_id} · ${esc(w.title)}</small><small class="waiting-detail">${esc(w.detail)}</small></span><span class="waiting-age ${age.days >= 2 ? 'late' : ''}">${age.text}</span><span class="waiting-go">${icon('arrow', 16)}</span></button>`;
  }).join('');
  const estimates = items.filter(w => w.kind === 'estimate');
  const total = estimates.reduce((sum, w) => sum + (w.amount_rub || (w.effort_minutes ? Math.round(w.effort_minutes / 60 * 3000) : 0)), 0);
  const bulk = estimates.length > 1 ? `<div class="waiting-bulk"><span><strong>${estimates.length} ${plural(estimates.length, ['оценка', 'оценки', 'оценок'])}</strong> на ${total.toLocaleString('ru-RU')} ₽ ждут одобрения</span><button type="button" class="button primary" id="approve-all">${icon('check', 16)}Одобрить все</button><button type="button" class="button primary" id="approve-all-confirm" hidden>Подтвердить: ${total.toLocaleString('ru-RU')} ₽</button><button type="button" class="button" id="approve-all-cancel" hidden>Отмена</button></div>` : '';
  return `<section class="panel waiting-panel" aria-labelledby="waiting-title"><div class="waiting-head"><div><span class="eyebrow">Ваше действие</span><h2 id="waiting-title">Ждём от вас</h2></div><span class="waiting-count" aria-label="${items.length} ${plural(items.length, ['шаг', 'шага', 'шагов'])}">${items.length}</span></div><div class="waiting-list">${rows}</div>${bulk}<p class="waiting-hint">Пока эти шаги не сделаны, работа по заявкам стоит.</p></section>`;
}
function bindWaitingBulk() {
  const start = document.querySelector('#approve-all');
  if (!start) return;
  const confirm = document.querySelector('#approve-all-confirm');
  const cancel = document.querySelector('#approve-all-cancel');
  const toggle = asking => { start.hidden = asking; confirm.hidden = !asking; cancel.hidden = !asking; };
  start.onclick = () => { toggle(true); confirm.focus(); };
  cancel.onclick = () => toggle(false);
  confirm.onclick = async () => {
    confirm.disabled = true;
    const ids = (state.waiting || []).filter(w => w.kind === 'estimate').map(w => w.ref_id);
    try { const result = await api('/estimates/approve', { method: 'POST', body: JSON.stringify({ estimate_ids: ids }) }); toast(`Одобрено оценок: ${result.approved} — команда приступит к работе`); await refresh(); }
    catch (error) { showError(error); await refresh(); }
  };
}
function renderTickets() {
  const staff = state.user.role !== 'customer';
  const dispatcher = isDispatcher();
  const owned = state.tickets.filter(t => state.owner === 'mine' ? t.assignee_id === state.user.id : state.owner === 'unassigned' ? !t.assignee_id : true);
  if (!statusChipNames[state.filter]) state.filter = 'all';
  const visible = owned.filter(t => state.filter === 'all' || t.status === state.filter);
  const chip = (key, label, count, dot = '') => `<button type="button" class="chip ${state.filter === key ? 'active' : ''}" data-status-filter="${key}" aria-pressed="${state.filter === key}">${dot ? `<span class="dot ${dot}"></span>` : ''}${label} <i>${count}</i></button>`;
  const chips = chip('all', 'Все', owned.length) + Object.entries(statusChipNames).map(([key, label]) => chip(key, label, owned.filter(t => t.status === key).length, key)).join('');
  const ownerSelect = staff ? `<label class="select-inline"><span>Ответственный</span><select id="owner-filter"><option value="all">Все</option><option value="mine">Мои</option>${dispatcher ? '<option value="unassigned">Без ответственного</option>' : ''}</select></label>` : '';
  const prioritySelect = `<label class="select-inline"><span>Приоритет</span><select id="priority-filter"><option value="all">Все</option><option value="urgent">Критический</option><option value="high">Высокий</option><option value="normal">Обычный</option><option value="low">Низкий</option></select></label>`;
  state.selectedTickets = state.selectedTickets || new Set();
  const ticketRow = t => {
    const sla = nearestSla(t);
    const finished = ['done', 'closed'].includes(t.status);
    const deadline = sla ? slaTag(sla) : finished ? `<span class="sla met">${icon('check', 13)}Завершена</span>` : `<span class="tdate">${esc(t.next_step || '—')}</span>`;
    const prioBadge = t.priority && t.priority !== 'normal' ? `<span class="badge priority-${esc(t.priority)}">${esc(priorityNames[t.priority] || t.priority)}</span>` : '<span class="muted" style="font-size:11px">Обычный</span>';
    const estimateCol = staff
      ? (t.effort_minutes ? hours(t.effort_minutes) : '—')
      : (t.estimate_amount_rub ? `${t.estimate_amount_rub.toLocaleString('ru-RU')} ₽` : (t.cost_rub ? `${t.cost_rub.toLocaleString('ru-RU')} ₽` : '—'));
    const canClaim = staff && t.assignee_id !== state.user.id && !['done', 'closed'].includes(t.status);
    const claimBtn = canClaim ? `<button type="button" class="button small btn-claim-ticket" data-claim-ticket="${t.id}" title="Взять заявку себе">${icon('user', 12)} Взять себе</button>` : '';
    const selectBox = staff ? `<span class="t-select-cell" onclick="event.stopPropagation()"><input type="checkbox" class="ticket-select-cb" data-ticket-select="${t.id}" ${state.selectedTickets.has(t.id) ? 'checked' : ''} aria-label="Выбрать заявку №${t.id}"></span>` : '';
    return `<button class="trow" data-ticket="${t.id}">${selectBox}<span class="tnum">${t.id}</span><span class="ttitle"><strong>${esc(t.title)}</strong><small>${esc([t.customer_name, staff ? t.customer_company : '', serviceLabel(t.service_type)].filter(Boolean).join(' · '))}</small></span><span class="badge ${esc(t.status)}">${statusNames[t.status]}</span><span>${deadline}</span><span class="tnum-strong">${estimateCol}</span><span class="twho">${avatarOf(t.assignee_id, t.assignee_name)}<span>${esc(t.assignee_name || 'Не назначен')}</span></span><span>${prioBadge}</span><span class="tdate">${date(t.updated_at)}</span>${staff ? `<span class="t-actions-cell" onclick="event.stopPropagation()">${claimBtn}</span>` : ''}</button>`;
  };
  const head = `<div class="table-head" aria-hidden="true">${staff ? `<span class="t-select-cell"><input type="checkbox" id="tickets-select-all" aria-label="Выбрать все" ${visible.length && visible.every(t => state.selectedTickets.has(t.id)) ? 'checked' : ''}></span>` : ''}<span>№</span><span>Заявка</span><span>Статус</span><span>Ближайший срок</span><span>${staff ? 'Оценка' : 'Стоимость'}</span><span>Ответственный</span><span>Приоритет</span><span>Обновлена</span>${staff ? '<span>Действия</span>' : ''}</div>`;
  const ticketTabs = staff ? `<div class="task-scope-tabs bitrix-role-tabs ticket-nav-tabs" role="group" aria-label="Разделы заявок">
    <button class="${state.owner !== 'mine' ? 'active' : ''}" id="tab-t-all">${icon('ticket', 14)}Все заявки <span>${owned.length}</span></button>
    <button class="" id="tab-t-queue">${icon('queue', 14)}Очередь обработки (SLA) <span class="accent">${state.queue.length}</span></button>
    <button class="${state.owner === 'mine' ? 'active' : ''}" id="tab-t-mine">${icon('check', 14)}Мои заявки <span>${state.tickets.filter(t => t.assignee_id === state.user.id && !['done', 'closed'].includes(t.status)).length}</span></button>
  </div>` : '';
  const bulkBarHtml = staff && state.selectedTickets.size > 0 ? `
    <div class="bulk-action-bar" id="bulk-action-bar">
      <div class="bulk-info">
        <span>Выбрано заявок: <strong>${state.selectedTickets.size}</strong></span>
      </div>
      <div class="bulk-actions">
        <label class="bulk-assignee-label">
          <span class="visually-hidden">Назначить исполнителя</span>
          <select id="bulk-assignee-select" class="field small">
            <option value="">Назначить исполнителя...</option>
            ${state.staff.filter(s => s.role !== 'customer').map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}
          </select>
        </label>
        <button type="button" class="button small primary" id="bulk-assignee-apply">Назначить</button>
        <div class="bulk-divider"></div>
        <button type="button" class="button small" data-bulk-status="working">В работу</button>
        <button type="button" class="button small" data-bulk-status="waiting">Ожидает заказчика</button>
        <button type="button" class="button small" data-bulk-status="closed">Закрыть</button>
        <div class="bulk-divider"></div>
        <button type="button" class="button small" id="bulk-cancel">Отменить выбор</button>
      </div>
    </div>
  ` : '';
  shell(staff ? 'Заявки клиентов' : 'Мои заявки', staff ? `<button class="button primary bitrix-btn-top" id="tickets-new-btn">${icon('plus', 15)}<span>Новая заявка</span></button>` : '', `${ticketTabs}${staff ? '' : waitingPanel()}${portfolioOverview(owned)}<section class="panel ${staff ? '' : 'customer-ticket-list'}"><div class="toolbar"><div class="chips" role="group" aria-label="Фильтр по статусу">${chips}</div><div class="ticket-tools"><input class="field ticket-search" id="ticket-search" type="search" maxlength="100" aria-label="Поиск по заявкам" placeholder="Номер, тема, клиент" value="${esc(state.search)}">${prioritySelect}${ownerSelect}</div></div>${head}<div id="ticket-list"></div><div class="toolbar" style="border-top:1px solid var(--line-light);border-bottom:0;min-height:52px"><span class="muted" id="ticket-count"></span><span class="kbd-hint"><kbd>J</kbd><kbd>K</kbd> по строкам · <kbd>Enter</kbd> открыть</span></div></section>${bulkBarHtml}`, { kicker: staff ? (dispatcher ? 'Все клиенты' : 'Назначенные мне и команде') : 'Личный кабинет' });
  const updateList = () => {
    const query = state.search.trim().toLocaleLowerCase('ru-RU');
    const prio = state.priorityFilter || 'all';
    const prioFiltered = visible.filter(t => prio === 'all' || (t.priority || 'normal') === prio);
    const matches = query ? prioFiltered.filter(t => [t.id, t.title, t.description, t.customer_name, t.customer_company, t.assignee_name, statusNames[t.status], priorityNames[t.priority || 'normal']].some(value => String(value || '').toLocaleLowerCase('ru-RU').includes(query))) : prioFiltered;
    document.querySelector('#ticket-count').textContent = `Показано ${matches.length} из ${owned.length}`;
    document.querySelector('#ticket-list').innerHTML = matches.map(ticketRow).join('') || (query ? '<div class="empty"><strong>Ничего не найдено</strong>Попробуйте другой запрос или фильтр.</div>' : '<div class="empty"><strong>Заявок пока нет</strong>Создайте новую заявку или выберите другой фильтр.</div>');
    document.querySelectorAll('#ticket-list [data-ticket]').forEach(el => el.onclick = () => openTicket(Number(el.dataset.ticket)));
  };
  const ownerFilter = document.querySelector('#owner-filter');
  if (ownerFilter) { ownerFilter.value = state.owner; ownerFilter.onchange = e => { state.owner = e.target.value; renderTickets(); }; }
  const prioFilterEl = document.querySelector('#priority-filter');
  if (prioFilterEl) { prioFilterEl.value = state.priorityFilter || 'all'; prioFilterEl.onchange = e => { state.priorityFilter = e.target.value; updateList(); }; }
  document.querySelector('#ticket-search').oninput = e => { state.search = e.target.value; updateList(); };
  updateList();
  document.querySelector('#tickets-new-btn')?.addEventListener('click', () => setView('new'));
  document.querySelector('#tab-t-all')?.addEventListener('click', () => { state.owner = 'all'; renderTickets(); });
  document.querySelector('#tab-t-queue')?.addEventListener('click', () => setView('queue'));
  document.querySelector('#tab-t-mine')?.addEventListener('click', () => { state.owner = 'mine'; renderTickets(); });
  document.querySelectorAll('[data-waiting-ticket]').forEach(el => el.onclick = () => openTicket(Number(el.dataset.waitingTicket)));
  bindWaitingBulk();
  document.querySelectorAll('[data-status-filter],[data-overview-filter]').forEach(button => button.onclick = () => { const key = button.dataset.statusFilter || button.dataset.overviewFilter; state.filter = state.filter === key && button.dataset.overviewFilter ? 'all' : key; renderTickets(); });
  document.querySelectorAll('[data-ticket-select]').forEach(cb => {
    cb.onchange = e => {
      e.stopPropagation();
      const tid = Number(cb.dataset.ticketSelect);
      if (cb.checked) state.selectedTickets.add(tid);
      else state.selectedTickets.delete(tid);
      renderTickets();
    };
  });
  document.querySelector('#tickets-select-all')?.addEventListener('change', e => {
    e.stopPropagation();
    const checked = e.target.checked;
    visible.forEach(t => {
      if (checked) state.selectedTickets.add(t.id);
      else state.selectedTickets.delete(t.id);
    });
    renderTickets();
  });
  document.querySelector('#bulk-cancel')?.addEventListener('click', () => {
    state.selectedTickets.clear();
    renderTickets();
  });
  document.querySelector('#bulk-assignee-apply')?.addEventListener('click', async () => {
    const uid = Number(document.querySelector('#bulk-assignee-select').value);
    if (!uid) return toast('Выберите исполнителя', 'error');
    try {
      const res = await api('/tickets/bulk', {
        method: 'POST',
        body: JSON.stringify({
          ticket_ids: [...state.selectedTickets],
          action: 'assignee',
          assignee_id: uid
        })
      });
      toast(`Назначен исполнитель для ${res.updated.length} заявок`);
      state.selectedTickets.clear();
      await reload();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
  document.querySelectorAll('[data-bulk-status]').forEach(btn => {
    btn.onclick = async () => {
      const status = btn.dataset.bulkStatus;
      try {
        const res = await api('/tickets/bulk', {
          method: 'POST',
          body: JSON.stringify({
            ticket_ids: [...state.selectedTickets],
            action: 'status',
            status
          })
        });
        toast(`Статус обновлён для ${res.updated.length} заявок`);
        state.selectedTickets.clear();
        await reload();
      } catch (err) {
        toast(err.message, 'error');
      }
    };
  });
  document.querySelectorAll('[data-claim-ticket]').forEach(btn => {
    btn.onclick = e => {
      e.stopPropagation();
      claimTicket(Number(btn.dataset.claimTicket));
    };
  });
}
function renderQueue() {
  const dispatcher = isDispatcher();
  const scoped = state.queue.filter(item => !dispatcher || state.queueScope !== 'mine' || item.assignee_id === state.user.id);
  const items = scoped.map(item => { const sla = queueItemSla(item); return { ...item, sla, group: item.overdue || sla?.tone === 'late' ? 'late' : item.priority <= 1 ? 'urgent' : item.priority === 2 ? 'active' : 'waiting' }; });
  const groupNames = [['late', 'Просрочено'], ['urgent', 'Срочно'], ['active', 'В работе'], ['waiting', 'Ждём заказчика']];
  const count = key => items.filter(i => i.group === key).length;
  const unassigned = items.filter(i => !i.assignee_id).length;
  const late = count('late');
  const stat = (key, label, value, hint, cls = '') => `<button type="button" class="stat ${cls} ${state.queueGroup === key ? 'active' : ''}" data-queue-group="${key}" aria-pressed="${state.queueGroup === key}"><span class="stat-label">${label}</span><strong>${value}</strong><small>${hint}</small></button>`;
  const stats = `<div class="stats">${stat('late', 'Просрочено по SLA', late, late ? 'Ответить или оценить в первую очередь' : 'Все сроки соблюдены', late ? 'alert' : '')}${stat('urgent', 'Срочно', count('urgent'), 'Назначить или ответить')}${stat('unassigned', 'Без ответственного', unassigned, 'Нужно назначить исполнителя')}${stat('waiting', 'Ждём заказчика', count('waiting'), 'Решения по оценке и ответы')}</div>`;
  const source = state.queueSource || 'all';
  const byGroup = items.filter(i => !state.queueGroup || (state.queueGroup === 'unassigned' ? !i.assignee_id : i.group === state.queueGroup));
  const visible = byGroup.filter(i => source === 'all' || i.source === source);
  const ordered = groupNames.flatMap(([key]) => visible.filter(i => i.group === key));
  const focus = ordered[0];
  const row = item => {
    const chat = item.source === 'chat';
    const ticket = !chat && state.tickets.find(t => t.id === item.id);
    const chatInfo = chat && state.chats.find(c => c.id === item.id);
    const sub = chat ? (chatInfo?.last_message ? `«${chatInfo.last_message}»` : item.customer_name) : [item.customer_name, ticket?.customer_company].filter(Boolean).join(' · ');
    return `<button class="qrow ${item === focus ? 'focused' : ''}" data-source="${item.source}" data-record="${item.id}"><span class="qico ${chat ? 'chat' : ''}">${icon(chat ? 'chat' : 'ticket')}</span><span class="qtext"><strong>${chat ? 'Чат · ' + esc(item.customer_name) : '№' + item.id + ' · ' + esc(item.title)}</strong><small>${esc(sub)} · ${date(item.updated_at)}</small></span><span class="qsla">${slaTag(item.sla)}</span><span class="qact ${item.priority < 3 ? 'actionable' : ''}">${esc(item.next_action)} →</span>${avatarOf(item.assignee_id, item.assignee_name)}</button>`;
  };
  const list = groupNames.map(([key, label]) => { const rows = visible.filter(i => i.group === key); return rows.length ? `<div class="queue-group ${key === 'late' ? 'late' : ''}">${label} · ${rows.length}</div>${rows.map(row).join('')}` : ''; }).join('');
  const sourceChip = (key, label) => `<button type="button" class="chip ${source === key ? 'active' : ''}" data-queue-source="${key}" aria-pressed="${source === key}">${label} <i>${key === 'all' ? byGroup.length : byGroup.filter(i => i.source === key).length}</i></button>`;
  const focusCard = focus ? `<section class="focus-panel"><span class="focus-overline">Следующее действие · ${focus.source === 'chat' ? 'общий чат' : 'заявка №' + focus.id}</span><h2>${esc(focus.source === 'chat' ? focus.customer_name : focus.title)}</h2><p>${esc(focus.next_action)}${focus.sla ? ` · ${esc(focus.sla.text)}` : ''}</p><div class="focus-facts"><div><span>Заказчик</span><strong>${esc(focus.customer_name)}</strong></div><div><span>Ответственный</span><strong>${esc(focus.assignee_name || 'Не назначен')}</strong></div></div><div class="focus-actions"><button class="button on-dark" id="focus-queue">Открыть ${focus.source === 'chat' ? 'чат' : 'заявку'}</button></div></section>` : '';
  const scope = dispatcher ? `<div class="seg" role="group" aria-label="Чья очередь"><button type="button" data-scope="all" class="${state.queueScope !== 'mine' ? 'active' : ''}" aria-pressed="${state.queueScope !== 'mine'}">Вся команда</button><button type="button" data-scope="mine" class="${state.queueScope === 'mine' ? 'active' : ''}" aria-pressed="${state.queueScope === 'mine'}">Мои задачи</button></div>` : '';
  const needs = items.filter(i => i.priority < 3).length;
  const today = new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
  const lead = items.length ? `${needs} ${plural(needs, ['задача ждёт', 'задачи ждут', 'задач ждут'])} действия${late ? `, ${late} ${plural(late, ['просрочена', 'просрочены', 'просрочено'])} по SLA` : ''}` : 'Новых обращений пока нет';
  const empty = state.queueGroup || source !== 'all' ? '<div class="empty"><strong>Здесь пусто</strong>Сбросьте фильтр, чтобы увидеть всю очередь.</div>' : '<div class="empty"><strong>Очередь пуста</strong>Новых обращений пока нет.</div>';
  shell('Рабочая очередь', scope, `${stats}<div class="workspace-grid"><section class="panel"><div class="toolbar"><div class="toolbar-title"><strong>Очередь действий</strong><span class="kbd-hint"><kbd>J</kbd><kbd>K</kbd> по строкам · <kbd>Enter</kbd> открыть</span></div><div class="chips" role="group" aria-label="Тип обращений">${sourceChip('all', 'Все')}${sourceChip('ticket', 'Заявки')}${sourceChip('chat', 'Чаты')}</div></div>${list || empty}</section><div class="context-stack">${focusCard}${workloadPanel()}${recentActivity()}</div></div>`, { kicker: today.charAt(0).toUpperCase() + today.slice(1), lead });
  document.querySelector('#focus-queue')?.addEventListener('click', () => focus.source === 'chat' ? openChat(focus.id) : openTicket(focus.id));
  document.querySelectorAll('.qrow').forEach(el => el.onclick = () => el.dataset.source === 'chat' ? openChat(Number(el.dataset.record)) : openTicket(Number(el.dataset.record)));
  document.querySelectorAll('[data-queue-group]').forEach(el => el.onclick = () => { state.queueGroup = state.queueGroup === el.dataset.queueGroup ? null : el.dataset.queueGroup; renderQueue(); });
  document.querySelectorAll('[data-queue-source]').forEach(el => el.onclick = () => { state.queueSource = el.dataset.queueSource; renderQueue(); });
  document.querySelectorAll('[data-scope]').forEach(el => el.onclick = () => { state.queueScope = el.dataset.scope; renderQueue(); });
}
function notificationGroups(notifications, taskEvents, tickets, chats) {
  const labels = {assignment:'Назначение',mention:'Вас упомянули',review:'Результат на проверке',change:'Изменения в задаче',new_ticket:'Создана заявка',new_chat:'Создан чат',message:'Новое сообщение',estimate:'Оценка трудозатрат',estimate_decision:'Решение по оценке',extra_hours:'Дополнительные часы',extra_hours_decision:'Решение по часам',status:'Изменение статуса',acceptance:'Приёмка работы',decline:'Отказ от работы',attachment:'Добавлен файл',meeting_summary:'Итоги встречи',budget:'Лимит сопровождения',owner_help:'Нужна помощь с согласованием',reminder:'Напоминание',customer_silent:'Ожидание ответа',rating:'Оценка качества'};
  const events = [...notifications, ...taskEvents.filter(e=>e.entity==='tasks').map(e=>({...e,target:'task',kind:e.event_kind,text:labels[e.event_kind]||'Обновление задачи'}))];
  const groups = new Map();
  events.forEach(event => {
    const target = event.target || 'ticket';
    const id = target === 'task' ? event.entity_id : target === 'chat' ? event.chat_id : event.ticket_id;
    const key = `${target}-${id}`;
    if (!groups.has(key)) {
      const record = (target === 'chat' ? chats : tickets).find(r=>Number(r.id)===Number(id));
      groups.set(key, {key, id, target, title:target==='task' ? event.title || `Задача №${id}` : target==='chat' ? record?.customer_name || `Общий чат №${id}` : record?.title || `Заявка №${id}`, context:target==='ticket' ? record?.customer_company || record?.customer_name || '' : '', status:target==='ticket' ? record?.status : '', events:[], unread:0});
    }
    const group = groups.get(key);
    group.events.push({...event, label:labels[event.kind] || 'Обновление'});
    if (!event.read_at) group.unread++;
  });
  return [...groups.values()].map(group=>{
    group.events.sort((a,b)=>b.created_at.localeCompare(a.created_at)||Number(b.id)-Number(a.id));
    group.latest = group.events[0].created_at;
    return group;
  }).sort((a,b)=>b.latest.localeCompare(a.latest)||a.key.localeCompare(b.key));
}
function renderNotifications() {
  const staff = state.user.role !== 'customer';
  const groups = notificationGroups(state.notifications, staff ? state.teamWorkspace?.events || [] : [], state.tickets, state.chats);
  const filter = state.notificationFilter || 'all';
  const expanded = state.notificationExpanded || (state.notificationExpanded = new Set());
  const unread = groups.reduce((sum,g)=>sum+g.unread,0);
  const visible = groups.filter(g=>filter==='all'||filter==='unread'&&g.unread||g.target===filter);
  const types = {ticket:['Заявка','ticket','Открыть заявку'],task:['Задача','check','Открыть задачу'],chat:['Общий чат','chat','Открыть чат']};
  const eventRow = event => `<li class="notice-event ${event.read_at?'':'is-new'}"><span class="notice-event-dot" aria-hidden="true"></span><div><div class="notice-event-top"><strong>${esc(event.label)}</strong>${!event.read_at?'<span class="notice-new-label">Новое</span>':''}</div>${event.text !== event.label ? `<p>${esc(event.text)}</p>` : ''}<time datetime="${esc(event.created_at)}">${date(event.created_at)}</time></div></li>`;
  const card = group => {
    const [label, glyph, action] = types[group.target];
    const preview = group.events.find(e=>!e.read_at)||group.events[0];
    const rest = group.events.filter(e=>e!==preview);
    return `<article class="panel notice-group ${group.unread?'has-unread':''}" aria-labelledby="notice-title-${group.key}"><header class="notice-group-head"><span class="notice-object-icon">${icon(glyph,20)}</span><div class="notice-object"><div class="notice-object-meta"><span>${label}${group.target==='chat'?'':` №${group.id}`}</span>${group.status?`<span class="badge ${esc(group.status)}">${statusNames[group.status]||esc(group.status)}</span>`:''}</div><h3 id="notice-title-${group.key}">${esc(group.title)}</h3>${group.context?`<p>${esc(group.context)}</p>`:''}</div>${group.unread?`<span class="notice-unread-count">${group.unread} ${plural(group.unread,['новое','новых','новых'])}</span>`:`<span class="notice-read-label">${icon('check',14)}Просмотрено</span>`}</header><div class="notice-group-body"><ol class="notice-timeline">${eventRow(preview)}</ol>${rest.length?`<details class="notice-history" data-notice-history="${group.key}" ${expanded.has(group.key)?'open':''}><summary>Ещё ${rest.length} ${plural(rest.length,['событие','события','событий'])}<span>История ${group.target==='chat'?'диалога':group.target==='task'?'задачи':'заявки'}</span></summary><ol class="notice-timeline">${rest.map(eventRow).join('')}</ol></details>`:''}</div><footer class="notice-group-footer"><span>${group.events.length} ${plural(group.events.length,['событие','события','событий'])} в группе</span><button class="button small" data-notice-open="${group.key}" aria-label="${action}: ${esc(group.title)}">${action}${icon('chevron',14)}</button></footer></article>`;
  };
  const section = (title, hint, items, id) => items.length ? `<section class="notice-section" aria-labelledby="${id}"><header class="notice-section-head"><div><h2 id="${id}">${title}<span>${items.length} ${plural(items.length,['группа','группы','групп'])}</span></h2><p>${hint}</p></div></header><div class="notice-groups">${items.map(card).join('')}</div></section>` : '';
  const filters = [['all','Все'],['unread','Непрочитанные'],['ticket','Заявки'],...(staff?[['task','Задачи']]:[]),['chat','Чаты']].map(([key,label])=>{const count=groups.filter(g=>key==='all'||key==='unread'&&g.unread||g.target===key).length;return `<button type="button" class="chip ${filter===key?'active':''}" data-notice-filter="${key}" aria-pressed="${filter===key}">${label}<span>${count}</span></button>`;}).join('');
  const content = section('Непрочитанное','События одной заявки, задачи или чата собраны вместе.',visible.filter(g=>g.unread),'notice-new') + section('Ранее просмотрено','История обновлений, к которой можно вернуться.',visible.filter(g=>!g.unread),'notice-read');
  const pushAction=pushSupported()&&!state.pushEnabled&&Notification.permission!=='denied'?`<button class="button" id="enable-push">${icon('bell',16)}Уведомления на телефон</button>`:'';
  shell('Уведомления',pushAction,`<div class="notification-center"><div class="notice-overview"><span class="notice-overview-icon">${icon(unread?'bell':'check',22)}</span><div><strong>${unread?`${unread} ${plural(unread,['новое событие','новых события','новых событий'])}`:'Всё просмотрено'}</strong><p>${unread?`В ${groups.filter(g=>g.unread).length} ${plural(groups.filter(g=>g.unread).length,['группе','группах','группах'])}. Откройте объект, чтобы разобраться в контексте.`:'Новые события появятся здесь. История остаётся ниже.'}</p></div></div><div class="notice-filters" role="group" aria-label="Фильтр уведомлений">${filters}</div>${content||`<div class="panel empty notice-empty">${icon('bell',28)}<strong>${groups.length?'Здесь пока нет событий':'Уведомлений пока нет'}</strong><p>${filter==='unread'?'Все уведомления просмотрены.':'Выберите другой раздел или дождитесь новых обновлений.'}</p>${filter!=='all'?'<button class="button" data-notice-filter="all">Показать все</button>':''}</div>`}</div>`,{kicker:'Центр событий',lead:'Заявки, задачи и диалоги — каждое обновление на своём месте.'});
  document.querySelectorAll('[data-notice-filter]').forEach(button=>button.onclick=()=>{state.notificationFilter=button.dataset.noticeFilter;renderNotifications();document.querySelector(`[data-notice-filter="${state.notificationFilter}"]`)?.focus({preventScroll:true});});
  document.querySelectorAll('[data-notice-history]').forEach(details=>details.ontoggle=()=>{if(details.open)expanded.add(details.dataset.noticeHistory);else expanded.delete(details.dataset.noticeHistory);});
  document.querySelectorAll('[data-notice-open]').forEach(button=>button.onclick=async()=>{
    const group=groups.find(g=>g.key===button.dataset.noticeOpen);
    button.disabled=true;
    try {
      if(group.target==='task'){await TasksUI.open(Number(group.id));return;}
      await Promise.all(group.events.filter(e=>!e.read_at).map(e=>api(`/${group.target==='chat'?'chat-notifications':'notifications'}/${e.id}/read`,{method:'POST'})));
      await refresh();
      if(group.target==='chat')await openChat(Number(group.id));else await openTicket(Number(group.id));
    } catch(error){showError(error);button.disabled=false;}
  });
  document.querySelector('#enable-push')?.addEventListener('click',async e=>{e.target.disabled=true;try{await enablePush();toast('Уведомления включены');renderNotifications();}catch(error){toast(error.message,'error');e.target.disabled=false;}});
}
function mountAssigneeFilter(select,serviceType){
  if(!select||document.querySelector('#assignee-specialty'))return;
  const suggested={development:'programmer',new_development:'programmer',integration:'integrator',support:'devops',maintenance:'support'}[serviceType];
  const control=document.createElement('label');control.textContent='Специализация исполнителя';
  control.innerHTML+=`<select class="field" id="assignee-specialty"><option value="">Вся команда</option>${Object.entries(teamRoleNames).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select>`;
  const label=select.closest("label");if(label)label.before(control);else select.before(control);
  const filter=control.querySelector('select');
  const paint=()=>{const current=select.value;const people=state.staff.filter(p=>!filter.value||p.team_role===filter.value).sort((a,b)=>state.tickets.filter(t=>t.assignee_id===a.id&&!['closed','done'].includes(t.status)).length-state.tickets.filter(t=>t.assignee_id===b.id&&!['closed','done'].includes(t.status)).length);select.innerHTML='<option value="">Назначить позже</option>'+people.map(p=>{const load=state.tickets.filter(t=>t.assignee_id===p.id&&!['closed','done'].includes(t.status)).length;return `<option value="${p.id}">${esc(staffLabel(p))} · ${load} в работе</option>`;}).join('');if(people.some(p=>String(p.id)===current))select.value=current;};
  filter.onchange=paint;
  if(!select.value&&suggested&&state.staff.some(p=>p.team_role===suggested))filter.value=suggested;
  paint();
  document.querySelector('#ticket-form [name="service_type"]')?.addEventListener('change',e=>{const role={development:'programmer',new_development:'programmer',integration:'integrator',support:'devops',maintenance:'support'}[e.target.value];filter.value=state.staff.some(p=>p.team_role===role)?role||'':'';paint();});
}
function renderNew() {
  const staff=state.user.role!=='customer';
  const dispatcher=state.user.role==='admin'||state.user.is_manager;
  const customerField=staff?`<label>Заказчик<select class="field" name="customer_id" required><option value="">Выберите заказчика</option>${state.customers.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.email)}</option>`).join('')}</select></label>`:'';
  const assigneeField=dispatcher?`<label>Ответственный<select class="field" name="assignee_id"><option value="">Назначить позже</option>${state.staff.map(s=>`<option value="${s.id}">${esc(staffLabel(s))}</option>`).join('')}</select></label>`:staff?'<p class="muted">Вы будете назначены ответственным за эту заявку.</p>':'';
  const estimateField=staff?`<details class="estimate-inline"><summary>Сразу приложить оценку</summary><p class="muted">Заказчику останется только согласовать часы — или отказаться, если заявка не нужна.${dispatcher?' Для оценки нужен ответственный.':''}</p><label>Плановые трудозатраты, часов<input class="field" name="effort_hours" type="number" min="0.25" max="1666" step="0.25"></label><label>Потрачено на оценку, минут<input class="field" name="assessment_minutes" type="number" min="1" max="100000" step="1"></label><label>Пояснение к оценке<textarea name="estimate_note" maxlength="3000" placeholder="Что входит в работу"></textarea></label></details>`:'';
  const help=staff?['Выберите заказчика, которому нужна помощь.','Опишите задачу его словами — он увидит текст в своём кабинете.','Приложите оценку — заказчик согласует её в один клик или откажется от заявки.']:['Коротко назовите задачу, чтобы её было легко найти.','Напишите, какой результат нужен и какие детали важны.','Команда оценит трудозатраты в часах; решение останется за вами.'];
  shell('Новая заявка','',`<button class="back" id="back">← К заявкам</button><div class="form-layout"><div class="panel content"><h2>${staff?'Создать заявку для заказчика':'Опишите задачу'}</h2>${staff&&!state.customers.length?'<div class="notice">Нет доступных заказчиков. Менеджер или администратор может создать заявку для любого зарегистрированного заказчика.</div>':''}<form class="form" id="ticket-form">${staff?`<div class="template-bar"><label>Шаблон<select class="field" id="template-select"><option value="">Без шаблона</option></select></label><div class="row"><button type="button" class="button" id="template-save">Сохранить как шаблон</button><button type="button" class="button" id="template-delete" hidden>Удалить шаблон</button></div></div>`:''}${customerField}<label>Тема<input class="field" name="title" required minlength="3" maxlength="140" placeholder="Коротко о задаче"></label><div id="kb-suggest-box" class="kb-suggest-box" style="display:none"></div><label>Описание<textarea name="description" data-draft="new-ticket" required minlength="5" maxlength="10000" placeholder="Что нужно сделать? Укажите важные детали."></textarea></label>${assigneeField}${estimateField}<button class="button primary" ${staff&&!state.customers.length?'disabled':''}>Создать заявку</button></form></div><div class="form-help"><span>ПОДСКАЗКА</span><h2>Чтобы быстрее начать</h2>${help.map((item,index)=>`<div class="help-step"><b>${String(index+1).padStart(2,'0')}</b><p>${item}</p></div>`).join('')}</div></div>`);
  document.querySelector('#ticket-form [name="title"]').parentElement.insertAdjacentHTML('beforebegin',`<label>Тип задачи<select class="field" name="service_type">${Object.entries(serviceNames).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><label id="service-topic-field" hidden>Другая тема<input class="field" name="service_topic" maxlength="80" placeholder="Укажите свою тему" disabled></label><label>Приоритет<select class="field" name="priority"><option value="low">Низкий (плановые задачи, консультации)</option><option value="normal" selected>Обычный (стандартный рабочий режим)</option><option value="high">Высокий (важный сбой, блок процессов)</option><option value="urgent">Критический (авария, полная остановка)</option></select></label>`);
  if(dispatcher){
    const details=document.createElement('details');details.className='estimate-inline';details.innerHTML='<summary>Добавить или подключить клиента</summary><div class="new-customer-invitation"></div>';
    document.querySelector('#ticket-form').before(details);
    const host=details.querySelector('.new-customer-invitation');
    mountCustomerInvitation(host,null,access=>{
      const select=document.querySelector('#ticket-form [name="customer_id"]');
      select.innerHTML='<option value="">Выберите заказчика</option>'+state.customers.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.email)}</option>`).join('');select.value=access.customer_id;
      select.dispatchEvent(new Event('change'));
      document.querySelector('#ticket-form button.primary').disabled=false;
    });
  }
  document.querySelector('#ticket-form [name="service_type"]').onchange=e=>{
    const other=e.target.value==='other';
    const topic=document.querySelector('#ticket-form [name="service_topic"]');
    document.querySelector('#service-topic-field').hidden=!other;
    topic.disabled=!other;topic.required=other;
    topic.setCustomValidity('');
    document.querySelector('#ticket-form [name="description"]').placeholder=serviceHints[e.target.value];
    document.querySelector('.form-help > h2').textContent=serviceNames[e.target.value];
  };
  document.querySelector('#ticket-form [name="service_topic"]').oninput=e=>e.target.setCustomValidity(e.target.value.trim()?'':'Укажите свою тему');
  document.querySelector('#ticket-form [name="service_type"]').dispatchEvent(new Event('change'));
  const titleInput = document.querySelector('#ticket-form [name="title"]');
  const suggestBox = document.querySelector('#kb-suggest-box');
  let suggestTimer = null;
  titleInput?.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    const q = titleInput.value.trim();
    if (q.length < 3) {
      if (suggestBox) { suggestBox.style.display = 'none'; suggestBox.innerHTML = ''; }
      return;
    }
    suggestTimer = setTimeout(async () => {
      try {
        const list = await api(`/kb/suggest?q=${encodeURIComponent(q)}`);
        if (!list || !list.length) {
          if (suggestBox) { suggestBox.style.display = 'none'; suggestBox.innerHTML = ''; }
          return;
        }
        if (suggestBox) {
          suggestBox.innerHTML = `
            <div class="kb-suggest-header">
              <span>Возможно, ответ уже есть в базе знаний:</span>
            </div>
            <div class="kb-suggest-list">
              ${list.map(s => `
                <button type="button" class="kb-suggest-item" data-suggest-id="${s.id}">
                  <strong>${esc(s.title)}</strong>
                  <small>${esc(s.category_name)} · ${esc(s.snippet)}</small>
                </button>
              `).join('')}
            </div>
          `;
          suggestBox.style.display = 'block';
          suggestBox.querySelectorAll('[data-suggest-id]').forEach(btn => {
            btn.onclick = async () => {
              await readKbArticle(Number(btn.dataset.suggestId));
            };
          });
        }
      } catch (e) {
        if (suggestBox) suggestBox.style.display = 'none';
      }
    }, 250);
  });
  document.querySelector('#ticket-form > button.primary').insertAdjacentHTML('beforebegin',`<label id="visibility-field" ${!staff&&!state.organizations.length?'hidden':''}>Кому видна заявка<select class="field" name="visibility"><option value="organization">Всей компании</option><option value="private">Только автору</option></select></label><label>Файлы к заявке<input class="field" name="files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.zip"><small>До 10 МБ на файл. Скриншот можно вставить в описание через Ctrl + V.</small></label><div class="composer-files" id="ticket-draft-files" aria-live="polite"></div>`);
  if(!staff&&state.organizations[0]?.members.some(m=>m.user_id===state.user.id&&m.role==='viewer')){document.querySelector('#visibility-field').hidden=true;document.querySelector('#visibility-field select').value='private';}
  if(staff)document.querySelector('#ticket-form [name="customer_id"]').onchange=e=>{const member=state.organizations.some(o=>o.members.some(m=>m.user_id===Number(e.target.value)));document.querySelector('#visibility-field').hidden=!member;document.querySelector('#visibility-field select').value=member?'organization':'private';};
  document.querySelector('#back').onclick=()=>setView('tickets');
  if(staff)bindTicketTemplates(document.querySelector('#ticket-form'));
  bindTicketDraft(document.querySelector('#ticket-form'));
  { const form = document.querySelector('#ticket-form'); bindFilePicker(form, form.elements.description, form.elements.files, form.querySelector('#ticket-draft-files')); }
  mountAssigneeFilter(document.querySelector('#ticket-form [name="assignee_id"]'),document.querySelector('#ticket-form [name="service_type"]')?.value);
  document.querySelector('#ticket-form').onsubmit=async e=>{e.preventDefault();const files=[...e.target.elements.files.files];const data=Object.fromEntries(new FormData(e.target));data.service_type=ticketServiceType(e.target);delete data.service_topic;delete data.files;if(document.querySelector('#visibility-field').hidden)data.visibility='private';if(staff){data.customer_id=Number(data.customer_id);if(dispatcher)data.assignee_id=data.assignee_id?Number(data.assignee_id):null;const effort=data.effort_hours;delete data.effort_hours;if(effort){if(dispatcher&&!data.assignee_id){showError(new Error('Чтобы сразу отправить оценку, выберите ответственного'));return;}data.effort_minutes=Math.round(Number(effort)*60);data.assessment_minutes=data.assessment_minutes?Number(data.assessment_minutes):null;}else{delete data.assessment_minutes;delete data.estimate_note;}}e.target.querySelector('button.primary').disabled=true;try{const ticket=await api('/tickets',{method:'POST',body:JSON.stringify(data)});clearDraft('new-ticket');clearDraft('ticket-form');const failed=[];for(const file of files){try{await upload(`/tickets/${ticket.id}/attachments`,file);}catch(error){failed.push(file.name);}}await refresh();await openTicket(ticket.id);if(failed.length){state.error=`Заявка создана, но файлы не загрузились: ${failed.join(', ')}. Прикрепите их в карточке.`;render();}}catch(error){showError(error);}};
}
function bindTicketTemplates(form) {
  const select = form.querySelector('#template-select');
  const save = form.querySelector('#template-save');
  const remove = form.querySelector('#template-delete');
  const current = () => (state.templates || []).find(t => t.id === Number(select.value));
  const fill = (selected = '') => {
    select.innerHTML = `<option value="">Без шаблона</option>${(state.templates || []).map(t => `<option value="${t.id}">${esc(t.name)}${t.effort_minutes ? ` · ${hours(t.effort_minutes)}` : ''}</option>`).join('')}`;
    select.value = selected;
    remove.hidden = !select.value;
  };
  const load = async selected => { try { state.templates = await api('/ticket-templates'); fill(selected); } catch (error) { showError(error); } };
  select.onchange = () => {
    remove.hidden = !select.value; remove.textContent = 'Удалить шаблон';
    const t = current();
    if (!t) return;
    form.elements.service_type.value = t.service_type.startsWith('custom:') ? 'other' : t.service_type;
    form.elements.service_topic.value = t.service_type.startsWith('custom:') ? t.service_type.slice(7) : '';
    form.elements.service_type.dispatchEvent(new Event('change'));
    if (t.priority && form.elements.priority) form.elements.priority.value = t.priority;
    form.elements.title.value = t.title;
    form.elements.description.value = t.description;
    form.elements.effort_hours.value = t.effort_minutes ? t.effort_minutes / 60 : '';
    form.elements.estimate_note.value = t.estimate_note || '';
    form.querySelector('.estimate-inline').open = Boolean(t.effort_minutes);
  };
  save.onclick = async () => {
    const title = form.elements.title.value.trim(), description = form.elements.description.value.trim();
      if (form.elements.service_type.value === 'other' && !form.elements.service_topic.value.trim()) { showError(new Error('Укажите свою тему')); form.elements.service_topic.focus(); return; }
    if (title.length < 3 || description.length < 5) { showError(new Error('Заполните тему и описание — из них получится шаблон')); return; }
    const effort = form.elements.effort_hours.value;
    save.disabled = true;
    try {
        const created = await api('/ticket-templates', { method: 'POST', body: JSON.stringify({ name: title.slice(0, 80), title, description, service_type: ticketServiceType(form), effort_minutes: effort ? Math.round(Number(effort) * 60) : null, estimate_note: form.elements.estimate_note.value }) });
      await load(String(created.id));
      toast('Шаблон сохранён — он появится в списке у всей команды');
    } catch (error) { showError(error); } finally { save.disabled = false; }
  };
  remove.onclick = async () => {
    if (remove.textContent !== 'Точно удалить?') { remove.textContent = 'Точно удалить?'; return; }
    try { await api(`/ticket-templates/${select.value}`, { method: 'DELETE' }); remove.textContent = 'Удалить шаблон'; await load(''); toast('Шаблон удалён'); } catch (error) { showError(error); }
  };
  load('');
}
async function openTicket(id) {if(state.view!=='detail'||state.current?.ticket?.id!==id)delayedLoading(`Заявка №${id}`,'detail');try{const sameTicket=state.current?.ticket?.id===id;state.current=await api(`/tickets/${id}`);if(!sameTicket)state.detailTab='messages';state.current.assignee_profile=state.user.role!=='customer'&&state.current.ticket.assignee_id?await api(`/staff/${state.current.ticket.assignee_id}/profile`).catch(()=>null):null;state.gitLinks=await api(`/tickets/${id}/git-links`).catch(()=>[]);state.view='detail';state.error='';render();}catch(error){showError(error);}}
/* ---------- Переписка: ответы, прочтение, итоги встреч ---------- */
const viewerSide = () => state.user.role === 'customer' ? 'customer' : 'team';
const messageSide = m => m.author_role === 'customer' ? 'customer' : 'team';
const meetingKindNames = { call: 'созвона', meeting: 'встречи', chat: 'переписки', other: 'обсуждения' };
function messageHtml(m, { header, extra = '', canReply = false }) {
  const side = messageSide(m);
  const quote = m.reply_to_id ? `<button type="button" class="reply-quote" data-jump="${m.reply_to_id}" aria-label="Перейти к исходному сообщению"><strong>${esc(m.reply_author_name || 'Сообщение')}</strong><span>${esc(m.reply_body || 'Сообщение удалено')}</span></button>` : '';
  const reply = canReply ? `<button type="button" class="msg-reply" data-reply="${m.id}" aria-label="Ответить на сообщение ${esc(m.author_name)}">${icon('reply', 14)}<span>Ответить</span></button>` : '';
  const toTask = state.user?.role !== 'customer' ? `<button type="button" class="msg-to-task" data-chat-to-task="${m.id}" title="Создать задачу из этого сообщения">${icon('check', 13)}<span>В задачу</span></button>` : '';
  const status = side === viewerSide() ? '<span class="msg-status" aria-live="off"></span>' : '';
  return `<div class="message ${m.author_id === state.user.id ? 'mine' : ''}" id="msg-${m.id}" data-msg="${m.id}" data-side="${side}"><div class="msg-head"><small>${header}</small><div class="msg-actions-wrap">${toTask}${reply}</div></div>${quote}<div class="msg-body">${esc(m.body)}</div>${extra}<div class="msg-foot">${status}</div></div>`;
}
function summaryCard(s) {
  return `<article class="meeting-card" aria-label="Итоги ${meetingKindNames[s.kind] || 'встречи'}"><div class="meeting-head"><span class="meeting-ico">${icon('users', 16)}</span><div><strong>Итоги ${meetingKindNames[s.kind] || 'встречи'} · ${new Date(s.occurred_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</strong><small>${esc(s.author_name)}</small></div></div><span class="eyebrow">О чём договорились</span><p>${esc(s.client_summary)}</p>${s.client_next_steps ? `<span class="eyebrow">Что дальше</span><p>${esc(s.client_next_steps)}</p>` : ''}</article>`;
}
function timeline(messages, summaries, renderMessage) {
  return [...messages.map(m => ({ at: m.created_at, kind: 'message', item: m })), ...(summaries || []).map(s => ({ at: s.shared_at, kind: 'summary', item: s }))]
    .sort((a, b) => a.at.localeCompare(b.at))
    .map(entry => entry.kind === 'summary' ? { at: entry.at, html: summaryCard(entry.item) } : { at: entry.at, html: renderMessage(entry.item) });
}
function paintReadTicks(readState) {
  if (!readState) return;
  const side = viewerSide();
  const otherRead = side === 'customer' ? readState.team_read_id : readState.customer_read_id;
  const who = side === 'customer' ? 'командой' : state.view === 'chat' && state.currentChat?.chat.organization_id ? 'участником компании' : 'заказчиком';
  document.querySelectorAll(`.message[data-side="${side}"] .msg-status`).forEach(el => {
    const read = Number(el.closest('.message').dataset.msg) <= (otherRead || 0);
    el.className = `msg-status ${read ? 'read' : ''}`;
    el.innerHTML = `${icon(read ? 'checks' : 'check', 14)}<span>${read ? `Прочитано ${who}` : 'Отправлено'}</span>`;
  });
}
function replyBar(kind, record) {
  const r = state.replyTo;
  if (!r || r.kind !== kind || r.record !== record) return '<div class="reply-bar" id="reply-bar" hidden></div>';
  return `<div class="reply-bar" id="reply-bar">${icon('reply', 15)}<div><strong>Ответ ${esc(r.author)}</strong><span>${esc(r.body.slice(0, 160))}</span></div><button type="button" class="icon-btn" id="cancel-reply" aria-label="Отменить ответ">×</button></div>`;
}
function bindConversation(kind, record, messages, readState) {
  paintReadTicks(readState);
  document.querySelectorAll('[data-jump]').forEach(el => el.onclick = () => {
    const target = document.querySelector(`#msg-${el.dataset.jump}`);
    if (!target) return toast('Исходное сообщение не найдено', 'error');
    target.scrollIntoView({ block: 'center', behavior: reduceMotion() ? 'auto' : 'smooth' });
    target.classList.remove('flash'); void target.offsetWidth; target.classList.add('flash');
  });
  document.querySelectorAll('[data-reply]').forEach(el => el.onclick = () => {
    const m = messages.find(x => x.id === Number(el.dataset.reply));
    if (!m) return;
    state.replyTo = { kind, record, id: m.id, author: m.author_name, body: m.body };
    const bar = document.querySelector('#reply-bar');
    if (bar) { bar.outerHTML = replyBar(kind, record); bindReplyCancel(kind, record); }
    document.querySelector(kind === 'ticket' ? '#message-body' : '#chat-body')?.focus();
  });
  document.querySelectorAll('[data-chat-to-task]').forEach(el => el.onclick = () => {
    const m = messages.find(x => x.id === Number(el.dataset.chatToTask));
    if (!m) return;
    const ticketId = kind === 'ticket' ? record : (state.current?.ticket?.id || null);
    const customerId = state.currentChat?.chat?.customer_id || state.current?.ticket?.customer_id || null;
    const title = m.body.slice(0, 80).replace(/\n.*/s, '');
    TasksUI.quickCreate({
      title: title || 'Задача из переписки',
      description: m.body,
      ticket_id: ticketId,
      customer_id: customerId
    });
  });
  bindReplyCancel(kind, record);
  markRead(kind, record, messages);
}
function bindReplyCancel(kind, record) {
  document.querySelector('#cancel-reply')?.addEventListener('click', () => { state.replyTo = null; document.querySelector('#reply-bar').outerHTML = replyBar(kind, record); });
}
const replyToId = (kind, record) => state.replyTo?.kind === kind && state.replyTo.record === record ? state.replyTo.id : null;
state.readSent = {};
async function markRead(kind, record, messages) {
  const top = messages.reduce((max, m) => Math.max(max, m.id), 0);
  const key = `${kind}-${record}`;
  if (document.visibilityState !== 'visible' || (state.readSent[key] || 0) >= top && state.readSent[key] !== undefined) return;
  state.readSent[key] = top;
  try {
    const reads = await api(`/${kind === 'ticket' ? 'tickets' : 'chats'}/${record}/read`, { method: 'POST', body: JSON.stringify({}) });
    const current = kind === 'ticket' ? state.current : state.currentChat;
    if (current) current.read_state = reads;
    loadNotifications().catch(() => {});
  } catch {}
}
function ticketProgress(ticket, estimates) {
  if (ticket.declined) return `<div class="notice">Заказчик отказался от заявки — работа не выполнялась.</div>`;
  const estimate = estimates[0];
  const step = ticket.status === 'closed' ? 4 : ticket.status === 'done' ? 4 : ['working', 'waiting'].includes(ticket.status) ? 3 : ['approved','pending'].includes(estimate?.state) ? 2 : estimate ? 1 : 0;
  const steps = ['Создана', 'Оценка', 'Согласование', 'В работе', 'Приёмка'];
  return `<section class="ticket-progress" aria-label="Этапы заявки"><p class="current-stage">Этап ${step+1} из ${steps.length}: <strong>${ticket.status==='closed'?'Работа завершена':steps[step]}</strong></p><ol>${steps.map((label, index) => `<li class="${index < step ? 'passed' : index === step ? 'current' : ''}" ${index === step ? 'aria-current="step"' : ''}><span class="step-dot">${index < step ? '✓' : index + 1}</span><span class="step-label">${label}</span></li>`).join('')}</ol></section>`;
}
function renderCsat(t, staff) {
  if (!['done', 'closed'].includes(t.status) || t.declined) return '';
  if (!staff && !t.rating && t.status !== 'closed') return '';
  if (!staff) {
    if (t.rating) {
      return `<div class="csat-box"><div class="csat-title">Ваша оценка работы</div><div class="csat-stars">${[1,2,3,4,5].map(s=>`<span class="csat-star active">${s<=t.rating?'★':'☆'}</span>`).join('')}</div>${t.rating_comment?`<p style="margin:6px 0;font-size:13px">«${esc(t.rating_comment)}»</p>`:''}<div class="csat-result">✓ Спасибо за вашу оценку!</div></div>`;
    }
    return `<div class="csat-box" id="csat-form-wrap"><div class="csat-title">Оцените качество решения задачи</div><div class="csat-subtitle">Поставьте оценку от 1 до 5 звёзд</div><div class="csat-stars" id="csat-star-picker">${[1,2,3,4,5].map(s=>`<button type="button" class="csat-star" data-val="${s}" aria-label="${s} из 5" aria-pressed="false">★</button>`).join('')}</div><textarea class="csat-comment" id="csat-comment" placeholder="Что вам понравилось или что улучшить? (необязательно)" maxlength="2000"></textarea><div><button class="button primary" id="csat-submit" disabled>Отправить оценку</button></div></div>`;
  }
  if (t.rating) {
    return `<section class="panel content" style="margin-top:18px"><div class="row"><h2>Оценка заказчика</h2><span class="csat-result">★ ${t.rating} из 5</span></div>${t.rating_comment?`<p style="margin:8px 0 4px;font-size:13.5px">«${esc(t.rating_comment)}»</p>`:''}<small class="muted">Оценено ${date(t.rated_at)}</small></section>`;
  }
  return '';
}

function attachCsatHandlers(t) {
  let selectedStar = 0;
  const picker = document.querySelector('#csat-star-picker');
  if (!picker) return;
  const stars = picker.querySelectorAll('.csat-star');
  stars.forEach(star => {
    star.onmouseenter = () => {
      const val = Number(star.dataset.val);
      stars.forEach(s => s.classList.toggle('active', Number(s.dataset.val) <= val));
    };
    star.onclick = () => {
      selectedStar = Number(star.dataset.val);
      document.querySelector('#csat-submit').disabled = false;
      stars.forEach(s => s.setAttribute('aria-pressed', String(s === star)));
      stars.forEach(s => s.classList.toggle('active', Number(s.dataset.val) <= selectedStar));
    };
  });
  picker.onmouseleave = () => {
    stars.forEach(s => s.classList.toggle('active', Number(s.dataset.val) <= selectedStar));
  };
  document.querySelector('#csat-submit')?.addEventListener('click', async () => {
    if (!selectedStar) return;
    const comment = document.querySelector('#csat-comment')?.value || '';
    document.querySelector('#csat-submit').disabled = true;
    try {
      await api(`/tickets/${t.id}/rate`, {
        method: 'POST',
        body: JSON.stringify({ rating: selectedStar, comment })
      });
      await refresh();
      await openTicket(t.id);
    } catch(err) {
      showError(err);
      const submit = document.querySelector('#csat-submit');
      if (submit) submit.disabled = false;
    }
  });
}

async function loadInternalNotes(ticketId) {
  if (state.user.role === 'customer') return;
  try {
    state.internalNotes = await api(`/tickets/${ticketId}/internal-notes`);
    renderInternalNotes(ticketId);
  } catch(e) {}
}

function renderInternalNotes(ticketId) {
  const container = document.querySelector('#internal-notes-container');
  if (!container) return;
  const notes = state.internalNotes || [];
  container.innerHTML = `
    <section class="internal-notes-panel">
      <div class="internal-notes-header">
        <div class="internal-notes-title">
          <span>Заметки команды</span>
          <span class="internal-notes-badge">${notes.length}</span>
        </div>
        <small class="muted">Видны только сотрудникам</small>
      </div>
      <div class="internal-notes-notice">
        <span>Закрытый служебный блок: заказчик не видит эту переписку.</span>
      </div>
      <div class="internal-notes-list">
        ${notes.map(n => `
          <div class="internal-note-item">
            <div class="internal-note-meta">
              <strong>${esc(n.author_name)} (${n.author_role === 'admin' ? 'Администратор' : 'Сотрудник'})</strong>
              <span>${date(n.created_at)}</span>
            </div>
            <div>${esc(n.body)}</div>
          </div>
        `).join('') || '<div class="muted" style="font-size:12.5px;padding:4px 0">Заметок пока нет. Зафиксируйте технические детали, пароли или ход задачи.</div>'}
      </div>
      <form class="internal-note-form" id="internal-note-form">
        <textarea id="internal-note-body" data-draft="note-${ticketId}" name="body" required placeholder="Добавить внутреннюю заметку..." maxlength="5000"></textarea>
        <button class="button">Записать</button>
      </form>
    </section>
  `;
  bindDrafts(container);
  container.querySelector('#internal-note-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = new FormData(e.target).get('body');
    const btn = e.target.querySelector('button');
    btn.disabled = true;
    try {
      await api(`/tickets/${ticketId}/internal-notes`, {
        method: 'POST',
        body: JSON.stringify({ body })
      });
      clearDraft(`note-${ticketId}`);
      await loadInternalNotes(ticketId);
    } catch(err) {
      showError(err);
    }
  });
}

async function renderCannedTrigger() {
  const composer = document.querySelector('#message-form');
  if (!composer) return;
  if (!state.cannedResponses.length) {
    try {
      state.cannedResponses = await api('/canned-responses');
    } catch(e) {}
  }
  const buttonWrap = document.createElement('div');
  buttonWrap.className = 'canned-wrap';
  buttonWrap.innerHTML = `
    <button type="button" class="button small canned-btn" id="canned-toggle">Быстрые ответы</button>
    <div class="canned-menu" id="canned-menu" hidden>
      ${renderCannedMenuItems()}
    </div>
  `;
  (composer.querySelector('.composer-bar')||composer).prepend(buttonWrap);
  const toggle = buttonWrap.querySelector('#canned-toggle');
  const menu = buttonWrap.querySelector('#canned-menu');
  toggle.onclick = (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
  };
  document.addEventListener('click', () => { if (menu) menu.hidden = true; });
  menu.onclick = (e) => e.stopPropagation();
  menu.querySelectorAll('[data-canned-body]').forEach(item => {
    item.onclick = () => {
      const textarea = composer.querySelector('textarea');
      if (textarea) {
        textarea.value = (textarea.value ? textarea.value + '\n\n' : '') + item.dataset.cannedBody;
        textarea.focus();
      }
      menu.hidden = true;
    };
  });
}

function renderCannedMenuItems() {
  const groups = {};
  for (const c of state.cannedResponses) {
    groups[c.category] = groups[c.category] || [];
    groups[c.category].push(c);
  }
  return Object.entries(groups).map(([cat, list]) => `
    <div class="canned-category">${esc(cat)}</div>
    ${list.map(item => `
      <button type="button" class="canned-item" data-canned-body="${esc(item.body)}">
        <strong>${esc(item.title)}</strong>
        <small>${esc(item.body)}</small>
      </button>
    `).join('')}
  `).join('');
}

function ticketChatComposer(t, viewer, staff) {
  return viewer ? '<div class="content muted">У вас доступ только к просмотру заявки.</div>' : t.status !== 'closed' ? `<form class="composer" id="message-form">${replyBar('ticket', t.id)}<label class="visually-hidden" for="message-body">Сообщение</label><textarea id="message-body" data-draft="ticket-${t.id}" name="body" required maxlength="10000" placeholder="${staff ? 'Напишите сообщение заказчику…' : 'Напишите сообщение команде…'}"></textarea><div class="composer-files" id="message-files" aria-live="polite"></div><div class="composer-bar"><label class="upload-label">${icon('paperclip', 15)}Файлы<input name="files" type="file" multiple accept="${ALLOWED_FILES.join(',')}"></label><span class="composer-hint">Ctrl + Enter — отправить</span><button class="button primary">Отправить</button></div></form>` : '<div class="content muted">Заявка закрыта. Переписка доступна для чтения.</div>';
}
function bindTicketChatComposer(t, reload) {
  bindCtrlEnter('#message-form');
  const messageForm = document.querySelector('#message-form');
  if (messageForm) bindFilePicker(messageForm, messageForm.elements.body, messageForm.elements.files, messageForm.querySelector('#message-files'), document.querySelector('.conversation'));
  messageForm?.addEventListener('submit', async e => {
    e.preventDefault(); const form = e.target;
    if (!form.elements.body.value.trim() && !form.elements.files.files.length) return showError(new Error('Введите сообщение или прикрепите файл'));
    const button = form.querySelector('button.primary'); button.disabled = true;
    try {
      // Remove each successful upload from the queue so a retry cannot duplicate it.
      for (const file of [...form.elements.files.files]) {
        await upload(`/tickets/${t.id}/attachments`, file);
        form.querySelector('[data-remove-file="0"]').click();
      }
      const body = form.elements.body.value.trim();
      if (body) await api(`/tickets/${t.id}/messages`, { method: 'POST', body: JSON.stringify({ body, request_id: form.dataset.requestId ||= crypto.randomUUID(), reply_to_id: replyToId('ticket', t.id) }) });
      clearDraft(`ticket-${t.id}`); state.replyTo = null; state.justSent = true; await refresh(); await reload();
    } catch (error) { showError(error); } finally { button.disabled = false; }
  });
}

function renderDetail() {
  const { ticket: t, messages, events, estimates = [] } = state.current;
  const staff = state.user.role !== 'customer';
  const dispatcher = isDispatcher();
  const viewer = (staff && t.can_write === false) || !staff && t.visibility === 'organization' && state.organizations.some(o => o.id === t.organization_id && o.members.some(m => m.user_id === state.user.id && m.role === 'viewer'));
  const canStatus = staff && t.status !== 'closed' && (state.user.role === 'admin' || t.assignee_id === state.user.id);
  const late = ticketSla(t).filter(s => s.tone === 'late');
  const prioBadge = `<span class="badge priority-${esc(t.priority || 'normal')}">${esc(priorityNames[t.priority] || 'Обычный')}</span>`;
  const badges = `<span class="badge ${esc(t.status)}">${statusNames[t.status]}</span>${prioBadge}${late.map(s => `<span class="sla late">${icon('clock', 13)}${s.label} ${s.label === 'Ответ' ? 'просрочен' : 'просрочена'} на ${formatDuration(-s.diff)}</span>`).join('')}<span class="badge">${esc(serviceLabel(t.service_type))}</span>`;
  const lead = [`№${t.id}`, staff ? (t.customer_company || t.customer_name) : '', `создана ${date(t.created_at)}`, t.organization_id ? (t.visibility === 'organization' ? 'видна всей компании' : 'личная заявка') : ''].filter(Boolean).map(esc).join(' · ');
  const canClaim = staff && t.assignee_id !== state.user.id && !['done', 'closed'].includes(t.status);
  const claimBtn = canClaim ? `<button type="button" class="button small btn-claim-ticket" data-claim-ticket="${t.id}" title="Взять заявку себе">${icon('user', 13)} Взять себе</button>` : '';
  const assignee = dispatcher ? `<div class="assignee-wrap"><select id="assignee" aria-label="Ответственный"><option value="">Без ответственного</option>${state.staff.map(x => `<option value="${x.id}">${esc(staffLabel(x))}</option>`).join('')}</select>${claimBtn}</div>` : `<div class="assignee-wrap"><span class="meta-person">${t.assignee_id ? avatarOf(t.assignee_id, t.assignee_name) : ''}${esc(t.assignee_name || 'Не назначен')}</span>${claimBtn}</div>`;
  const canReply = !viewer && t.status !== 'closed';
  const chat = timeline(messages, state.current.meeting_summaries, m => messageHtml(m, { header: `${esc(m.author_name)} · ${date(m.created_at)}`, canReply })).map(x => x.html).join('') || `<div class="empty">${canReply ? 'Сообщений пока нет. Напишите первое сообщение.' : 'Сообщений пока нет. Здесь появится история переписки.'}</div>`;
  const eventText = e => e.kind==='priority'?'приоритет изменён на «'+(priorityNames[e.new_value]||e.new_value)+'»':e.kind==='service_budget'?'лимит сопровождения изменён: '+(e.new_value==='unlimited'?'без ограничения':hours(Number(e.new_value))):e.kind==='owner_help'?'отправлен запрос менеджеру на восстановление владельца':e.kind === 'reopen' ? 'заявка возвращена в работу: ' + esc(e.new_value) : e.kind === 'status' ? 'статус изменён на «' + esc(statusNames[e.new_value] || e.new_value) + '»' : e.kind === 'acceptance' ? (e.new_value === 'accepted' ? 'работа принята' : 'работа возвращена на доработку') : e.kind === 'decline' ? 'заказчик отказался от заявки' : 'ответственный изменён';
  const history = events.map(e => `<li><div>${esc(e.actor_name)}: ${eventText(e)}<small>${date(e.created_at)}</small></div></li>`).join('');
  const person = state.current.assignee_profile;
  if (!staff && state.detailTab === 'notes') state.detailTab = 'messages';
  const tab = state.detailTab || 'messages';
  const tabButton = (id, label, count, ic = '') => `<button type="button" role="tab" class="tab ${tab === id ? 'active' : ''}" aria-selected="${tab === id}" data-detail-tab="${id}">${ic}${label}${count !== undefined ? ` <i>${count}</i>` : ''}</button>`;
  const composer = ticketChatComposer(t, viewer, staff);
  const priorityControl = staff ? `<select id="ticket-priority" class="field compact" aria-label="Приоритет">${Object.entries(priorityNames).map(([k,v])=>`<option value="${k}" ${(t.priority||'normal')===k?'selected':''}>${v}</option>`).join('')}</select>` : `<span class="badge priority-${esc(t.priority || 'normal')}">${esc(priorityNames[t.priority] || 'Обычный')}</span>`;
  const participants = state.current.participants || [];
  const participantsList = participants.length ? `<div class="participants-list" style="margin-top:12px;border-top:1px solid var(--line-light);padding-top:10px;"><span class="eyebrow" style="margin-bottom:6px;display:block;">Участники команды (${participants.length})</span>${participants.map(p=>`<div class="team-person org-person" style="padding:4px 0;"><span class="org-member-identity">${avatar(p,'small')}<span><strong>${esc(p.name)}</strong><small>${esc([(p.functions||[teamRoleNames[p.team_role]]).filter(Boolean).join(', '), p.job_title].filter(Boolean).join(' · ') || 'Специалист')}</small></span></span></div>`).join('')}</div>` : '';
  const meta = `<dl class="meta"><dt>Заказчик</dt><dd>${esc(t.customer_name)}${staff && t.customer_company ? `<small>${esc(t.customer_company)}</small>` : ''}</dd><dt>Ответственный</dt><dd>${staff ? assignee : (t.assignee_name ? `<span class="meta-person">${avatarOf(t.assignee_id, t.assignee_name)}${esc(t.assignee_name)}</span>` : '<span class="muted">Назначается поддержкой</span>')}</dd><dt>Приоритет</dt><dd>${priorityControl}</dd><dt>Тип задачи</dt><dd>${esc(serviceLabel(t.service_type))}</dd>${t.organization_id ? `<dt>Видимость</dt><dd>${t.visibility === 'organization' ? 'Вся компания' : 'Личная заявка'}</dd>` : ''}<dt>Создана</dt><dd>${date(t.created_at)}</dd>${t.created_by_name ? `<dt>Создал</dt><dd>${esc(t.created_by_name)}</dd>` : ''}</dl>`;
  const personCard = person ? `<section class="panel content assigned-person"><div class="person-heading">${avatar(person)}<div><span class="eyebrow">${staff ? 'Ответственный' : 'Ваш специалист по заявке'}</span><h2>${esc(person.name)}</h2><p>${esc([(person.function_names||[teamRoleNames[person.team_role]]).filter(Boolean).join(", "),person.job_title].filter(Boolean).join(' · ') || 'Специалист команды')}</p></div></div>${person.bio ? `<p class="person-bio">${esc(person.bio)}</p>` : ''}${participantsList}</section>` : (participants.length ? `<section class="panel content assigned-person">${participantsList}</section>` : '');
  const body = `${ticketProgress(t, estimates)}<div class="detail-grid"><div>${t.next_step ? `<div class="next-step"><span>Следующий шаг</span><strong>${esc(t.next_step)}</strong></div>` : ''}<section class="panel content"><h2>Описание задачи</h2><p class="description">${esc(t.description)}</p>${state.current.linked_chat ? `<button class="button linked-chat" id="linked-chat">${icon('chat', 16)}Обсуждение в общем чате</button>` : ''}</section><section class="panel conversation"><div class="tabs" role="tablist" aria-label="Обсуждение заявки">${tabButton('messages', 'Переписка', messages.length)}${staff ? tabButton('notes', 'Заметки команды', undefined, icon('lock', 14)) : ''}${tabButton('history', 'История', events.length)}</div><div class="tab-pane" data-pane="messages" ${tab !== 'messages' ? 'hidden' : ''}><div class="messages">${chat}</div>${composer}</div>${staff ? `<div class="tab-pane" data-pane="notes" ${tab !== 'notes' ? 'hidden' : ''}><div id="internal-notes-container"></div></div>` : ''}<div class="tab-pane" data-pane="history" ${tab !== 'history' ? 'hidden' : ''}>${history ? `<ol class="events">${history}</ol>` : '<div class="empty">В истории пока нет событий.</div>'}</div></section>${renderCsat(t, staff)}</div><div><section class="panel content"><h2>Детали</h2>${meta}</section>${personCard}</div></div>`;
  const topClaimAction = canClaim ? `<button type="button" class="button primary btn-claim-ticket" data-claim-ticket="${t.id}">${icon('user', 14)}<span>Взять себе</span></button>` : '';
  shell(t.title, topClaimAction, body, { crumbs: `<button class="crumb-link" id="back">Заявки</button><span aria-hidden="true">/</span><span>№${t.id}</span>`, badges, lead });
  document.querySelectorAll('[data-claim-ticket]').forEach(btn => {
    btn.onclick = () => claimTicket(Number(btn.dataset.claimTicket));
  });
  renderEstimate(t, estimates, staff);
  renderAcceptance(t, staff);
  renderOperations();
  renderTicketActions(t, estimates, canStatus);
  const descriptionPanel = document.querySelector('.description').parentElement;
  const ticketFiles = state.current.attachments || [];
  descriptionPanel.insertAdjacentHTML('beforeend', `<div class="description-files">${ticketFiles.map(attachmentLink).join('')}</div>${canReply ? `<label class="upload-label">${icon('paperclip', 15)}Прикрепить файлы к описанию<input id="description-files" type="file" multiple accept="${ALLOWED_FILES.join(',')}"></label><small class="muted description-file-hint">Можно выбрать или перетащить файлы; скриншот — вставить через Ctrl + V.</small>` : ''}`);
  if (canReply) {
    const addDescriptionFiles = async files => {
      const input = document.querySelector('#description-files'); input.disabled = true;
      let uploaded = false;
      try { for (const file of files) { await upload(`/tickets/${t.id}/attachments`, file); uploaded = true; } await openTicket(t.id); }
      catch (error) { if (uploaded) await openTicket(t.id); showError(error); }
      finally { input.disabled = false; }
    };
    descriptionPanel.tabIndex = 0;
    descriptionPanel.addEventListener('paste', e => { const files = [...(e.clipboardData?.files || [])]; if (files.length) { e.preventDefault(); const ok = checkFiles(files); if (ok.length) addDescriptionFiles(ok); } });
    document.querySelector('#description-files').addEventListener('change', e => { const files = checkFiles([...e.target.files]); if (files.length) addDescriptionFiles(files); });
    bindDropzone(descriptionPanel, 'Отпустите, чтобы прикрепить к описанию', addDescriptionFiles);
  }
  foldTicketContext();
  if(t.visibility==='organization'&&t.has_available_owner===false){
    document.querySelector('.detail-grid>div:first-child').insertAdjacentHTML('afterbegin',`<section class="notice" role="status"><p>У компании нет владельца с действующим доступом. Согласование общих работ недоступно.</p>${dispatcher?'<button class="button" id="resolve-owner">Назначить владельца или восстановить доступ</button>':'<p>Менеджер поможет назначить владельца или восстановить его доступ.</p><button class="button" id="request-owner-help">Попросить менеджера восстановить согласование</button>'}</section>`);
    document.querySelector('#request-owner-help')?.addEventListener('click',async e=>{e.target.disabled=true;try{const result=await api(`/tickets/${t.id}/owner-help`,{method:'POST'});toast(result.message);e.target.textContent='Запрос передан менеджеру';}catch(error){showError(error);}});
    document.querySelector('#resolve-owner')?.addEventListener('click',()=>{setView('organizations');document.querySelector(`[data-org-card="${t.organization_id}"]`)?.scrollIntoView({block:'start'});});
  }
  if (dispatcher && t.status === 'closed') {
    document.querySelector('.detail-grid>div:last-child').insertAdjacentHTML('beforeend', `<section class="panel content"><h2>Вернуть заявку в работу</h2><p class="muted">Предыдущая приёмка останется в истории. Результат понадобится принять повторно.</p><form class="form" id="reopen-form"><label>Причина<textarea name="reason" required minlength="3" maxlength="2000"></textarea></label><button class="button">Вернуть в работу</button></form></section>`);
    document.querySelector('#reopen-form').onsubmit = async e => { e.preventDefault(); const button=e.target.querySelector('button');button.disabled=true;try{await api(`/tickets/${t.id}/reopen`,{method:'POST',body:JSON.stringify({reason:e.target.elements.reason.value})});toast('Заявка возвращена в работу');await refresh();await openTicket(t.id);}catch(error){toast(error.message,'error');button.disabled=false;} };
  }
  if(staff&&t.can_write!==false&&state.teamWorkspace?.my_permissions.includes('tasks')){document.querySelector('.detail-grid>div:last-child').insertAdjacentHTML('beforeend',`<section class="panel content"><h2>Работа по заявке</h2><button class="button" id="ticket-create-task">Создать связанную задачу</button></section>`);document.querySelector('#ticket-create-task').onclick=()=>TasksUI.quickCreate({title:t.title,description:t.description.slice(0,5000),customer_id:t.customer_id,customer_name:t.customer_name,ticket_id:t.id,owner_id:state.user.id});}
  document.querySelector('#linked-chat')?.addEventListener('click', () => openChat(state.current.linked_chat.chat_id));
  document.querySelector('#back').onclick = () => setView('tickets');
  if (dispatcher) {document.querySelector('#assignee').value = t.assignee_id || '';mountAssigneeFilter(document.querySelector('#assignee'),t.service_type);}
  document.querySelectorAll('[data-detail-tab]').forEach(button => button.onclick = () => { state.detailTab = button.dataset.detailTab; document.querySelectorAll('[data-detail-tab]').forEach(x => { const on = x === button; x.classList.toggle('active', on); x.setAttribute('aria-selected', String(on)); }); document.querySelectorAll('.tab-pane').forEach(pane => pane.hidden = pane.dataset.pane !== state.detailTab); });
  const box = document.querySelector('.tab-pane[data-pane="messages"] .messages');
  if (box) box.scrollTop = box.scrollHeight;
  popLastMessage(box);
  document.querySelector('#assignee')?.addEventListener('change', async e => { try { await api(`/tickets/${t.id}/assignee`, { method: 'PATCH', body: JSON.stringify({ assignee_id: e.target.value ? Number(e.target.value) : null }) }); toast('Ответственный обновлён'); await refresh(); await openTicket(t.id); } catch (error) { showError(error); } });
  document.querySelector('#ticket-priority')?.addEventListener('change', async e => { try { await api(`/tickets/${t.id}/priority`, { method: 'PATCH', body: JSON.stringify({ priority: e.target.value }) }); toast('Приоритет обновлён'); await refresh(); await openTicket(t.id); } catch (error) { showError(error); } });
  bindTicketChatComposer(t, () => openTicket(t.id));
  if (staff) {
    loadInternalNotes(t.id);
    if (t.status !== 'closed') renderCannedTrigger();
  }

  attachCsatHandlers(t);
  bindConversation('ticket', t.id, messages, state.current.read_state);
  bindWorkspaceTabs();
}
function renderTicketActions(t, estimates, canStatus) {
  if (state.user.role === 'customer' || t.status === 'closed') return;
  const approved = estimates[0]?.state === 'approved';
  const assigned = t.assignee_id === state.user.id;
  const active = ['working', 'waiting'].includes(t.status);
  const button = (status, label, primary = false) => `<button type="button" class="button ${primary ? 'primary' : ''}" data-ticket-status="${status}">${label}</button>`;
  let hint = 'Сначала подготовьте оценку и получите одобрение заказчика. Затем можно начать работу.';
  let actions = '';
  if (t.status === 'new' && approved) {
    hint = 'Оценка согласована. Начните работу, затем внесите фактическое время и передайте результат на проверку.';
    if (canStatus) actions = button('working', 'Начать работу', true);
  } else if (active) {
    hint = t.pending_hour_request ? 'Дождитесь согласования дополнительных часов. После этого можно передать результат на проверку.' : 'Работа выполнена? Внесите фактическое время, затем отправьте результат на проверку. Заказчик примет работу и закроет заявку.';
    if (assigned) actions += '<button type="button" class="button" id="go-to-time">Внести фактическое время</button>';
    if (canStatus) {
      if (approved && !t.pending_hour_request) actions += button('done', 'Отправить на проверку', true);
      actions += t.status === 'waiting' ? button('working', 'Продолжить работу') : button('waiting', 'Ждать ответа заказчика');
    }
  } else if (t.status === 'done') {
    hint = 'Результат отправлен на проверку. Заказчик примет работу и закроет заявку или вернёт её на доработку.';
    if (canStatus) actions = button('working', 'Продолжить доработку');
  }
  if (!canStatus && !assigned) hint += ' Статусом и фактическим временем управляет ответственный сотрудник.';
  document.querySelector('.ticket-progress')?.insertAdjacentHTML('beforeend', `<div class="form"><p class="muted">Этапы меняются по мере выполнения действий: оценка → согласование → работа → приёмка.</p><p>${hint}</p>${actions ? `<div class="row" style="flex-wrap:wrap;gap:8px">${actions}</div>` : ''}</div>`);
  const focusTime = () => {
    document.querySelector('#actual-work')?.scrollIntoView({ block: 'start', behavior: reduceMotion() ? 'auto' : 'smooth' });
    document.querySelector('#time-entry-form [name="hours"]')?.focus({ preventScroll: true });
  };
  document.querySelector('#go-to-time')?.addEventListener('click', focusTime);
  document.querySelectorAll('[data-ticket-status]').forEach(button => button.onclick = async () => {
    const status = button.dataset.ticketStatus;
    if (status === 'done' && !t.actual_minutes) {
      toast('Перед отправкой на проверку внесите фактически потраченное время.', 'error');
      focusTime();
      return;
    }
    button.disabled = true;
    try {
      await api(`/tickets/${t.id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) });
      toast(status === 'done' ? 'Результат отправлен заказчику на проверку' : `Статус изменён: ${statusNames[status]}`);
      await refresh(); await openTicket(t.id);
    } catch (error) { showError(error); button.disabled = false; }
  });
}
function foldTicketContext(){
  document.querySelectorAll('.detail-grid section.panel').forEach(panel=>{
    const title=panel.querySelector('h2');if(!title||!['Сроки SLA','Файлы','Детали'].includes(title.textContent))return;
    const details=document.createElement('details');details.className='ticket-context';
    const summary=document.createElement('summary');summary.textContent=title.textContent;
    const body=document.createElement('div');body.className='ticket-context-body';title.remove();
    while(panel.firstChild)body.append(panel.firstChild);
    details.append(summary,body);panel.append(details);
    if(title.textContent==='Фактические трудозатраты'&&state.user.role!=='customer'&&state.current.ticket.assignee_id===state.user.id)details.open=true;
  });
}
function renderAcceptance(t, staff) {
  if (staff || t.status !== 'done') return;
  const host = document.querySelector('.detail-grid>div:first-child');
  if (!t.can_decide) {
    host.insertAdjacentHTML('afterbegin', `<section class="panel content acceptance-panel"><h2>Работа на проверке</h2><p class="muted">Принять общую работу или вернуть её на доработку может владелец компании.</p></section>`);
    return;
  }
  host.querySelector('.next-step')?.remove();
  host.insertAdjacentHTML('afterbegin', `<section class="panel content acceptance-panel needs-action"><div class="eyebrow">Ваше действие</div><h2>Работа готова — проверьте результат</h2><p>Если всё в порядке, примите работу, и заявка закроется. Если что-то нужно поправить, верните её с комментарием: команда продолжит работу.</p><div class="row acceptance-actions"><button class="button primary" id="accept-work">${icon('check', 16)}Принять работу</button><button class="button" id="return-work">Вернуть на доработку</button></div><form class="form" id="return-form" hidden><label>Что нужно доработать<textarea name="comment" data-draft="return-${t.id}" required minlength="3" maxlength="3000" placeholder="Например: заказы с сайта не попадают в CRM"></textarea></label><div class="row"><button class="button primary">Вернуть на доработку</button><button type="button" class="button" id="cancel-return">Отмена</button></div></form></section>`);
  bindDrafts(host);
  const send = async (data, message) => {
    try { await api(`/tickets/${t.id}/acceptance`, { method: 'POST', body: JSON.stringify(data) }); clearDraft(`return-${t.id}`); toast(message); await refresh(); await openTicket(t.id); }
    catch (error) { showError(error); }
  };
  document.querySelector('#accept-work').onclick = e => { e.currentTarget.disabled = true; send({ action: 'accept' }, 'Работа принята, заявка закрыта'); };
  document.querySelector('#return-work').onclick = () => { const form = document.querySelector('#return-form'); form.hidden = false; form.elements.comment.focus(); };
  document.querySelector('#cancel-return').onclick = () => { document.querySelector('#return-form').hidden = true; };
  document.querySelector('#return-form').onsubmit = e => { e.preventDefault(); e.target.querySelector('button.primary').disabled = true; send({ action: 'return', comment: e.target.elements.comment.value }, 'Заявка возвращена на доработку'); };
}
function renderEstimate(ticket, estimates, staff) {
  const latest = estimates[0];
  const isPm = isDispatcher();
  const legacy = latest && latest.effort_minutes === null && !latest.amount_rub;
  const canCreate = staff && (ticket.assignee_id === state.user.id || isPm) && ticket.status !== 'closed' && (!latest || legacy || ['rejected', 'revision_requested', 'pm_revision_requested'].includes(latest.state));
  const canDecide = !staff && ticket.can_decide && latest?.state === 'pending' && ticket.status !== 'closed';
  const isPmReview = isPm && latest?.state === 'pending_pm' && ticket.status !== 'closed';

  const history = staff ? estimates.map(e => {
    const perfH = hours(e.performer_effort_minutes || e.effort_minutes || 0);
    const pmH = e.pm_effort_minutes ? ` + PM: ${hours(e.pm_effort_minutes)}` : '';
    const sumRub = e.amount_rub ? ` · ${e.amount_rub.toLocaleString('ru-RU')} ₽` : '';
    return `<div class="estimate-version">
      <div class="row">
        <strong>Версия ${e.version} · Исполнитель: ${perfH}${pmH}${sumRub}</strong>
        <span class="badge">${estimateNames[e.state] || 'Требуется новая оценка'}</span>
      </div>
      <div class="muted">Оценил ${esc(e.author_name)} · ${date(e.created_at)} · на оценку: ${e.assessment_minutes || 0} мин.</div>
      ${e.note ? `<p><strong>Внутренняя заметка:</strong> ${esc(e.note)}</p>` : ''}
      ${e.client_note ? `<p><strong>Пояснение клиенту:</strong> ${esc(e.client_note)}</p>` : ''}
      ${e.customer_comment ? `<p><strong>Комментарий заказчика:</strong> ${esc(e.customer_comment)}</p>` : ''}
      ${e.proposed_amount_rub ? `<p><strong>Предложение заказчика:</strong> ${e.proposed_amount_rub.toLocaleString('ru-RU')} ₽</p>` : ''}
    </div>`;
  }).join('') : estimates.map(e => `
    <div class="estimate-version">
      <div class="row">
        <strong>Версия ${e.version} · ${(e.amount_rub || 0).toLocaleString('ru-RU')} ₽</strong>
        <span class="badge">${estimateNames[e.state] || e.state}</span>
      </div>
      <div class="muted">Оценка подготовлена · ${date(e.created_at)}</div>
      ${e.note ? `<p>${esc(e.note)}</p>` : ''}
      ${e.customer_comment ? `<p>Ваш комментарий: ${esc(e.customer_comment)}</p>` : ''}
      ${e.proposed_amount_rub ? `<p>Желаемый бюджет: ${e.proposed_amount_rub.toLocaleString('ru-RU')} ₽</p>` : ''}
    </div>
  `).join('');

  const rateRub = ticket.hourly_rate_rub || 3000;
  const perfHours = ((latest?.performer_effort_minutes || latest?.effort_minutes || 0) / 60);
  const pmReviewCard = isPmReview ? `
    <div class="pm-review-card" style="border: 2px solid var(--accent); border-radius: var(--radius); padding: 16px; margin: 16px 0; background: var(--surface-secondary);">
      <div class="eyebrow" style="color:var(--accent-ink);margin-bottom:6px">Проверка руководителем проектов (PM)</div>
      <h3 style="margin-top:0">Выставление оценки клиенту</h3>
      <p>Оценка исполнителя: <strong>${perfHours} ч</strong> (${Math.round(perfHours * rateRub).toLocaleString('ru-RU')} ₽ по ставке ${rateRub.toLocaleString('ru-RU')} ₽/ч).</p>
      <form class="form" id="pm-review-form">
        <div class="duration-inputs">
          <label>Часы PM / QA / риски
            <input class="field" type="number" id="pm-hours-input" name="pm_hours" min="0" max="500" step="0.25" value="0">
          </label>
          <label>Сумма клиенту, ₽ (ручная корректировка)
            <input class="field" type="number" id="pm-custom-amount" name="custom_amount_rub" min="0" step="100" placeholder="Автоматический расчёт">
          </label>
        </div>
        <p class="muted" id="pm-calc-preview">Итого клиенту: <strong>${Math.round(perfHours * rateRub).toLocaleString('ru-RU')} ₽</strong> (${perfHours} ч × ${rateRub.toLocaleString('ru-RU')} ₽/ч)</p>
        <label>Пояснение для клиента (клиент не видит часы и ставку)
          <textarea class="field" name="client_note" maxlength="3000" placeholder="Что входит в стоимость работы">${esc(latest?.client_note || latest?.note || '')}</textarea>
        </label>
        <div class="row">
          <button class="button primary" id="pm-send-estimate">Выставить клиенту</button>
          <button type="button" class="button" id="pm-reject-estimate">Вернуть исполнителю</button>
        </div>
      </form>
      <form class="form" id="pm-reject-form" hidden style="margin-top:12px; border-top: 1px solid var(--line); padding-top: 12px;">
        <label>Причина возврата на доработку
          <textarea class="field" name="reject_comment" required maxlength="3000" placeholder="Укажите, что нужно пересмотреть в оценке"></textarea>
        </label>
        <div class="row">
          <button class="button primary">Вернуть на доработку</button>
          <button type="button" class="button" id="pm-cancel-reject">Отмена</button>
        </div>
      </form>
    </div>
  ` : '';

  const pendingPmNotice = (staff && !isPm && latest?.state === 'pending_pm') ? `
    <div class="notice">Оценка (${hours(latest.performer_effort_minutes || latest.effort_minutes)}) передана на проверку руководителю проектов (PM). Клиент пока её не видит.</div>
  ` : '';
  const pmRevisionNotice = (staff && latest?.state === 'pm_revision_requested') ? `
    <div class="notice warning">PM запросил пересмотр оценки: ${esc(latest.customer_comment || '')}. Пожалуйста, внесите скорректированную оценку.</div>
  ` : '';

  const create = canCreate ? `
    <form class="form" id="estimate-form">
      <label>Плановые трудозатраты исполнителя, часов
        <input class="field" name="effort_hours" type="number" min="0.25" max="1666" step="0.25" required>
      </label>
      <label>Потрачено на оценку, минут
        <input class="field" name="minutes" type="number" min="1" max="100000" step="1" required>
      </label>
      <label>Пояснение к оценке
        <textarea name="note" maxlength="3000" placeholder="Что входит в работу"></textarea>
      </label>
      <button class="button primary">${isPm ? 'Создать оценку' : 'Отправить на проверку PM'}</button>
    </form>
  ` : '';

  const decide = canDecide ? `
    <div class="estimate-customer-offer" style="margin: 16px 0; padding: 16px; background: var(--surface-secondary); border-radius: var(--radius); border-left: 4px solid var(--accent);">
      <div style="font-size: 24px; font-weight: 700; color: var(--accent-ink);">${(latest.amount_rub || 0).toLocaleString('ru-RU')} ₽</div>
      ${latest.note ? `<p style="margin: 8px 0 0; color: var(--ink);">${esc(latest.note)}</p>` : ''}
    </div>
    <div class="row estimate-actions">
      <button class="button primary" id="approve-estimate">Согласовать стоимость</button>
      <button class="button" id="revise-estimate">Запросить корректировку</button>
      <button class="button" id="reject-estimate">Не согласен со стоимостью</button>
    </div>
    <form class="form" id="revision-form" hidden>
      <label>Желаемый бюджет, ₽ (необязательно)
        <input class="field" name="proposed_amount" type="number" min="0" step="500" placeholder="Например: 15000">
      </label>
      <label>Что скорректировать
        <textarea name="comment" required maxlength="3000" placeholder="Напишите ваши пожелания"></textarea>
      </label>
      <div class="row">
        <button class="button primary">Запросить корректировку</button>
        <button type="button" class="button" id="cancel-revision">Отмена</button>
      </div>
    </form>
  ` : '';

  const estimateMoney = staff && latest && billingOn() ? `
    <p class="notice">Тариф клиента: <strong>${rateRub.toLocaleString('ru-RU')} ₽/ч</strong>. Согласованная сумма: <strong>${(latest.amount_rub || 0).toLocaleString('ru-RU')} ₽</strong>.</p>
  ` : '';

  const decline = !staff && ticket.can_decline ? `<div class="decline-box"><p class="muted">Эту заявку создала команда. Если задача не нужна, откажитесь — заявка закроется без работы и оплаты.</p><button type="button" class="button" id="decline-ticket">Отменить задачу</button><form class="form" id="decline-form" hidden><label>Почему не нужна (необязательно)<textarea name="comment" maxlength="3000" placeholder="Например: уже решили своими силами"></textarea></label><div class="row"><button class="button primary">Отказаться от заявки</button><button type="button" class="button" id="cancel-decline">Отмена</button></div></form></div>` : '';

  const title = staff ? 'Оценка трудозатрат и стоимости' : 'Стоимость работ';
  const needsAction = canCreate || canDecide || isPmReview;
  const noEstimateText = staff ? 'Оценка ещё не подготовлена.' : 'Команда готовит расчёт стоимости.';

  document.querySelector('.detail-grid>div:first-child>.panel.content').insertAdjacentHTML('afterend', `
    <section class="panel content estimate-panel ${needsAction ? 'needs-action' : ''}">
      ${needsAction ? '<div class="eyebrow" style="color:var(--accent-ink);margin-bottom:6px">Ваше действие</div>' : ''}
      <h2>${title}</h2>
      ${legacy ? '<div class="notice">Старая оценка была указана в деньгах. Нужна новая оценка в часах.</div>' : ''}
      ${pendingPmNotice}
      ${pmRevisionNotice}
      ${pmReviewCard}
      ${latest ? history : `<p class="muted">${noEstimateText}</p>`}
      ${estimateMoney}
      ${create}
      ${decide}
      ${decline}
    </section>
  `);

  document.querySelector('#decline-ticket')?.addEventListener('click', () => {
    const form = document.querySelector('#decline-form');
    form.hidden = false;
    document.querySelector('#decline-ticket').hidden = true;
    form.elements.comment.focus();
  });
  document.querySelector('#cancel-decline')?.addEventListener('click', () => {
    document.querySelector('#decline-form').hidden = true;
    document.querySelector('#decline-ticket').hidden = false;
  });
  document.querySelector('#decline-form')?.addEventListener('submit', e => {
    e.preventDefault();
    e.target.querySelector('button.primary').disabled = true;
    update(`/tickets/${ticket.id}/decline`, { comment: e.target.elements.comment.value }, 'Заявка закрыта — команда получила уведомление');
  });

  const update = async (path, data, message) => {
    try {
      await api(path, { method: 'POST', body: JSON.stringify(data) });
      if (message) toast(message);
      await refresh();
      await openTicket(ticket.id);
    } catch (error) {
      showError(error);
    }
  };

  const updatePmPreview = () => {
    const pmH = Number(document.querySelector('#pm-hours-input')?.value || 0);
    const customAmt = document.querySelector('#pm-custom-amount')?.value;
    const totalH = perfHours + pmH;
    const calcAmt = Math.round(totalH * rateRub);
    const finalAmt = (customAmt !== '' && customAmt !== null && customAmt !== undefined) ? Number(customAmt) : calcAmt;
    const prev = document.querySelector('#pm-calc-preview');
    if (prev) prev.innerHTML = `Итого клиенту: <strong>${finalAmt.toLocaleString('ru-RU')} ₽</strong> (${totalH} ч × ${rateRub.toLocaleString('ru-RU')} ₽/ч)`;
  };
  document.querySelector('#pm-hours-input')?.addEventListener('input', updatePmPreview);
  document.querySelector('#pm-custom-amount')?.addEventListener('input', updatePmPreview);

  document.querySelector('#pm-review-form')?.addEventListener('submit', e => {
    e.preventDefault();
    const data = new FormData(e.target);
    const pmHours = Number(data.get('pm_hours') || 0);
    const custom = data.get('custom_amount_rub');
    update(`/tickets/${ticket.id}/estimates/${latest.id}/pm-review`, {
      action: 'send_to_customer',
      pm_effort_minutes: Math.round(pmHours * 60),
      custom_amount_rub: custom ? Number(custom) : null,
      client_note: data.get('client_note') || ''
    }, 'Оценка выставлена заказчику');
  });

  document.querySelector('#pm-reject-estimate')?.addEventListener('click', () => {
    const form = document.querySelector('#pm-reject-form');
    form.hidden = false;
    form.elements.reject_comment.focus();
  });
  document.querySelector('#pm-cancel-reject')?.addEventListener('click', () => {
    document.querySelector('#pm-reject-form').hidden = true;
  });
  document.querySelector('#pm-reject-form')?.addEventListener('submit', e => {
    e.preventDefault();
    const data = new FormData(e.target);
    update(`/tickets/${ticket.id}/estimates/${latest.id}/pm-review`, {
      action: 'reject_to_performer',
      comment: data.get('reject_comment') || ''
    }, 'Оценка возвращена исполнителю');
  });

  document.querySelector('#estimate-form')?.addEventListener('submit', e => {
    e.preventDefault();
    const data = new FormData(e.target);
    update(`/tickets/${ticket.id}/estimates`, {
      effort_minutes: Math.round(Number(data.get('effort_hours')) * 60),
      assessment_minutes: Number(data.get('minutes')),
      note: data.get('note')
    }, isPm ? 'Оценка создана' : 'Оценка отправлена на проверку PM');
  });

  document.querySelector('#approve-estimate')?.addEventListener('click', () => {
    update(`/tickets/${ticket.id}/estimates/decision`, {
      estimate_id: latest.id,
      action: 'approve'
    }, 'Стоимость согласована — команда приступает к работе');
  });

  document.querySelector('#reject-estimate')?.addEventListener('click', () => {
    update(`/tickets/${ticket.id}/estimates/decision`, {
      estimate_id: latest.id,
      action: 'reject'
    }, 'Оценка отклонена');
  });

  document.querySelector('#revise-estimate')?.addEventListener('click', () => {
    const form = document.querySelector('#revision-form');
    form.hidden = false;
    form.elements.comment.focus();
  });
  document.querySelector('#cancel-revision')?.addEventListener('click', () => {
    document.querySelector('#revision-form').hidden = true;
  });
  document.querySelector('#revision-form')?.addEventListener('submit', e => {
    e.preventDefault();
    const data = new FormData(e.target);
    const propAmt = data.get('proposed_amount');
    update(`/tickets/${ticket.id}/estimates/decision`, {
      estimate_id: latest.id,
      action: 'request_revision',
      comment: data.get('comment'),
      proposed_amount_rub: propAmt ? Number(propAmt) : null
    }, 'Запрос на корректировку отправлен');
  });
}

function renderOperations() {
  const { ticket: t, time_entries = [], hour_requests = [], attachments = [] } = state.current;
  const staff = state.user.role !== 'customer';
  const assigned = staff && t.assignee_id === state.user.id;
  const viewer = (staff && t.can_write === false) || !staff && t.visibility === 'organization' && state.organizations.some(o => o.id === t.organization_id && o.members.some(m => m.user_id === state.user.id && m.role === 'viewer'));
  const canDecide = !staff && t.can_decide;
  const remaining = Math.max(0, (t.approved_minutes || 0) - (t.actual_minutes || 0));
  const progress = t.approved_minutes ? Math.min(100, Math.round(t.actual_minutes / t.approved_minutes * 100)) : 0;
  const rateRub = t.hourly_rate_rub || 3000;
  const costRub = t.cost_rub || Math.round((t.approved_minutes || 0) / 60 * rateRub);
  const actBadge = t.act_invoice ? `<span style="margin: 0 10px; color: var(--line)">|</span><a href="/api/billing/invoices/${t.act_invoice.id}/print" target="_blank" rel="noopener noreferrer" class="billing-doc-pill act" title="Открыть печатную форму акта">Акт №${esc(t.act_invoice.number)} ✓</a>` : '';

  const requests = staff ? hour_requests.map(r => {
    if (r.state === 'pending_pm') {
      if (isDispatcher()) {
        const perfH = (r.minutes / 60);
        return `<div class="hours-request needs-action" style="border: 2px solid var(--accent); border-radius: var(--radius); padding: 12px; margin: 10px 0;">
          <div class="row"><strong>Запрос доп. часов: +${hours(r.minutes)}</strong><span class="badge">Ждёт решения PM</span></div>
          <p><strong>Причина исполнителя:</strong> ${esc(r.reason)}</p>
          <small>${esc(r.author_name)} · ${date(r.created_at)}</small>
          <form class="form pm-hour-decision-form" data-request-id="${r.id}" style="margin-top: 10px;">
            <div class="duration-inputs">
              <label>Часов исполнителю
                <input class="field" type="number" name="approved_hours" min="0" max="500" step="0.25" value="${perfH}" required>
              </label>
              <label class="check-row" style="margin-top:24px">
                <input type="checkbox" name="bill_customer" class="bill-customer-check">Выставить заказчику
              </label>
            </div>
            <div class="bill-customer-fields" hidden style="margin-top:8px">
              <label>Сумма заказчику, ₽ (по умолчанию по тарифу)
                <input class="field" type="number" name="custom_amount_rub" min="0" step="100" placeholder="Автоматический расчёт">
              </label>
              <label>Пояснение для заказчика
                <textarea name="client_explanation" maxlength="3000" placeholder="Пояснение к дополнительной стоимости">${esc(r.reason)}</textarea>
              </label>
            </div>
            <div class="row" style="margin-top:8px">
              <button class="button primary small" type="submit">Принять решение PM</button>
              <button class="button small" type="button" data-pm-hour-reject="${r.id}">Отклонить</button>
            </div>
          </form>
        </div>`;
      } else {
        return `<div class="hours-request"><div class="row"><strong>+${hours(r.minutes)}</strong><span class="badge">Ожидает решения PM</span></div><p>${esc(r.reason)}</p><small>${esc(r.author_name)} · ${date(r.created_at)}</small></div>`;
      }
    }
    const billNote = r.bill_customer ? ` · клиенту: ${(r.amount_rub || 0).toLocaleString('ru-RU')} ₽` : ' · за счёт компании';
    const stBadge = r.state === 'approved' ? 'Одобрено' : r.state === 'rejected' ? 'Отклонено' : 'На согласовании у заказчика';
    return `<div class="hours-request"><div class="row"><strong>+${hours(r.pm_approved_minutes || r.minutes)}${billNote}</strong><span class="badge">${stBadge}</span></div><p>${esc(r.reason)}</p>${r.client_explanation ? `<p class="muted">Пояснение клиенту: ${esc(r.client_explanation)}</p>` : ''}<small>${esc(r.author_name)} · ${date(r.created_at)}</small></div>`;
  }).join('') : '';

  const customerRequests = !staff ? hour_requests.map(r => `
    <div class="hours-request ${r.state === 'pending' && canDecide ? 'needs-action' : ''}">
      <div class="row"><strong>Дополнительные работы: +${(r.amount_rub || 0).toLocaleString('ru-RU')} ₽</strong><span class="badge">${r.state === 'approved' ? 'Одобрено' : r.state === 'rejected' ? 'Отклонено' : 'Ожидает согласования'}</span></div>
      <p>${esc(r.reason || r.client_explanation || '')}</p>
      <small>${date(r.created_at)}</small>
      ${r.state === 'pending' && canDecide ? `<div class="row" style="margin-top:8px"><button class="button primary" data-hours-approve="${r.id}">Согласовать доплату</button><button class="button" data-hours-reject="${r.id}">Отклонить</button></div>` : ''}
    </div>
  `).join('') : '';

  const entries = staff ? time_entries.map(w => `<div class="time-entry"><div class="row"><strong>${hours(w.minutes)}</strong><small>${esc(w.work_date || w.created_at.slice(0, 10))}</small></div><p>${esc(w.note)}</p><small>${esc(w.author_name)}</small></div>`).join('') : '';

  const logForm = assigned && ['working', 'waiting', 'done'].includes(t.status) && t.approved_minutes ? `<form class="form" id="time-entry-form"><label>Дата работы<input class="field" type="date" name="work_date" value="${new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10)}" max="${new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10)}" required></label><small>Часы поступят администратору на подтверждение для выплаты.</small><div><span>Фактически потрачено</span><div class="duration-inputs"><label>Часы<input class="field" type="number" name="hours" min="0" step="1" max="${Math.floor(remaining / 60)}" placeholder="0" inputmode="numeric"></label><label>Минуты · необязательно<input class="field" type="number" name="minutes" min="0" max="60" step="1" placeholder="0" inputmode="numeric"></label></div><small>Например: 1 час и 30 минут. Пустое поле — 0. 60 минут = 1 час.</small></div><label>Что сделано<textarea name="note" data-draft="work-note-${t.id}" required minlength="3" maxlength="2000" placeholder="Кратко опишите результат работы"></textarea></label><button class="button primary" ${remaining < 1 ? 'disabled data-permanently-disabled="true"' : ''}>Внести время</button>${remaining > 0 ? `<button type="button" class="button" id="fill-remaining">Внести остаток ${hours(remaining)}</button>` : ''}</form>` : '';

  const requestForm = assigned && ['working', 'waiting'].includes(t.status) && t.approved_minutes && !t.pending_hour_request ? `<form class="form" id="hour-request-form"><p class="muted">Запросите часы сверх согласованной оценки и укажите причину. Запрос поступит руководителю проектов (PM) на проверку.</p><label>Дополнительные часы<input class="field" type="number" name="hours" min="0.25" step="0.25" required></label><label>Почему нужны дополнительные часы<textarea name="reason" required minlength="3" maxlength="2000"></textarea></label><button class="button">Запросить согласование</button></form>` : '';

  const deadlineForm = staff && (state.user.role === 'admin' || state.user.is_manager) ? `<form class="deadline-form" id="deadline-form"><label>Установить срок выполнения<input class="field" type="datetime-local" name="due_at" value="${t.delivery_due_at ? new Date(t.delivery_due_at).toLocaleString('sv-SE').replace(' ', 'T').slice(0, 16) : ''}"></label><button class="button">Сохранить срок</button></form>` : '';

  document.querySelector('.detail-grid>div:last-child').insertAdjacentHTML('afterbegin', `<section class="panel content operations-panel"><h2>Сроки SLA</h2>${slaCard(t)}${deadlineForm}</section>`);
  if (staff) document.querySelector('.detail-grid>div:last-child').insertAdjacentHTML('beforeend', `<div id="git-links-container">${renderGitLinksPanel(t.id, staff && t.can_write !== false)}</div>`);

  const serviceEntries = state.current.service_entries || [];
  const serviceMins = t.service_minutes || 0;
  const serviceTarget = { customer_id: t.customer_id, customer_name: t.customer_company || t.customer_name, ticket_id: t.id, reload: () => openTicket(t.id) };
  const serviceList = serviceEntries.length ? serviceEntries.map(e => serviceEntryItem(e, { canDelete: e.author_id === state.user.id || isDispatcher() })).join('') : '<p class="muted">Созвонов и переписки по заявке пока не учтено.</p>';
  const serviceTotal = billingOn() ? `<div class="hours-finance"><span>Стоимость для заказчика: <strong>${(t.total_cost_rub ?? costRub).toLocaleString('ru-RU')} ₽</strong></span><span style="margin: 0 10px; color: var(--line)">|</span><span>оценка ${costRub.toLocaleString('ru-RU')} ₽ + сопровождение ${(t.service_cost_rub || 0).toLocaleString('ru-RU')} ₽</span></div>` : '';

  const clientService = !staff && billingOn() ? `
    <section class="panel content">
      <h2>Сопровождение и общая стоимость</h2>
      <p>Консультации, созвоны и координация учитываются отдельно. В закрывающих документах они указываются строкой «Консультационное сопровождение и координация работ».</p>
      <p>Согласованная стоимость работ: <strong>${costRub.toLocaleString('ru-RU')} ₽</strong>.</p>
      <p>Учтено сопровождение: <strong>${(t.service_cost_rub || 0).toLocaleString('ru-RU')} ₽</strong>.</p>
      <p>Общая стоимость: <strong>${(t.total_cost_rub ?? costRub).toLocaleString('ru-RU')} ₽</strong>.</p>
      ${t.estimate_state === 'pending' ? '<p class="muted">Текущая оценка ещё не согласована и не входит в эту сумму.</p>' : ''}
    </section>
  ` : '';

  const serviceSection = staff ? `<section class="panel content operations-panel"><div class="row contractor-time-header"><h2>Трудозатраты подрядчика</h2>${t.can_write !== false ? `<button class="button small" type="button" id="open-service-form">${icon('clock', 14)}Учесть созвон или переписку</button>` : ''}</div><div class="hours-summary contractor-time-summary"><div><small>Фактическая работа</small><strong>${hours(t.actual_minutes || 0)}</strong></div><div><small>Оценки и переоценки</small><strong>${hours(t.assessment_minutes || 0)}</strong></div><div><small>Сопровождение</small><strong>${hours(serviceMins)}</strong></div><div><small>Всего к учёту подрядчику</small><strong>${hours(t.contractor_total_minutes || 0)}</strong></div></div><p class="muted">Всего — фактически внесённая работа, время всех версий оценки (включая отклонённые и пересмотренные), учтённые созвоны и переписка. Время уточнений нужно внести вручную и привязать к этой заявке.</p>${serviceTotal}<p class="muted">Подробности записей видны только команде. Заказчик видит стоимость работ и сопровождения.</p>${t.can_write !== false ? serviceForm(serviceTarget, serviceEntries) : ''}${serviceList}</section>` : '';

  const financeHtml = `<div class="hours-finance"><span>Ставка: <strong>${rateRub.toLocaleString('ru-RU')} ₽/ч</strong></span><span style="margin: 0 10px; color: var(--line)">|</span><span>Стоимость: <strong>${costRub.toLocaleString('ru-RU')} ₽</strong></span>${actBadge}</div>`;

  const staffWorkSection = staff ? `<section class="panel content operations-panel" id="actual-work"><h2>Фактические трудозатраты</h2><p class="muted">Вносите время, которое действительно потратили на выполнение. После записи передайте готовый результат заказчику на проверку.</p><div class="hours-summary"><div><small>Согласовано</small><strong>${hours(t.approved_minutes || 0)}</strong></div><div><small>Выполнено</small><strong>${hours(t.actual_minutes || 0)}</strong></div><div><small>Осталось</small><strong>${hours(remaining)}</strong></div></div><div class="work-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}" aria-label="Использовано согласованных часов"><span style="width:${progress}%"></span></div>${billingOn() ? financeHtml : ''}${logForm}${entries ? `<h3>Записи времени</h3>${entries}` : '<p class="muted">Фактическое время пока не внесено.</p>'}${requests ? `<h3>Дополнительные часы</h3>${requests}` : ''}${requestForm}</section>` : '';

  const customerRequestsSection = (!staff && customerRequests) ? `
    <section class="panel content operations-panel">
      <h2>Дополнительные работы</h2>
      <p class="muted">Согласование дополнительных работ и стоимости.</p>
      ${customerRequests}
    </section>
  ` : '';

  const filesSection = `<section class="panel content operations-panel"><h2>Файлы</h2>${attachments.map(a => `<a class="attachment-link" href="/api/attachments/${a.id}"><span>${icon('paperclip', 14)} ${esc(a.filename)}</span><small>${Math.ceil(a.size / 1024)} КБ</small></a>`).join('') || '<p class="muted">Файлов пока нет.</p>'}${t.status !== 'closed' && !viewer ? '<label class="upload-label">Прикрепить файл<input id="ticket-file" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.zip"></label>' : ''}</section>`;

  document.querySelector('.detail-grid>div:first-child').insertAdjacentHTML('beforeend', `${staffWorkSection}${customerRequestsSection}${serviceSection}${clientService}${filesSection}`);

  const actualWork = document.querySelector('#actual-work');
  const conversation = document.querySelector('.detail-grid .conversation');
  if (actualWork && conversation) conversation.before(actualWork);
  if (actualWork) bindDrafts(actualWork);

  state.pendingOps ||= {};
  const submit = async (path, data, key) => {
    try {
      await api(path, { method: 'POST', body: JSON.stringify(data) });
      if (key) delete state.pendingOps[key];
      if (key === `time-${t.id}`) clearDraft(`work-note-${t.id}`);
      await refresh();
      await openTicket(t.id);
    } catch (error) {
      showError(error);
      document.querySelector('#time-entry-form button.primary:not([data-permanently-disabled])')?.removeAttribute('disabled');
      document.querySelector('#hour-request-form button')?.removeAttribute('disabled');
    }
  };

  const timeForm = document.querySelector('#time-entry-form');
  const timeMinutes = () => Number(timeForm.elements.hours.value) * 60 + Number(timeForm.elements.minutes.value);
  const validateTime = () => {
    const minutes = timeMinutes();
    timeForm.elements.hours.setCustomValidity(minutes < 1 ? 'Укажите время: хотя бы 1 минуту.' : minutes > remaining ? `Осталось ${hours(remaining)}. Для превышения лимита согласуйте дополнительные часы.` : '');
  };
  timeForm?.addEventListener('input', validateTime);
  document.querySelector('#fill-remaining')?.addEventListener('click', () => {
    timeForm.elements.hours.value = String(Math.floor(remaining / 60));
    timeForm.elements.minutes.value = String(remaining % 60);
    validateTime();
    timeForm.elements.note.focus();
  });
  document.querySelector('#time-entry-form')?.addEventListener('submit', e => {
    e.preventDefault();
    validateTime();
    if (!e.target.reportValidity()) return;
    e.target.querySelector('button').disabled = true;
    const form = new FormData(e.target);
    const key = `time-${t.id}`;
    const request_id = state.pendingOps[key] ||= crypto.randomUUID();
    submit(`/tickets/${t.id}/time-entries`, { minutes: timeMinutes(), note: form.get('note'), work_date: form.get('work_date'), request_id }, key);
  });

  document.querySelector('#hour-request-form')?.addEventListener('submit', e => {
    e.preventDefault();
    e.target.querySelector('button').disabled = true;
    const form = new FormData(e.target);
    const key = `hours-${t.id}`;
    const request_id = state.pendingOps[key] ||= crypto.randomUUID();
    submit(`/tickets/${t.id}/hour-requests`, { minutes: Math.round(Number(form.get('hours')) * 60), reason: form.get('reason'), request_id }, key);
  });

  document.querySelectorAll('.pm-hour-decision-form').forEach(form => {
    const reqId = form.dataset.requestId;
    const billCheck = form.querySelector('.bill-customer-check');
    const billFields = form.querySelector('.bill-customer-fields');
    billCheck?.addEventListener('change', () => {
      if (billFields) billFields.hidden = !billCheck.checked;
    });
    form.onsubmit = async e => {
      e.preventDefault();
      const fd = new FormData(form);
      const appH = Number(fd.get('approved_hours') || 0);
      const isBilled = billCheck?.checked || false;
      const customAmt = fd.get('custom_amount_rub');
      submit(`/tickets/${t.id}/hour-requests/${reqId}/pm-decision`, {
        action: 'approve',
        approved_performer_minutes: Math.round(appH * 60),
        bill_customer: isBilled,
        customer_minutes: isBilled ? Math.round(appH * 60) : 0,
        custom_amount_rub: (isBilled && customAmt) ? Number(customAmt) : null,
        client_explanation: isBilled ? (fd.get('client_explanation') || '') : ''
      });
    };
  });

  document.querySelectorAll('[data-pm-hour-reject]').forEach(btn => {
    btn.onclick = () => submit(`/tickets/${t.id}/hour-requests/${btn.dataset.pmHourReject}/pm-decision`, { action: 'reject' });
  });

  document.querySelectorAll('[data-hours-approve],[data-hours-reject]').forEach(button => button.onclick = () => submit(`/tickets/${t.id}/hour-requests/${button.dataset.hoursApprove || button.dataset.hoursReject}/decision`, { action: button.dataset.hoursApprove ? 'approve' : 'reject' }));
  document.querySelector('#ticket-file')?.addEventListener('change', async e => {
    try {
      for (const file of e.target.files) await upload(`/tickets/${t.id}/attachments`, file);
      await refresh();
      await openTicket(t.id);
    } catch (error) {
      showError(error);
    }
  });
  if (staff) bindServiceForm(serviceTarget);
  document.querySelector('#deadline-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const raw = e.target.elements.due_at.value;
    try {
      await api(`/tickets/${t.id}/deadline`, { method: 'PATCH', body: JSON.stringify({ due_at: raw ? new Date(raw).toISOString() : null }) });
      await refresh();
      await openTicket(t.id);
    } catch (error) {
      showError(error);
    }
  });
}
function serviceEntryItem(e, { showClient = false, canDelete = false } = {}) {
  const billed = e.act_invoice_id ? `<a class="billing-doc-pill act" href="/api/billing/invoices/${e.act_invoice_id}/print" target="_blank" rel="noopener">Акт ${esc(e.act_number || '')}</a>` : '<span class="badge">Ждёт акта</span>';
  const remove = canDelete && !e.act_invoice_id ? `<button class="button small" type="button" data-service-delete="${e.id}" aria-label="Удалить запись">Удалить</button>` : '';
  const summary = e.client_summary ? `<div class="entry-summary"><span class="eyebrow">Итоги для клиента · ${e.shared_at ? `отправлены ${date(e.shared_at)}` : 'не отправлены'}</span><p>${esc(e.client_summary)}</p>${e.client_next_steps ? `<p><strong>Дальше:</strong> ${esc(e.client_next_steps)}</p>` : ''}</div>` : '';
  const summaryAction = canDelete && !e.shared_at ? `<button class="button small" type="button" data-summary-edit="${e.id}">${icon('send', 13)}${e.client_summary ? 'Отправить итоги клиенту' : 'Итоги для клиента'}</button>` : '';
  const summaryForm = canDelete && !e.shared_at ? `<form class="form summary-form" data-summary-form="${e.id}" hidden><label>О чём договорились<textarea name="summary" required minlength="3" maxlength="3000">${esc(e.client_summary || '')}</textarea></label><label>Что дальше<textarea name="next_steps" maxlength="2000">${esc(e.client_next_steps || '')}</textarea></label><small class="muted">Клиент увидит только итоги — без длительности и внутренней заметки.</small><div class="row"><button class="button primary small">Отправить клиенту</button><button class="button small" type="button" data-summary-cancel="${e.id}">Отмена</button></div></form>` : '';
  return `<div class="time-entry"><div class="row"><strong>${hours(e.minutes)} · ${esc(serviceKindNames[e.kind] || e.kind)}</strong><small>${date(e.occurred_at)}</small></div><p>${esc(e.note)}</p>${summary}<div class="row"><small>${showClient ? `${esc(e.client_name)} · ` : ''}${esc(e.author_name)}${e.ticket_id ? ` · заявка №${e.ticket_id}` : ''}</small><span class="row">${summaryAction}${billed}${remove}</span></div>${summaryForm}</div>`;
}
function bindServiceDelete(after) {
  document.querySelectorAll('[data-service-delete]').forEach(btn => btn.onclick = async () => {
    if (!confirm('Удалить запись о времени?')) return;
    try { await api(`/service-entries/${btn.dataset.serviceDelete}`, { method: 'DELETE' }); toast('Запись удалена'); await after(); } catch (error) { showError(error); }
  });
  document.querySelectorAll('[data-summary-edit]').forEach(btn => btn.onclick = () => { const form = document.querySelector(`[data-summary-form="${btn.dataset.summaryEdit}"]`); form.hidden = false; form.elements.summary.focus(); });
  document.querySelectorAll('[data-summary-cancel]').forEach(btn => btn.onclick = () => { document.querySelector(`[data-summary-form="${btn.dataset.summaryCancel}"]`).hidden = true; });
  document.querySelectorAll('[data-summary-form]').forEach(form => form.onsubmit = async e => {
    e.preventDefault();
    form.querySelector('button.primary').disabled = true;
    try { await api(`/service-entries/${form.dataset.summaryForm}/summary`, { method: 'PATCH', body: JSON.stringify({ summary: form.elements.summary.value, next_steps: form.elements.next_steps.value, share: true }) }); toast('Итоги отправлены клиенту'); await after(); }
    catch (error) { form.querySelector('button.primary').disabled = false; showError(error); }
  });
}
function chatServiceTarget(chat) { return { customer_id: state.currentChat?.participants?.[0]?.id || chat.customer_id, customer_name: chat.customer_name, reload: () => openChat(chat.id) }; }
function servicePendingMinutes(entries) { return entries.filter(e => !e.act_invoice_id).reduce((acc, e) => acc + e.minutes, 0); }
function serviceBlock(entries) {
  const pending = servicePendingMinutes(entries);
  const list = entries.length ? entries.slice(0, 10).map(e => serviceEntryItem(e, { canDelete: e.author_id === state.user.id || isDispatcher() })).join('') : '<p class="muted">Записей пока нет.</p>';
  return `<div class="info-block"><span class="eyebrow">Сопровождение${pending ? ` <span>${hours(pending)} к акту</span>` : ''}</span>${list}</div>`;
}
function serviceForm(target, entries) {
  const pending = servicePendingMinutes(entries);
  const customerTickets = target.ticket_id ? [] : state.tickets.filter(t => t.customer_id === target.customer_id && t.status !== 'closed');
  const nowLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return `<form class="form chat-ticket-form service-form" id="service-form" hidden>
    <strong>Учёт времени: ${esc(target.customer_name)}${target.ticket_id ? `, заявка №${target.ticket_id}` : ''}</strong>
    <small class="muted">Клиент не видит длительность и заметку: в акте записи идут общей строкой по его ставке. Итоги встречи можно отправить ему отдельно.${pending ? ` Сейчас к акту: ${hours(pending)}.` : ''}</small>
    <label>Вид<select class="field" name="kind">${Object.entries(serviceKindNames).map(([k, v]) => `<option value="${k}" ${k === 'call' ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
    <label>Длительность, минут<input class="field" type="number" name="minutes" min="5" max="1440" step="5" required></label>
    <label>Когда<input class="field" type="datetime-local" name="occurred_at" value="${nowLocal}" max="${nowLocal}"></label>
    ${customerTickets.length ? `<label>Заявка (необязательно)<select class="field" name="ticket_id"><option value="">Без заявки</option>${customerTickets.map(t => `<option value="${t.id}">№${t.id} · ${esc(t.title)}</option>`).join('')}</select></label>` : ''}
    <label>Что обсуждали (видно только команде)<textarea name="note" required minlength="3" maxlength="2000" placeholder="Например: созвон по срокам релиза"></textarea></label>
    <fieldset class="summary-fields"><legend>Итоги для клиента <small>необязательно</small></legend>
      <label>О чём договорились<textarea name="summary" maxlength="3000" placeholder="Например: обмен заказами запускаем 15 октября, формат — JSON"></textarea></label>
      <label>Что дальше<textarea name="next_steps" maxlength="2000" placeholder="Например: до пятницы пришлём схему, от вас — доступ к API"></textarea></label>
      <label class="check-row"><input type="checkbox" name="share">Отправить итоги клиенту</label>
      <small class="muted">Клиент увидит только итоги — без длительности и внутренней заметки.</small>
    </fieldset>
    <div class="row"><button class="button primary">Внести время</button><button class="button" type="button" id="cancel-service">Отмена</button></div></form>`;
}
function bindServiceForm(target) {
  const form = document.querySelector('#service-form');
  if (!form) return;
  document.querySelector('#open-service-form').onclick = () => { const ticketForm = document.querySelector('#chat-ticket-form'); if (ticketForm) ticketForm.hidden = true; form.hidden = false; form.elements.minutes.focus(); };
  document.querySelector('#cancel-service').onclick = () => { form.hidden = true; };
  form.elements.summary.addEventListener('input', () => { if (form.elements.summary.value.trim().length >= 3 && !form.dataset.shareTouched) form.elements.share.checked = true; });
  form.elements.share.addEventListener('change', () => { form.dataset.shareTouched = '1'; });
  form.onsubmit = async e => {
    e.preventDefault();
    const button = form.querySelector('button.primary');
    button.disabled = true;
    const data = new FormData(form);
    const requestId = form.dataset.requestId || (form.dataset.requestId = crypto.randomUUID());
    try {
      await api('/service-entries', { method: 'POST', body: JSON.stringify({
        customer_id: target.customer_id, kind: data.get('kind'), minutes: Number(data.get('minutes')), note: data.get('note'),
        occurred_at: data.get('occurred_at') ? new Date(data.get('occurred_at')).toISOString() : null,
        ticket_id: target.ticket_id || (data.get('ticket_id') ? Number(data.get('ticket_id')) : null), request_id: requestId,
        summary: data.get('summary') || '', next_steps: data.get('next_steps') || '', share: data.get('share') === 'on'
      }) });
      toast(data.get('share') === 'on' ? 'Время внесено, итоги отправлены клиенту' : 'Время внесено');
      await target.reload();
    } catch (error) { button.disabled = false; showError(error); }
  };
  bindServiceDelete(target.reload);
}
function chatUnreadCount(id) { return state.notifications.filter(n => n.target === 'chat' && !n.read_at && n.chat_id === id).length; }
function inboxTickets() {
  return [...state.tickets].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')) || b.id - a.id);
}
function paintInboxUnread() {
  document.querySelectorAll('[data-ticket-chat], [data-chat]').forEach(el => {
    const tickets = el.hasAttribute('data-ticket-chat');
    const id = Number(tickets ? el.dataset.ticketChat : el.dataset.chat);
    const unread = state.notifications.filter(n => n.target === (tickets ? 'ticket' : 'chat') && !n.read_at && (tickets ? n.ticket_id : n.chat_id) === id).length;
    const meta = el.querySelector('.chat-item-meta');
    if (!meta) return;
    meta.querySelector('.unread-count')?.remove();
    if (unread) meta.insertAdjacentHTML('beforeend', `<span class="unread-count" aria-label="${unread} непрочитанных">${unread}</span>`);
  });
}
function chatListPanel(activeId) {
  const tickets = state.inboxSection === 'tickets';
  const records = tickets ? inboxTickets() : state.chats;
  const search = tickets ? state.ticketChatSearch : state.chatSearch;
  const sectionButton = (id, label, count) => `<button type="button" class="${state.inboxSection === id ? 'active' : ''}" data-inbox-section="${id}" aria-pressed="${state.inboxSection === id}">${label}<span>${count}</span></button>`;
  const items = records.map(c => {
    const unread = tickets ? state.notifications.filter(n => n.target === 'ticket' && !n.read_at && n.ticket_id === c.id).length : chatUnreadCount(c.id);
    const title = tickets ? `№${c.id} · ${c.title}` : c.customer_name;
    const preview = tickets ? [c.customer_company || c.customer_name, statusNames[c.status]].filter(Boolean).join(' · ') : c.last_message || 'Диалог пока пуст';
    const active = c.id === activeId;
    return `<button class="chat-item ${active ? 'active' : ''}" ${tickets ? 'data-ticket-chat' : 'data-chat'}="${c.id}" ${active ? 'aria-current="true"' : ''}><span class="chat-logo" aria-hidden="true">${tickets ? icon('ticket', 18) : initials(c.customer_name)}</span><span class="chat-item-text"><strong>${esc(title)}</strong><small>${esc(preview)}</small></span><span class="chat-item-meta">${date(c.updated_at)}${unread ? `<span class="unread-count" aria-label="${unread} непрочитанных">${unread}</span>` : ''}</span></button>`;
  }).join('');
  return `<div class="inbox-list"><div class="inbox-list-head"><div class="inbox-sections" role="group" aria-label="Разделы переписки">${sectionButton('general', 'Общие', state.chats.length)}${sectionButton('tickets', 'Чаты заявок', state.tickets.length)}</div><label class="inbox-search">${icon('search', 15)}<span class="visually-hidden">Поиск по диалогам</span><input type="search" id="chat-search" placeholder="${tickets ? 'Номер, тема или заказчик' : 'Компания, заказчик или сообщение'}" value="${esc(search || '')}"></label></div><div class="inbox-items">${items || `<div class="empty"><strong>${tickets ? 'Заявок пока нет' : 'Диалогов пока нет'}</strong>${tickets ? 'Здесь появятся переписки по доступным вам заявкам.' : 'Когда участник компании напишет в общий чат, диалог появится здесь.'}</div>`}</div><div class="empty chat-no-results" id="chat-no-results" role="status" hidden><strong>Диалог не найден</strong>Попробуйте другой поисковый запрос.</div></div>`;
}
function bindChatList() {
  document.querySelectorAll('[data-chat]').forEach(el => el.onclick = () => openChat(Number(el.dataset.chat)));
  document.querySelectorAll('[data-ticket-chat]').forEach(el => el.onclick = () => openTicketChat(Number(el.dataset.ticketChat)));
  document.querySelectorAll('[data-inbox-section]').forEach(el => el.onclick = () => { state.inboxSection = el.dataset.inboxSection; setView('chats'); });
  const search = document.querySelector('#chat-search');
  const filter = () => {
    state[state.inboxSection === 'tickets' ? 'ticketChatSearch' : 'chatSearch'] = search.value;
    const query = search.value.trim().toLocaleLowerCase('ru-RU');
    let visible = 0;
    document.querySelectorAll('.chat-item').forEach(el => { el.hidden = Boolean(query) && !el.textContent.toLocaleLowerCase('ru-RU').includes(query); if (!el.hidden) visible++; });
    const empty = document.querySelector('#chat-no-results');
    if (empty) empty.hidden = !query || visible > 0 || !(state.inboxSection === 'tickets' ? state.tickets : state.chats).length;
  };
  if (search) { search.addEventListener('input', filter); filter(); }
}
function renderChats() {
  const unread = state.notifications.filter(n => ['chat', 'ticket'].includes(n.target) && !n.read_at).length;
  shell('Общий чат', '', `<section class="panel inbox no-thread">${chatListPanel(null)}<div class="inbox-empty"><div>${icon('chat', 28)}<p><strong>Выберите диалог</strong><br>Выберите общий диалог или чат заявки слева.</p></div></div></section>`, { kicker: 'Общие диалоги и чаты заявок', lead: `${state.chats.length} ${plural(state.chats.length, ['общий диалог', 'общих диалога', 'общих диалогов'])} · ${state.tickets.length} ${plural(state.tickets.length, ['чат заявки', 'чата заявок', 'чатов заявок'])}${unread ? ` · ${unread} ${plural(unread, ['непрочитанное', 'непрочитанных', 'непрочитанных'])}` : ''}` });
  bindChatList();
}
async function openChat(id) {
  if(state.view!=='chat'||state.currentChat?.chat?.id!==id)delayedLoading('Общий чат','list');
  try{state.currentChat=await api(`/chats/${id}`);state.inboxSection='general';state.view='chat';state.error='';render();}
  catch(error){showError(error);}
}
let ticketChatLoad = 0;
async function openTicketChat(id) {
  const load = ++ticketChatLoad;
  const accountId = state.user.id;
  const origin = `${state.view}:${state.inboxSection}`;
  try {
    const detail = await api(`/tickets/${id}`);
    if (load !== ticketChatLoad || state.user?.id !== accountId || `${state.view}:${state.inboxSection}` !== origin) return;
    state.current = detail;
    state.inboxSection = 'tickets';
    state.view = 'ticket-chat';
    state.error = '';
    render();
  } catch (error) { if (load === ticketChatLoad) showError(error); }
}
function renderTicketChat() {
  const { ticket: t, messages, attachments = [], meeting_summaries = [] } = state.current;
  const staff = state.user.role !== 'customer';
  const viewer = t.can_write === false;
  const canReply = !viewer && t.status !== 'closed';
  const items = timeline(messages, meeting_summaries, m => messageHtml(m, {
    header: `${esc(m.author_name)} · ${date(m.created_at)}`, canReply
  })).map(entry => entry.html).join('') || '<div class="empty">Сообщений пока нет. Здесь появится переписка по заявке.</div>';
  const files = attachments.length ? `<div class="ticket-chat-files"><details><summary>Файлы заявки · ${attachments.length}</summary>${attachments.map(attachmentLink).join('')}</details></div>` : '';
  const thread = `<section class="inbox-thread conversation"><div class="inbox-thread-head"><button type="button" class="icon-btn thread-back" id="back-chats" aria-label="К списку диалогов">←</button><span class="chat-logo" aria-hidden="true">${icon('ticket', 20)}</span><div><strong>№${t.id} · ${esc(t.title)}</strong><small>${esc(t.customer_company || t.customer_name)} · ${esc(statusNames[t.status])}</small></div><button type="button" class="button small" id="open-ticket-card">Открыть заявку ${icon('arrow', 14)}</button></div>${files}<div class="messages" id="ticket-chat-messages">${items}</div>${ticketChatComposer(t, viewer, staff)}</section>`;
  shell('Общий чат', '', `<section class="panel inbox has-thread ticket-inbox">${chatListPanel(t.id)}${thread}</section>`, { kicker: 'Общие диалоги и чаты заявок' });
  bindChatList();
  document.querySelector('#back-chats').onclick = () => setView('chats');
  document.querySelector('#open-ticket-card').onclick = () => openTicket(t.id);
  bindTicketChatComposer(t, () => openTicketChat(t.id));
  bindConversation('ticket', t.id, messages, state.current.read_state);
  const box = document.querySelector('#ticket-chat-messages');
  box.scrollTop = box.scrollHeight;
  popLastMessage(box);
}

function openChatContext() {
  const info = document.querySelector('.inbox-info');
  if (!info) return;
  const trigger = document.activeElement;
  const marker = document.createComment('chat-context');
  info.before(marker);
  const dialog = document.createElement('dialog');
  dialog.className = 'team-dialog chat-context-dialog';
  dialog.setAttribute('aria-labelledby', 'chat-context-title');
  dialog.innerHTML = `<div class="team-dialog-head"><h2 id="chat-context-title">О диалоге</h2><button type="button" class="icon-btn" aria-label="Закрыть окно">${icon('close')}</button></div><div class="team-dialog-body"></div>`;
  dialog.querySelector('.team-dialog-body').append(info);
  document.body.append(dialog);
  dialog.querySelector('button').onclick = () => dialog.close();
  dialog.addEventListener('click', event => {
    if (event.target.closest('[data-linked-ticket]')) dialog.close();
  }, true);
  const closeOnNavigation = () => dialog.close();
  window.addEventListener('hashchange', closeOnNavigation, { once: true });
  dialog.addEventListener('close', () => {
    window.removeEventListener('hashchange', closeOnNavigation);
    if (marker.isConnected) marker.replaceWith(info);
    dialog.remove();
    if (trigger?.isConnected) trigger.focus();
  });
  dialog.showModal();
}

function renderChatDetail() {
  const { chat, messages, participants = [], linked_tickets = [], attachments = [], service_entries = [], meeting_summaries = [] } = state.currentChat;
  const staff = state.user.role !== 'customer';
  const dispatcher = isDispatcher();
  let lastDay = '';
  const items = timeline(messages, meeting_summaries, m => messageHtml(m, { canReply: true,
    header: `${esc(m.author_name)} · ${new Date(m.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`,
    extra: attachments.filter(a => a.chat_message_id === m.id).map(attachmentLink).join('') })).map(entry => {
    const day = new Date(entry.at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
    const separator = day !== lastDay ? `<div class="day-separator">${day}</div>` : '';
    lastDay = day;
    return separator + entry.html;
  }).join('') || '<div class="empty">Начните разговор. Сообщение увидит наша команда.</div>';
  const otherTickets = state.tickets.filter(t => (chat.organization_id ? t.organization_id === chat.organization_id && t.visibility === 'organization' : t.customer_id === chat.customer_id) && !['done', 'closed'].includes(t.status) && !linked_tickets.some(l => l.id === t.id));
  const ticketButton = t => `<button class="linked-ticket" data-linked-ticket="${t.id}"><span>№${t.id} · ${esc(t.title)}</span>${t.status ? `<span class="badge ${esc(t.status)}">${statusNames[t.status]}</span>` : ''}</button>`;
  const assigneeSelect = dispatcher ? `<label class="select-inline"><span>Ведёт</span><select id="chat-assignee" aria-label="Ответственный за чат"><option value="">Без ответственного</option>${state.staff.map(x => `<option value="${x.id}">${esc(staffLabel(x))}</option>`).join('')}</select></label>` : '';
  const info = `<div class="inbox-info" role="complementary" aria-label="О диалоге"><div class="info-block"><span class="eyebrow">${chat.organization_id ? 'Компания' : 'Заказчик'}</span><strong>${esc(chat.customer_name)}</strong></div>${chat.organization_id ? `<div class="info-block"><span class="eyebrow">Участники компании · ${participants.length}</span>${participants.map(p => `<div>${esc(p.name)}</div>`).join('')}<small class="muted">Все участники компании видят эту переписку.</small></div>` : ''}${staff ? `<div class="info-block"><span class="eyebrow">Ответственный</span><strong>${esc(chat.assignee_name || 'Не назначен')}</strong></div>` : ''}${linked_tickets.length ? `<div class="info-block"><span class="eyebrow">Заявки из этого чата <span>${linked_tickets.length}</span></span>${linked_tickets.map(ticketButton).join('')}</div>` : ''}${otherTickets.length ? `<div class="info-block"><span class="eyebrow">Открытые заявки <span>${otherTickets.length}</span></span>${otherTickets.slice(0, 5).map(ticketButton).join('')}</div>` : ''}${staff ? serviceBlock(service_entries) : ''}</div>`;
  const thread = `<section class="inbox-thread"><div class="inbox-thread-head"><button class="icon-btn thread-back" id="back-chats" aria-label="К списку диалогов">←</button><span class="chat-logo" aria-hidden="true">${initials(staff ? chat.customer_name : 'Линия')}</span><div><strong>${esc(chat.organization_id ? chat.customer_name : staff ? chat.customer_name : 'Служба поддержки')}</strong><small>${chat.organization_id ? `Чат всей компании · ${participants.length} ${plural(participants.length, ['участник', 'участника', 'участников'])} · ` : ''}${messages.length} ${plural(messages.length, ['сообщение', 'сообщения', 'сообщений'])}</small></div>${staff ? `<button class="button small" type="button" id="open-service-form">${icon('clock', 14)}Учесть время</button>` : ''}${assigneeSelect}<button type="button" class="icon-btn chat-info-toggle" id="chat-info-toggle" aria-label="О диалоге и связанных заявках">${icon('alert', 18)}</button></div><div class="messages" id="chat-messages">${items}</div><form class="composer" id="chat-message-form">${replyBar('chat', chat.id)}<label class="visually-hidden" for="chat-body">Сообщение</label><textarea id="chat-body" data-draft="chat-${chat.id}" name="body" required maxlength="10000" placeholder="${staff ? `Ответить: ${esc(chat.customer_name)}` : 'Напишите сообщение команде…'}"></textarea><div class="composer-files" id="chat-files"></div><div class="composer-bar"><label class="upload-label">${icon('paperclip', 15)}Файлы<input name="files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.zip"></label><span class="composer-hint">Ctrl + Enter — отправить</span><button class="button primary">Отправить</button></div></form></section>`;
  shell(staff ? 'Общий чат' : 'Чат с командой', '', `<section class="panel inbox has-thread">${chatListPanel(chat.id)}${thread}${info}</section>`, { kicker: chat.organization_id ? 'Общий чат компании с командой поддержки' : staff ? 'Переписка без привязки к заявке' : 'Личный кабинет' });
  bindChatList();
  document.querySelector('#chat-info-toggle').onclick = openChatContext;
  document.querySelectorAll('[data-linked-ticket]').forEach(el => el.onclick = () => openTicket(Number(el.dataset.linkedTicket)));
  if (staff) {
    document.querySelectorAll('#chat-messages .message').forEach(el => {
      const msg = messages.find(m => m.id === Number(el.dataset.msg));
      if (msg && msg.author_role === 'customer' && !linked_tickets.some(t => t.source_message_id === msg.id)) {
        el.querySelector('.msg-foot').insertAdjacentHTML('beforeend', `<button class="chat-to-ticket" data-message="${msg.id}">${icon('plus', 13)}Создать заявку из сообщения</button>`);
      }
    });
    document.querySelector('#chat-message-form').insertAdjacentHTML('afterend', '<form class="form chat-ticket-form" id="chat-ticket-form" hidden><strong>Новая заявка из чата</strong><label>Тема<input class="field" name="title" required minlength="3" maxlength="140"></label><input type="hidden" name="message_id"><div class="row"><button class="button primary">Создать заявку</button><button class="button" type="button" id="cancel-chat-ticket">Отмена</button></div></form>' + serviceForm(chatServiceTarget(chat), service_entries));
    document.querySelectorAll('[data-message]').forEach(el => el.onclick = () => { const msg = messages.find(m => m.id === Number(el.dataset.message)); const form = document.querySelector('#chat-ticket-form'); form.hidden = false; form.elements.message_id.value = msg.id; form.elements.title.value = msg.body.slice(0, 100); form.elements.title.focus(); });
    document.querySelector('#cancel-chat-ticket').onclick = () => document.querySelector('#chat-ticket-form').hidden = true;
    document.querySelector('#chat-ticket-form').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button.primary'); button.disabled = true; try { const data = Object.fromEntries(new FormData(e.target)); const ticket = await api(`/chats/${chat.id}/tickets`, { method: 'POST', body: JSON.stringify({ title: data.title, message_id: Number(data.message_id) }) }); await refresh(); await openTicket(ticket.id); } catch (error) { showError(error); } };
  }
  if (staff) bindServiceForm(chatServiceTarget(chat));
  document.querySelector('#back-chats')?.addEventListener('click', () => setView('chats'));
  if (dispatcher) { document.querySelector('#chat-assignee').value = chat.assignee_id || ''; document.querySelector('#chat-assignee').onchange = async e => { try { await api(`/chats/${chat.id}/assignee`, { method: 'PATCH', body: JSON.stringify({ assignee_id: e.target.value ? Number(e.target.value) : null }) }); await refresh(); await openChat(chat.id); } catch (error) { showError(error); } }; }
  bindCtrlEnter('#chat-message-form');
  document.querySelector('#chat-message-form').onsubmit = async e => { e.preventDefault(); if (!e.target.elements.body.value.trim() && !e.target.elements.files.files.length) return showError(new Error('Введите сообщение или прикрепите файл')); const button = e.target.querySelector('button.primary'); button.disabled = true; const requestId = e.target.dataset.requestId || (e.target.dataset.requestId = crypto.randomUUID()); try { const files = [...e.target.elements.files.files]; const message = await api(`/chats/${chat.id}/messages`, { method: 'POST', body: JSON.stringify({ body: e.target.elements.body.value.trim() || `Прикреплены файлы: ${files.map(file => file.name).join(', ')}`.slice(0, 10000), request_id: requestId, reply_to_id: replyToId('chat', chat.id) }) }); clearDraft(`chat-${chat.id}`); state.replyTo = null; for (const file of files) { await upload(`/chats/${chat.id}/attachments`, file, { message_id: message.id }); e.target.querySelector('[data-remove-file="0"]').click(); } state.justSent = true; await refresh(); await openChat(chat.id); } catch (error) { showError(error); } finally { button.disabled = false; } };
  document.querySelector('#chat-messages').scrollTop = document.querySelector('#chat-messages').scrollHeight;
  popLastMessage(document.querySelector('#chat-messages'));
  bindChatFiles();
  bindConversation('chat', chat.id, messages, state.currentChat.read_state);
}
function renderTeam() { TeamUI.render(); }
function renderProfile(){
  const p=state.profile;
  if(!p)return;
  if(state.user.role==='customer'){
    shell('Мой профиль','',`<div class="profile-layout"><section class="panel content profile-main"><div class="profile-heading customer-profile-heading">${avatar(p,'large')}<div><span class="eyebrow">КАБИНЕТ ЗАКАЗЧИКА</span><h2>${esc(p.name)}</h2><p>${esc(p.company_name||'Добавьте название компании')}</p><small>${esc(p.email)}</small></div></div><form class="form" id="customer-profile-form"><label>Ваше имя<input class="field" name="name" required minlength="2" maxlength="100" autocomplete="name" value="${esc(p.name)}"></label><label>Компания или команда<input class="field" name="company_name" maxlength="150" autocomplete="organization" placeholder="Например, Студия Север" value="${esc(p.company_name)}"></label><label>Контактный телефон<input class="field" name="phone" type="tel" maxlength="40" autocomplete="tel" placeholder="+7 999 123-45-67" value="${esc(p.phone)}"></label><label>Одобрять оценки автоматически — до, часов<input class="field" name="auto_approve_hours" type="number" min="0" max="1666" step="0.25" placeholder="0" value="${p.auto_approve_minutes?p.auto_approve_minutes/60:''}"><small>Небольшие задачи в пределах лимита уйдут в работу сразу, без вашего подтверждения. Пусто или 0 — всегда спрашивать.</small></label><p class="profile-hint">Email для входа: <strong>${esc(p.email)}</strong></p><div class="profile-actions"><button class="button primary">Сохранить изменения</button><span id="profile-saved" role="status"></span></div></form></section><div class="profile-note"><span class="eyebrow">НА СВЯЗИ С КОМАНДОЙ</span><h2>Ваши обращения в одном месте</h2><p>Имя и название компании помогут команде узнавать ваши задачи в заявках и общем чате. Контактный телефон доступен только вам в этом кабинете.</p><div class="profile-facts"><div><strong>${state.tickets.length}</strong><span>заявок</span></div><div><strong>${state.chats.length}</strong><span>общих чатов</span></div></div></div></div>`);
    if(state.organizations[0]){document.querySelector('.customer-profile-heading p').textContent=state.organizations[0].name;document.querySelector('#customer-profile-form [name="company_name"]').parentElement.innerHTML=`Компания <strong>${esc(state.organizations[0].name)}</strong><input type="hidden" name="company_name" value="${esc(p.company_name)}"><small>Состав компании управляется в разделе «Моя компания».</small>`;}
    mountPushCard();
    document.querySelector('#customer-profile-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const data=Object.fromEntries(new FormData(e.target));data.auto_approve_minutes=Math.round(Number(data.auto_approve_hours||0)*60);delete data.auto_approve_hours;state.profile=await api('/customer-profile/me',{method:'PATCH',body:JSON.stringify(data)});state.user.name=state.profile.name;state.error='';renderProfile();document.querySelector('#profile-saved').textContent='✓ Изменения сохранены';}catch(error){showError(error);}};
    return;
  }
  shell('Мой профиль','',`<div class="profile-layout"><section class="panel content profile-main"><div class="profile-heading"><div>${avatar(p,'large')}<label class="avatar-upload" for="avatar-file">Загрузить фото</label><input id="avatar-file" class="visually-hidden" type="file" aria-label="Загрузить фото профиля" accept="image/png,image/jpeg,image/webp">${p.avatar_url?'<button class="avatar-remove" id="avatar-remove">Удалить фото</button>':''}</div><div><span class="eyebrow">ПРОФИЛЬ СОТРУДНИКА</span><h2>${esc(p.name)}</h2><p>${esc([(p.functions||[p.team_role]).filter(Boolean).map(c=>state.teamWorkspace?.functions.find(f=>f.code===c)?.name||teamRoleNames[c]||c).join(', '),p.job_title].filter(Boolean).join(' · ')||'Укажите должность')}</p><small>${esc(p.email)}</small></div></div><form class="form" id="profile-form"><label>ФИО<input class="field" name="name" required minlength="2" maxlength="100" autocomplete="name" value="${esc(p.name)}"></label><label>Должность<input class="field" name="job_title" maxlength="100" placeholder="Например, ведущий разработчик" value="${esc(p.job_title)}"></label><label>О себе<textarea name="bio" maxlength="1000" placeholder="Чем вы помогаете заказчикам, ваш опыт и специализация">${esc(p.bio)}</textarea></label><div class="profile-actions"><button class="button primary">Сохранить изменения</button><span id="profile-saved" role="status"></span></div></form></section><aside class="profile-note"><span class="eyebrow">КАК ЭТО РАБОТАЕТ</span><h2>Ваш профиль для команды</h2><p>Имя, должность, описание и фотография доступны вашим коллегам. Заказчики общаются с единым контактом «Служба поддержки».</p><p>Подойдёт PNG, JPEG или WebP до 2 МБ. Изображение автоматически подстроится под кабинет.</p></aside></div>`);
  mountPushCard();
  document.querySelector('#profile-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{state.profile=await api('/profile/me',{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});state.user.name=state.profile.name;state.error='';renderProfile();document.querySelector('#profile-saved').textContent='✓ Изменения сохранены';}catch(error){showError(error);}};
  document.querySelector('#avatar-file').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;if(file.size>2_000_000){showError(new Error('Фото должно быть меньше 2 МБ'));return;}try{const dataUrl=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Не удалось прочитать файл'));reader.readAsDataURL(file);});state.profile=await api('/profile/me/avatar',{method:'POST',body:JSON.stringify({data_url:dataUrl})});await refresh();setView('profile');}catch(error){showError(error);}};
  document.querySelector('#avatar-remove')?.addEventListener('click',async()=>{try{state.profile=await api('/profile/me/avatar',{method:'DELETE'});await refresh();setView('profile');}catch(error){showError(error);}});
}
async function openMessengers(){delayedLoading('Мессенджеры','list');try{state.bots=await api('/bots');state.view='messengers';state.error='';render();}catch(error){showError(error);}}
function renderMessengers(){
  const info=state.bots;
  if(!info)return;
  const labels={telegram:'Telegram',max:'MAX',both:'Оба мессенджера',off:'Выключены'};
  const cards=info.providers.map(p=>{
    const link=info.links.find(l=>l.provider===p.provider);
    const pairing=state.pairings?.[p.provider];
    return `<section class="panel content messenger-card"><div class="messenger-header"><h2>${labels[p.provider]}</h2><span class="badge ${link?'working':'waiting'}">${link?'Подключён':p.configured?'Доступен':'Не настроен'}</span></div><p>${link?`Подключён: <strong>${esc(link.display_name)}</strong>. ${link.enabled?'Аккаунт связан с кабинетом.':'Доставка остановлена. Откройте бота и отправьте /start.'}`:p.configured?'Заявки и переписка в вашем мессенджере.':'Бот пока не настроен. После подключения администратором здесь появится кнопка.'}</p>${link?`<button class="button" data-unlink="${p.provider}">Отключить ${labels[p.provider]}</button>`:p.configured?`<button class="button primary" data-pair="${p.provider}">${pairing?'Получить новый код':'Подключить '+labels[p.provider]}</button>`:''}${pairing?`<div class="form"><p>1. <a href="${esc(pairing.url)}" target="_blank" rel="noopener noreferrer">Откройте бота</a> и отправьте ему команду ниже. Она действует 10 минут.</p><label>Команда подключения<input class="field" readonly value="${esc(pairing.command)}" aria-label="Команда подключения ${labels[p.provider]}"></label><p>2. Бот пришлёт код подтверждения. Введите его здесь, чтобы завершить подключение.</p></div>`:''}${!link&&p.configured&&(pairing||info.pending.some(x=>x.provider===p.provider))?`<form class="form" style="margin-top:18px" data-confirm="${p.provider}"><label>Код подтверждения из бота<input class="field" name="code" required minlength="6" maxlength="6" pattern="[a-fA-F0-9]{6}" autocomplete="off" placeholder="6 символов"></label><button class="button">Подтвердить подключение</button></form>`:''}</section>`;
  }).join('');
  const available=new Set(info.links.map(l=>l.provider));
  shell('Мессенджеры','',`<p class="muted">Подключите ботов к этому кабинету. Заявки и история переписки будут общими для сайта, Telegram и MAX.</p><div class="detail-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr))">${cards}</div><section class="panel content" style="margin-top:18px"><h2>Куда отправлять уведомления</h2><form class="form" id="bot-preferences"><label>Канал<select class="field" name="channel">${Object.entries(labels).map(([key,label])=>`<option value="${key}" ${key===info.channel?'selected':''} ${key==='both'?available.size<2?'disabled':'':key!=='off'&&!available.has(key)?'disabled':''}>${label}</option>`).join('')}</select></label><p class="muted">Уведомления внутри кабинета сохраняются при любом выборе.</p><button class="button primary">Сохранить</button><span id="bot-saved" role="status"></span></form></section>`);
  document.querySelectorAll('[data-pair]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const p=button.dataset.pair;const pairing=await api(`/bots/${p}/pairing`,{method:'POST'});state.pairings={...state.pairings,[p]:pairing};state.error='';renderMessengers();}catch(error){showError(error);}});
  document.querySelectorAll('[data-confirm]').forEach(form=>form.onsubmit=async event=>{event.preventDefault();form.querySelector('button').disabled=true;try{const p=form.dataset.confirm;await api(`/bots/${p}/confirm`,{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});if(state.pairings)delete state.pairings[p];await openMessengers();}catch(error){showError(error);}});
  document.querySelectorAll('[data-unlink]').forEach(button=>button.onclick=async()=>{const p=button.dataset.unlink;if(!confirm(`Отключить ${labels[p]} от кабинета? Доступ бота и доставка уведомлений прекратятся.`))return;button.disabled=true;try{await api(`/bots/${p}`,{method:'DELETE'});if(state.pairings)delete state.pairings[p];await openMessengers();}catch(error){showError(error);}});
  document.querySelector('#bot-preferences').onsubmit=async event=>{event.preventDefault();const form=event.target;form.querySelector('button').disabled=true;try{await api('/bots/preferences',{method:'PUT',body:JSON.stringify(Object.fromEntries(new FormData(form)))});state.bots.channel=form.elements.channel.value;document.querySelector('#bot-saved').textContent='Настройки сохранены';}catch(error){showError(error);}finally{form.querySelector('button').disabled=false;}};
}
function renderCredentials(){
  app.innerHTML = `<main class="auth-main"><section class="auth-card"><h1>Замените временные данные</h1><p class="lead">Укажите свой email и новый пароль. После сохранения откроется кабинет вашей компании.</p>${notice()}<form class="form" id="credentials-form"><label>Ваш email<input class="field" name="email" type="email" autocomplete="email" required maxlength="254"></label><label>Временный пароль<input class="field" name="current_password" type="password" autocomplete="current-password" required minlength="8" maxlength="128"></label><label>Новый пароль<input class="field" name="password" type="password" autocomplete="new-password" required minlength="8" maxlength="128"></label><label>Повторите новый пароль<input class="field" name="confirm_password" type="password" autocomplete="new-password" required minlength="8" maxlength="128"></label><button class="button primary">Сохранить и открыть кабинет</button></form><button class="button" id="credentials-logout" type="button">Выйти</button></section></main>`;
  document.querySelector('#credentials-logout').onclick=async()=>{await api('/logout',{method:'POST'});state.user=null;resetAccountState();initRealtime();state.error='';render();};
  document.querySelector('#credentials-form').onsubmit=async e=>{
    e.preventDefault();const form=e.target;const button=form.querySelector('button');const data=Object.fromEntries(new FormData(form));
    if(data.password!==data.confirm_password){state.error='Новые пароли не совпадают';const noticeBox=document.createElement('div');noticeBox.className='notice';noticeBox.setAttribute('role','alert');noticeBox.textContent=state.error;form.querySelector('.notice')?.remove();form.prepend(noticeBox);return;}
    delete data.confirm_password;button.disabled=true;
    try{state.user=await api('/account/credentials',{method:'POST',body:JSON.stringify(data)});state.error='';await refresh();await openHash();initRealtime();}
    catch(error){form.querySelector('.notice')?.remove();const box=document.createElement('div');box.className='notice';box.setAttribute('role','alert');box.textContent=error.message;form.prepend(box);button.disabled=false;}
  };
}

function renderOrganizations(){
  const dispatcher=isDispatcher();
  const owns=org=>dispatcher||org.members.some(m=>m.user_id===state.user.id&&m.role==='owner');
  const cards=state.organizations.map(org=>{const manage=owns(org);return `<section class="panel content organization-card" data-org-card="${org.id}"><div class="row org-card-heading"><div class="org-company-name"><span class="org-company-icon" aria-hidden="true">${icon('building',20)}</span><h2>${esc(org.name)}</h2></div><span class="badge">${org.members.length} ${plural(org.members.length,['участник','участника','участников'])}</span></div>${!org.has_available_owner?`<div class="notice">Нет владельца с действующим доступом. ${manage?'Назначьте активного участника владельцем или пригласите нового.':'Откройте общую заявку и отправьте запрос менеджеру на восстановление согласования.'}</div>`:''}<div class="org-members">${org.members.map(m=>`<div class="team-person org-person"><span class="org-member-identity">${avatar(m,'small')}<span><strong>${esc(m.name)}</strong><small>${esc(m.email)}${m.must_change_credentials?' · ждём активацию':''}${!m.active?' · доступ отключён':''}</small></span></span>${manage?`<span class="org-person-actions"><select class="field" data-member-role="${m.user_id}" data-org="${org.id}" aria-label="Роль ${esc(m.name)}">${['owner','member','viewer'].map(role=>`<option value="${role}" ${m.role===role?'selected':''}>${{owner:'Владелец',member:'Участник',viewer:'Наблюдатель'}[role]}</option>`).join('')}</select><button class="button" data-remove-member="${m.user_id}" data-org="${org.id}" aria-label="Удалить ${esc(m.name)} из компании">${icon('close',16)}</button></span>`:`<span class="badge">${{owner:'Владелец',member:'Участник',viewer:'Наблюдатель'}[m.role]}</span>`}</div>`).join('')}</div>${manage?`<details class="estimate-inline"><summary>Добавить участника</summary><div data-invite-host="${org.id}"></div></details>`:''}${dispatcher?org.members.filter(m=>m.must_change_credentials&&m.email.endsWith('@access.local')).map(m=>`<section class="content"><p>Временный доступ: ${esc(m.name)} · до ${date(m.temporary_credentials_expires_at)}</p><button class="button" data-renew-owner="${m.user_id}" ${m.active?'':'disabled data-permanently-disabled="true"'}>Выдать новые временные данные</button><div data-owner-access="${m.user_id}" role="status"></div></section>`).join(''):''}</section>`;}).join('');
  const managed=state.organizations.some(owns);
  const memberCount=state.organizations.reduce((total,org)=>total+org.members.length,0);
  const roles=`<details class="org-role-guide"><summary>Как устроены роли и доступ</summary><dl><div><dt>Владелец</dt><dd>Согласует оценки и общие работы компании.</dd></div><div><dt>Участник</dt><dd>Создаёт заявки и ведёт переписку.</dd></div><div><dt>Наблюдатель</dt><dd>Читает общие заявки без внесения изменений.</dd></div></dl></details>`;
  shell(dispatcher?'Компании и клиенты':'Моя компания',dispatcher?`<button class="button primary" id="org-add-client">${icon('plus',16)}Добавить клиента</button>`:'',`<div class="organizations-workspace"><div class="org-summary"><span><strong>${state.organizations.length}</strong> ${plural(state.organizations.length,['компания','компании','компаний'])}</span><span><strong>${memberCount}</strong> ${plural(memberCount,['участник','участника','участников'])}</span><span class="muted">Общие заявки и доступ клиентов</span></div><div class="org-layout"><div class="org-directory"><div class="org-directory-toolbar"><h2>Компании <span class="muted" id="org-search-count">${state.organizations.length}</span></h2><label class="org-search">${icon('search',16)}<input type="search" id="org-search" aria-label="Поиск компании или участника" placeholder="Компания, имя или email" value="${esc(state.organizationSearch||'')}"></label></div><div class="org-grid">${cards||'<section class="panel content empty"><h2>Компаний пока нет</h2><p>Добавьте клиента и укажите компанию, чтобы объединить заявки и участников.</p></section>'}</div><section class="panel content empty" id="org-no-results" hidden><h2>Ничего не найдено</h2><p>Попробуйте другое название, имя или email.</p></section>${dispatcher||managed?'<section class="panel content org-invitations"><h2>Приглашения и доступ</h2><p class="muted">Активация кабинетов и доставка приглашений.</p><div id="invitation-list">Загружаем статусы…</div></section>':''}</div><aside class="org-sidebar">${dispatcher?'<section class="panel content org-create"><span class="eyebrow">Новый контакт</span><h2>Добавить клиента</h2><div data-invite-host="new"></div></section>':''}${roles}</aside></div></div>`,{kicker:'Клиенты и доступ',lead:'Управляйте компаниями, участниками и приглашениями в кабинет.'});
  const search=document.querySelector('#org-search');
  const filterCompanies=()=>{state.organizationSearch=search.value;const query=search.value.trim().toLocaleLowerCase('ru');let count=0;document.querySelectorAll('[data-org-card]').forEach(card=>{const org=state.organizations.find(o=>String(o.id)===card.dataset.orgCard);const text=[org.name,...org.members.flatMap(m=>[m.name,m.email])].join(' ').toLocaleLowerCase('ru');card.hidden=!text.includes(query);if(!card.hidden)count++;});document.querySelector('#org-no-results').hidden=!query||count>0;document.querySelector('#org-search-count').textContent=count;};
  search.addEventListener('input',filterCompanies);filterCompanies();
  document.querySelector('#org-add-client')?.addEventListener('click',()=>{const input=document.querySelector('[data-invite-host="new"] input');input?.scrollIntoView({block:'center',behavior:'smooth'});input?.focus({preventScroll:true});});
  state.organizations.filter(owns).forEach(org=>mountCustomerInvitation(document.querySelector(`[data-invite-host="${org.id}"]`),org.id));
  if(dispatcher)mountCustomerInvitation(document.querySelector('[data-invite-host="new"]'));
  mountInvitationList();
  document.querySelectorAll('[data-member-role]').forEach(select=>{const original=select.value;select.onchange=async()=>{try{await api(`/organizations/${select.dataset.org}/members/${select.dataset.memberRole}`,{method:'PATCH',body:JSON.stringify({role:select.value})});await refresh();}catch(error){select.value=original;showError(error);}};});
  document.querySelectorAll('[data-remove-member]').forEach(button=>button.onclick=async()=>{if(!confirm('Убрать участника из компании? Доступ к общим заявкам прекратится.'))return;try{await api(`/organizations/${button.dataset.org}/members/${button.dataset.removeMember}`,{method:'DELETE'});await refresh();}catch(error){showError(error);}});
  document.querySelectorAll('[data-renew-owner]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const access=await api(`/company-owners/${button.dataset.renewOwner}/temporary-access`,{method:'POST'});const host=document.querySelector(`[data-owner-access="${button.dataset.renewOwner}"]`);host.innerHTML=`<label>Временный логин<input class="field" readonly value="${esc(access.login)}"></label><label>Временный пароль<input class="field" readonly value="${esc(access.temporary_password)}"></label><p>До ${date(access.expires_at)}. Сохраните данные и передайте владельцу.</p>`;state.organizations=await api('/organizations');}catch(error){showError(error);}finally{button.disabled=false;}});
}


async function openSpecialists() {
  setView('specialists');
  try {
    state.specialists = await api('/customer/specialists');
    render();
  } catch (error) {
    showError(error);
  }
}

function renderSpecialists() {
  const list = state.specialists || [];
  const empty = `<div class="empty">
    <h3>Специалисты пока не назначены</h3>
    <p>Здесь появятся сотрудники службы поддержки, кураторы и инженеры, закреплённые за вашей компанией или назначенные на ваши заявки.</p>
  </div>`;

  const cards = list.map(s => {
    const responsibilitiesHtml = (s.responsibilities && s.responsibilities.length)
      ? `<div class="specialist-tags">
          <span class="muted">Направления:</span>
          ${s.responsibilities.map(r => `<span class="badge role">${esc(r)}</span>`).join('')}
         </div>`
      : '';

    const functionsHtml = (s.functions && s.functions.length)
      ? `<div class="specialist-tags">
          <span class="muted">Компетенции:</span>
          ${s.functions.map(f => `<span class="badge">${esc(f)}</span>`).join('')}
         </div>`
      : '';

    const ticketsHtml = (s.tickets && s.tickets.length)
      ? `<div class="specialist-tickets">
          <h4>Заявки с участием специалиста (${s.tickets.length})</h4>
          <ul class="specialist-ticket-list">
            ${s.tickets.map(t => `
              <li class="specialist-ticket-item">
                <div class="row" style="gap:8px;align-items:center;">
                  <span class="badge ${esc(t.status)}">${statusNames[t.status] || t.status}</span>
                  <span class="badge priority-${esc(t.priority || 'normal')}">${esc(priorityNames[t.priority] || 'Обычный')}</span>
                  <span class="specialist-role-tag">${esc(t.role)}</span>
                </div>
                <button type="button" class="link-button specialist-ticket-title" data-open-ticket="${t.id}">
                  №${t.id} · ${esc(t.title)}
                </button>
              </li>
            `).join('')}
          </ul>
         </div>`
      : '<p class="muted">Сейчас нет активных заявок с участием этого специалиста.</p>';

    return `
      <section class="panel content specialist-card" data-specialist-id="${s.id}">
        <div class="specialist-header">
          ${avatar(s, 'large')}
          <div class="specialist-info">
            <span class="eyebrow">${esc(s.job_title || 'Специалист команды')}</span>
            <h2>${esc(s.name)}</h2>
            ${s.bio ? `<p class="specialist-bio">${esc(s.bio)}</p>` : ''}
            ${responsibilitiesHtml}
            ${functionsHtml}
          </div>
        </div>
        ${ticketsHtml}
      </section>
    `;
  }).join('');

  shell('Наша команда', '', `<div class="specialists-container">${list.length ? `<div class="specialists-grid">${cards}</div>` : empty}</div>`, { kicker: 'Сотрудники, работающие с вами' });

  document.querySelectorAll('[data-open-ticket]').forEach(btn => {
    btn.onclick = () => openTicket(Number(btn.dataset.openTicket));
  });
}

async function openAnalytics(){
  setView('analytics');
  try{
    state.analytics=await api('/analytics/summary');
    renderAnalytics();
  }catch(err){
    showError(err);
  }
}
function renderAnalytics() {
  if (!state.analytics) {
    shell('Аналитика и SLA', '', skeleton('analytics'), { kicker: 'Сроки, качество и нагрузка' });
    return;
  }
  const a = state.analytics;
  const target = 90;
  const pct = value => Math.round(Number(value) || 0);
  const frt = a.avg_response_minutes < 60 ? `${a.avg_response_minutes} мин` : `${(a.avg_response_minutes / 60).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч`;
  const stat = (label, value, hint, cls = '') => `<div class="stat ${cls}"><span class="stat-label">${label}</span><strong>${value}</strong><small>${hint}</small></div>`;
  const goal = value => pct(value) >= target ? `<span class="trend-up">цель ${target}% достигнута</span>` : `<span class="trend-down">ниже цели ${target}%</span>`;
  const stats = `<div class="stats five">${stat('Всего заявок', a.total_tickets, `${a.open_tickets} в работе · ${a.done_tickets} закрыто`)}${stat('Первый ответ', frt, `в срок ${pct(a.sla_response_met_pct)}%`)}${stat('Оценка в срок', `${pct(a.sla_estimate_met_pct)}%`, goal(a.sla_estimate_met_pct))}${stat('Сдача в срок', `${pct(a.sla_delivery_met_pct)}%`, goal(a.sla_delivery_met_pct))}${stat('Оценка клиентов', a.avg_csat ? `${String(a.avg_csat).replace('.', ',')} из 5` : '—', `${a.total_ratings} ${plural(a.total_ratings, ['отзыв', 'отзыва', 'отзывов'])}`)}</div>`;
  const meter = (label, value, hint) => `<div class="sla-meter"><div class="sla-meter-head"><span>${label}</span><strong>${pct(value)}%</strong></div><div class="sla-meter-track" role="img" aria-label="${label}: ${pct(value)}% при цели ${target}%"><span class="${pct(value) < target ? 'below' : ''}" style="width:${Math.min(100, pct(value))}%"></span><i style="left:${target}%"></i></div><small>${hint}</small></div>`;
  const staffRows = (a.staff_stats || []).map(s => `<tr><td><div class="person-cell">${avatar(personById(s.id) || { name: s.name }, 'small')}<div><strong>${esc(s.name)}</strong><small>${esc(s.job_title || '')}</small></div></div></td><td class="num"><strong>${s.active_tickets}</strong></td><td class="num">${s.closed_tickets}</td><td class="num"><strong>${hours(s.logged_minutes)}</strong></td><td class="num">${s.avg_rating ? `<span class="rating">★ ${s.avg_rating}</span>` : '<span class="muted">—</span>'}</td></tr>`).join('');
  const csatTotal = a.total_ratings || 1;
  const csatBars = [5, 4, 3, 2, 1].map(stars => { const count = a.csat_distribution?.[stars] || 0; return `<div class="csat-bar-row"><span>${stars} ★</span><div class="meter"><span class="${stars <= 2 ? 'soon' : ''}" style="width:${Math.round(count / csatTotal * 100)}%"></span></div><span>${count}</span></div>`; }).join('');
  const colors = ['#137b69', '#3a7fc4', '#d99a2b', '#8a6bc4', '#a9bdb7'];
  const services = Object.entries(a.service_breakdown || {});
  const servicesTotal = services.reduce((sum, [, count]) => sum + count, 0) || 1;
  const serviceBar = services.map(([, count], index) => `<span style="width:${count / servicesTotal * 100}%;background:${colors[index % colors.length]}"></span>`).join('');
  const serviceRows = services.map(([key, count], index) => `<span><b style="background:${colors[index % colors.length]}"></b>${esc(serviceLabel(key))}</span><strong>${count}</strong>`).join('');
  const feedback = (a.recent_feedback || []).map(f => `<div class="activity-item"><span class="activity-dot fresh"></span><div><div class="row" style="justify-content:space-between"><strong>№${f.ticket_id} · ${esc(f.customer_name)}</strong><span class="rating">★ ${f.rating}</span></div>${f.comment ? `<p>«${esc(f.comment)}»</p>` : ''}<small>${date(f.rated_at)}</small></div></div>`).join('');
  const body = `${stats}<div class="split"><div class="context-stack"><section class="panel content"><div class="card-head"><h2>Соблюдение SLA</h2><span class="legend"><span><b style="background:var(--accent)"></b>цель достигнута</span><span><b style="background:#d99a2b"></b>ниже цели</span></span></div><div class="sla-meters">${meter('Первый ответ', a.sla_response_met_pct, `Среднее время первого ответа — ${frt}`)}${meter('Подготовка оценки', a.sla_estimate_met_pct, 'Оценка трудозатрат отправлена до срока')}${meter('Сдача работы', a.sla_delivery_met_pct, 'Заявка завершена до дедлайна')}</div></section><section class="panel"><div class="toolbar"><strong>Нагрузка и результаты команды</strong></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Сотрудник</th><th class="num">В работе</th><th class="num">Закрыто</th><th class="num">Списано</th><th class="num">Отзывы</th></tr></thead><tbody>${staffRows || '<tr><td colspan="5" class="muted">Нет данных</td></tr>'}</tbody></table></div></section></div><div class="context-stack"><section class="panel content"><div class="card-head"><h2>Оценки клиентов</h2><span class="muted">${a.total_ratings} ${plural(a.total_ratings, ['отзыв', 'отзыва', 'отзывов'])}</span></div><div class="csat-bars">${csatBars}</div></section><section class="panel content"><h2>Заявки по типам</h2>${services.length ? `<div class="stack-bar">${serviceBar}</div><div class="service-list">${serviceRows}</div>` : '<p class="muted">Пока нет данных</p>'}</section>${feedback ? `<section class="activity-panel"><div class="activity-heading"><h2>Последние отзывы</h2><span>${(a.recent_feedback || []).length}</span></div>${feedback}</section>` : ''}</div></div>`;
  shell('Аналитика и SLA', `<a class="button" href="/api/analytics/export.csv" download>${icon('download', 16)}Отчёт CSV</a>`, body, { kicker: 'Сроки, качество и нагрузка', lead: 'Сводка по соблюдению SLA, оценкам клиентов и работе команды' });
}
function renderGitLinksPanel(ticketId, staff) {
  const links = state.gitLinks || [];
  return `
    <section class="panel content git-panel">
      <div class="row" style="align-items:center;margin-bottom:10px">
        <h2>Git & Релизы</h2>
        <span class="badge">${links.length}</span>
      </div>
      <div class="git-links-list">
        ${links.map(g => `
          <div class="git-link-item">
            <div class="git-link-main">
              <span class="git-pill ${esc(g.ref_type)}">${g.ref_type === 'pr' ? 'PR' : g.ref_type === 'commit' ? 'Commit' : 'Branch'}</span>
              <div class="git-link-text">
                <a href="${esc(g.url)}" target="_blank" rel="noopener noreferrer">
                  ${esc(g.repo)} · <strong>${esc(g.ref_id)}</strong> ↗
                </a>
                ${g.title ? `<div style="font-size:12px;color:var(--muted)">${esc(g.title)}</div>` : ''}
                <small class="muted">${esc(g.author_name)} · ${date(g.created_at)}</small>
              </div>
            </div>
            ${staff ? `<button type="button" class="git-delete-btn" data-delete-git="${g.id}" title="Удалить">×</button>` : ''}
          </div>
        `).join('') || '<p class="muted" style="font-size:13px">К этой заявке пока не привязаны ветки или пулл-реквесты.</p>'}
      </div>
      ${staff ? `
        <details style="margin-top:12px;font-size:13px">
          <summary style="cursor:pointer;font-weight:700;color:var(--accent)">+ Привязать ветку / PR / коммит</summary>
          <form class="form" id="git-link-form" style="margin-top:10px">
            <label>Репозиторий<input class="field" name="repo" required placeholder="например: backend / frontend"></label>
            <label>Тип ссылки
              <select class="field" name="ref_type">
                <option value="branch">Ветка (branch)</option>
                <option value="pr">Пулл-реквест (PR)</option>
                <option value="commit">Коммит (commit)</option>
              </select>
            </label>
            <label>Идентификатор<input class="field" name="ref_id" required placeholder="например: feat/billing-v2 или PR #14"></label>
            <label>URL ссылки<input class="field" name="url" required type="url" placeholder="https://github.com/..."></label>
            <label>Комментарий / Описание (необязательно)<input class="field" name="title" placeholder="Краткая суть изменений"></label>
            <button class="button primary" style="margin-top:6px">Привязать к заявке</button>
          </form>
        </details>
      ` : ''}
    </section>
  `;
}

async function loadGitLinks(ticketId) {
  try {
    state.gitLinks = await api(`/tickets/${ticketId}/git-links`);
    const container = document.querySelector('#git-links-container');
    if (container) {
      container.innerHTML = renderGitLinksPanel(ticketId, state.user.role !== 'customer');
      attachGitLinkHandlers(ticketId);
    }
  } catch(e) {}
}

function attachGitLinkHandlers(ticketId) {
  const form = document.querySelector('#git-link-form');
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const data = {
      repo: fd.get('repo'),
      ref_type: fd.get('ref_type'),
      ref_id: fd.get('ref_id'),
      url: fd.get('url'),
      title: fd.get('title') || ''
    };
    e.target.querySelector('button').disabled = true;
    try {
      await api(`/tickets/${ticketId}/git-links`, {
        method: 'POST',
        body: JSON.stringify(data)
      });
      await loadGitLinks(ticketId);
    } catch(err) {
      showError(err);
      e.target.querySelector('button').disabled = false;
    }
  });

  document.querySelectorAll('[data-delete-git]').forEach(btn => {
    btn.onclick = async () => {
      const linkId = Number(btn.dataset.deleteGit);
      if (!confirm('Удалить привязку к Git?')) return;
      try {
        await api(`/tickets/${ticketId}/git-links/${linkId}`, { method: 'DELETE' });
        await loadGitLinks(ticketId);
      } catch(err) {
        showError(err);
      }
    };
  });
}

async function openKb() {
  state.kbLoading = true;
  state.kbReadingArticle = null;
  state.kbEditingArticle = null;
  setView('kb');
  try {
    state.kbCategories = await api('/kb/categories');
    state.kbArticles = await api('/kb/articles' + (state.kbActiveCategory ? `?category_id=${state.kbActiveCategory}` : ''));
    state.kbReadingArticle = null;
    state.kbEditingArticle = null;
    state.kbLoading = false;
    renderKb();
  } catch(e) {
    state.kbLoading = false;
    showError(e);
  }
}

async function readKbArticle(articleId) {
  try {
    const article = await api(`/kb/articles/${articleId}`);
    state.kbReadingArticle = article;
    state.kbEditingArticle = null;
    setView('kb');
    renderKb();
  } catch(e) {
    showError(e);
  }
}

function renderKb() {
  const staff = state.user.role !== 'customer';
  if (state.kbEditingArticle) {
    return renderKbEditor();
  }
  if (state.kbReadingArticle) {
    return renderKbReader();
  }
  if (state.kbLoading && !(state.kbArticles || []).length) {
    shell('База знаний и регламенты', '', skeleton('cards'));
    return;
  }

  const allCount = (state.kbCategories || []).reduce((sum, c) => sum + (c.article_count || 0), 0);
  const chips = [
    `<button class="kb-chip ${state.kbActiveCategory === null ? 'active' : ''}" data-kb-cat="all">Все статьи <span class="kb-chip-count">${allCount}</span></button>`,
    ...(state.kbCategories || []).map(c => `
      <button class="kb-chip ${state.kbActiveCategory === c.id ? 'active' : ''}" data-kb-cat="${c.id}">
        ${esc(c.name)} <span class="kb-chip-count">${c.article_count}</span>
      </button>
    `)
  ].join('');

  const articles = state.kbArticles || [];
  const q = (state.kbSearch || '').trim().toLowerCase();
  const filtered = q ? articles.filter(a => a.title.toLowerCase().includes(q) || a.content.toLowerCase().includes(q)) : articles;

  const cards = filtered.map(a => `
    <article class="kb-card" data-read-article="${a.id}">
      <div class="kb-card-head">
        <span class="kb-cat-badge">${esc(a.category_name)}</span>
        ${a.is_internal ? '<span class="kb-internal-badge">Только для команды</span>' : ''}
      </div>
      <h3 class="kb-card-title">${esc(a.title)}</h3>
      <p class="kb-card-snippet">${esc(a.snippet)}</p>
      <div class="kb-card-foot">
        <span>${a.views_count} ${plural(a.views_count,['просмотр','просмотра','просмотров'])}</span>
        <span>Полезно: ${a.helpful_yes} · Нет: ${a.helpful_no}</span>
      </div>
    </article>
  `).join('');

  const topAction = staff ? `<button class="button primary" id="kb-create-btn">+ Создать статью</button>` : '';

  const body = `
    <div class="kb-topbar">
      <div class="kb-search-wrap">
        <input class="field" id="kb-search-input" type="search" placeholder="Поиск по статьям и инструкциям..." value="${esc(state.kbSearch || '')}">
      </div>
    </div>
    <div class="kb-cat-chips">${chips}</div>
    <div class="kb-grid">
      ${cards || '<div class="empty"><strong>Статей не найдено</strong>Попробуйте изменить категорию или поисковый запрос.</div>'}
    </div>
  `;

  shell('База знаний и регламенты', topAction, body);

  document.querySelector('#kb-create-btn')?.addEventListener('click', () => {
    state.kbEditingArticle = { id: null, category_id: state.kbCategories[0]?.id || 1, title: '', content: '', is_internal: false };
    renderKb();
  });

  document.querySelectorAll('[data-kb-cat]').forEach(btn => {
    btn.onclick = async () => {
      const cat = btn.dataset.kbCat === 'all' ? null : Number(btn.dataset.kbCat);
      state.kbActiveCategory = cat;
      state.kbArticles = await api('/kb/articles' + (cat ? `?category_id=${cat}` : ''));
      renderKb();
    };
  });

  const searchInput = document.querySelector('#kb-search-input');
  if (searchInput) {
    searchInput.oninput = (e) => {
      state.kbSearch = e.target.value;
      const qVal = state.kbSearch.trim().toLowerCase();
      const list = qVal ? state.kbArticles.filter(a => a.title.toLowerCase().includes(qVal) || a.content.toLowerCase().includes(qVal)) : state.kbArticles;
      const container = document.querySelector('.kb-grid');
      if (container) {
        container.innerHTML = list.map(a => `
          <article class="kb-card" data-read-article="${a.id}">
            <div class="kb-card-head">
              <span class="kb-cat-badge">${esc(a.category_name)}</span>
              ${a.is_internal ? '<span class="kb-internal-badge">Только для команды</span>' : ''}
            </div>
            <h3 class="kb-card-title">${esc(a.title)}</h3>
            <p class="kb-card-snippet">${esc(a.snippet)}</p>
            <div class="kb-card-foot">
              <span>${a.views_count} ${plural(a.views_count,['просмотр','просмотра','просмотров'])}</span>
              <span>Полезно: ${a.helpful_yes} · Нет: ${a.helpful_no}</span>
            </div>
          </article>
        `).join('') || '<div class="empty"><strong>Статей не найдено</strong>Попробуйте изменить поисковый запрос.</div>';
        container.querySelectorAll('[data-read-article]').forEach(c => {
          c.onclick = () => readKbArticle(Number(c.dataset.readArticle));
        });
      }
    };
  }

  document.querySelectorAll('[data-read-article]').forEach(c => {
    c.onclick = () => readKbArticle(Number(c.dataset.readArticle));
  });
}

function renderKbReader() {
  const a = state.kbReadingArticle;
  const staff = state.user.role !== 'customer';
  const actions = `
    <div style="display:flex;gap:8px">
      <button class="button" id="kb-back-btn">← Все статьи</button>
      ${staff ? `<button class="button" id="kb-edit-btn">Редактировать</button><button class="button" id="kb-delete-btn" style="color:var(--late)">Удалить</button>` : ''}
    </div>
  `;
  const body = `
    <div class="kb-reader">
      <div style="margin-bottom:14px;display:flex;gap:8px;align-items:center">
        <span class="kb-cat-badge">${esc(a.category_name)}</span>
        ${a.is_internal ? '<span class="kb-internal-badge">Внутренний регламент команды</span>' : ''}
        <small class="muted" style="margin-left:auto">${date(a.updated_at)} · ${a.views_count} ${plural(a.views_count,['просмотр','просмотра','просмотров'])}</small>
      </div>
      <section class="panel content">
        <h1 style="font-size:24px;font-weight:800;margin-bottom:16px">${esc(a.title)}</h1>
        <div class="kb-reader-body">${esc(a.content)}</div>
        <div class="kb-feedback-box" id="kb-feedback-box">
          <div>
            <strong>Была ли эта статья полезна?</strong>
            <div class="muted" style="font-size:12px;margin-top:2px">Ваша оценка помогает улучшать базу знаний</div>
          </div>
          <div class="kb-feedback-actions">
            <button class="kb-feedback-btn" id="kb-vote-yes">Да (${a.helpful_yes})</button>
            <button class="kb-feedback-btn" id="kb-vote-no">Нет (${a.helpful_no})</button>
          </div>
        </div>
      </section>
    </div>
  `;
  shell(a.title, actions, body);
  document.querySelector('#kb-back-btn')?.addEventListener('click', () => {
    state.kbReadingArticle = null;
    openKb();
  });
  document.querySelector('#kb-edit-btn')?.addEventListener('click', () => {
    state.kbEditingArticle = { ...a };
    renderKb();
  });
  document.querySelector('#kb-delete-btn')?.addEventListener('click', async () => {
    if (!confirm('Удалить эту статью из базы знаний?')) return;
    try {
      await api(`/kb/articles/${a.id}`, { method: 'DELETE' });
      state.kbReadingArticle = null;
      await openKb();
    } catch(err) {
      showError(err);
    }
  });
  const vote = async (helpful) => {
    try {
      const res = await api(`/kb/articles/${a.id}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ helpful })
      });
      document.querySelector('#kb-feedback-box').innerHTML = `<span style="color:var(--accent-ink);font-weight:700">✓ Спасибо за обратную связь!</span><div class="muted" style="font-size:12px">Полезно: ${res.helpful_yes} · Нет: ${res.helpful_no}</div>`;
    } catch(err) {
      showError(err);
    }
  };
  document.querySelector('#kb-vote-yes')?.addEventListener('click', () => vote(true));
  document.querySelector('#kb-vote-no')?.addEventListener('click', () => vote(false));
}

function renderKbEditor() {
  const a = state.kbEditingArticle;
  const isNew = !a.id;
  const body = `
    <div class="kb-reader">
      <button class="button" id="kb-cancel-edit" style="margin-bottom:16px">← Отмена</button>
      <section class="panel content">
        <h2>${isNew ? 'Новая статья базы знаний' : 'Редактирование статьи'}</h2>
        <form class="form" id="kb-editor-form">
          <label>Категория
            <select class="field" name="category_id" required>
              ${state.kbCategories.map(c => `<option value="${c.id}" ${c.id === a.category_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
            </select>
          </label>
          <label>Заголовок статьи
            <input class="field" name="title" required minlength="3" maxlength="200" value="${esc(a.title)}" placeholder="Например: Как передать доступы к API">
          </label>
          <label>Текст статьи / инструкции
            <textarea name="content" required minlength="5" style="min-height:240px" placeholder="Опишите шаги, регламент или решение проблемы...">${esc(a.content)}</textarea>
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-weight:600">
            <input type="checkbox" name="is_internal" ${a.is_internal ? 'checked' : ''}>
            <span>Только для команды (скрыть от заказчиков)</span>
          </label>
          <div style="display:flex;gap:10px;margin-top:14px">
            <button class="button primary">Сохранить статью</button>
            <button type="button" class="button" id="kb-cancel-form">Отмена</button>
          </div>
        </form>
      </section>
    </div>
  `;
  shell(isNew ? 'Новая статья' : 'Редактирование', '', body);
  const cancel = () => {
    state.kbEditingArticle = null;
    renderKb();
  };
  document.querySelector('#kb-cancel-edit')?.addEventListener('click', cancel);
  document.querySelector('#kb-cancel-form')?.addEventListener('click', cancel);
  document.querySelector('#kb-editor-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const data = {
      category_id: Number(fd.get('category_id')),
      title: fd.get('title'),
      content: fd.get('content'),
      is_internal: fd.get('is_internal') === 'on'
    };
    e.target.querySelector('button.primary').disabled = true;
    try {
      if (isNew) {
        const created = await api('/kb/articles', { method: 'POST', body: JSON.stringify(data) });
        state.kbEditingArticle = null;
        await readKbArticle(created.id);
      } else {
        const updated = await api(`/kb/articles/${a.id}`, { method: 'PATCH', body: JSON.stringify(data) });
        state.kbEditingArticle = null;
        await readKbArticle(updated.id);
      }
    } catch(err) {
      showError(err);
      e.target.querySelector('button.primary').disabled = false;
    }
  });
}

async function openWebhooks() {
  state.webhooksLoading = true;
  setView('webhooks');
  try {
    state.webhooks = await api('/webhooks');
    state.webhooksLoading = false;
    renderWebhooks();
  } catch(err) {
    showError(err);
  }
}

function renderWebhooks() {
  const list = state.webhooks || [];
  if (state.webhooksLoading && !list.length) { shell('Вебхуки и интеграции', '', skeleton('list')); return; }
  const allEvents = [
    ['ticket.created', 'Создание заявки'],
    ['ticket.status_changed', 'Смена статуса заявки'],
    ['estimate.decided', 'Решение по оценке'],
    ['internal_note.created', 'Внутренняя заметка'],
    ['ticket.rated', 'Оценка CSAT'],
  ];

  const cards = list.map(w => `
    <div class="webhook-card" id="webhook-${w.id}">
      <div class="webhook-card-head">
        <div>
          <div class="webhook-url">${esc(w.url)}</div>
          ${w.description ? `<div style="font-size:13px;color:var(--muted);margin-top:2px">${esc(w.description)}</div>` : ''}
        </div>
        <span class="badge ${w.is_active ? 'working' : 'closed'}">${w.is_active ? 'Активен' : 'Отключен'}</span>
      </div>
      <div class="webhook-events-list">
        ${(w.events || []).map(ev => `<span class="webhook-ev-badge">${esc(ev)}</span>`).join('')}
      </div>
      <div style="font-size:12px;color:var(--muted);margin-top:6px">
        <span>Секретный ключ (HMAC): <code>${esc(w.secret.slice(0, 6))}••••••••</code></span> ·
        <span>Доставок: <strong>${w.total_deliveries}</strong></span>
        ${w.last_status_code ? ` · Код: <strong>${w.last_status_code}</strong>` : ''}
      </div>
      <div class="webhook-actions">
        <button class="button small-btn" data-wh-test="${w.id}">Тестовый запрос</button>
        <button class="button small-btn" data-wh-toggle="${w.id}">${w.is_active ? 'Приостановить' : 'Активировать'}</button>
        <button class="button small-btn" data-wh-logs="${w.id}">Журнал доставок</button>
        <button class="button small-btn" data-wh-delete="${w.id}" style="color:var(--late);margin-left:auto">Удалить</button>
      </div>
      <div class="webhook-logs-drawer" id="wh-logs-${w.id}" style="display:none"></div>
    </div>
  `).join('');

  const body = `
    <div class="workspace-grid">
      <div class="panel content">
        <div class="row" style="margin-bottom:12px">
          <h2>Настроенные вебхуки</h2>
          <span class="badge">${list.length}</span>
        </div>
        <p class="muted" style="font-size:13.5px;margin-bottom:16px">
          Поддержка HMAC-SHA256 подписи в заголовке <code>X-Signature-SHA256</code> для безопасной интеграции с CI/CD, CRM и мессенджерами.
        </p>
        <div class="webhooks-list">
          ${cards || '<div class="empty"><strong>Вебхуков пока нет</strong>Добавьте первый URL для отправки системных событий.</div>'}
        </div>
      </div>
      <div class="context-stack">
        <section class="panel content">
          <h2>+ Добавить вебхук</h2>
          <form class="form" id="create-webhook-form" style="margin-top:12px">
            <label>URL обработчика (Endpoint)
              <input class="field" name="url" required type="url" placeholder="https://api.yourdomain.com/webhook">
            </label>
            <label>Описание (необязательно)
              <input class="field" name="description" placeholder="например: Telegram бот оповещений или Jira Sync">
            </label>
            <label>Секретный ключ (опционально)
              <input class="field" name="secret" placeholder="Оставьте пустым для автогенерации">
            </label>
            <label>События для подписки:
              <div style="display:flex;flex-direction:column;gap:6px;margin-top:6px;font-size:13px">
                ${allEvents.map(([ev, label]) => `
                  <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                    <input type="checkbox" name="events" value="${ev}" ${['ticket.created','ticket.status_changed'].includes(ev)?'checked':''}>
                    <span><code>${ev}</code> — ${label}</span>
                  </label>
                `).join('')}
              </div>
            </label>
            <button class="button primary" style="margin-top:10px">Подключить вебхук</button>
          </form>
        </section>
      </div>
    </div>
  `;

  shell('Вебхуки и интеграции (DevOps Gateway)', '', body);

  document.querySelector('#create-webhook-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const checkedEvents = fd.getAll('events');
    if (!checkedEvents.length) {
      alert('Выберите хотя бы одно событие для подписки');
      return;
    }
    const data = {
      url: fd.get('url'),
      description: fd.get('description'),
      secret: fd.get('secret') || null,
      events: checkedEvents
    };
    e.target.querySelector('button').disabled = true;
    try {
      await api('/webhooks', { method: 'POST', body: JSON.stringify(data) });
      await openWebhooks();
    } catch(err) {
      showError(err);
      e.target.querySelector('button').disabled = false;
    }
  });

  document.querySelectorAll('[data-wh-test]').forEach(btn => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.whTest);
      btn.disabled = true;
      btn.textContent = 'Отправка...';
      try {
        const res = await api(`/webhooks/${id}/test`, { method: 'POST' });
        btn.textContent = res.log?.status_code ? `✓ Код ${res.log.status_code} (${res.log.duration_ms} мс)` : '✓ Отправлено';
        setTimeout(() => { btn.disabled = false; btn.textContent = 'Тестовый запрос'; }, 3000);
      } catch(err) {
        showError(err);
        btn.disabled = false;
        btn.textContent = 'Тестовый запрос';
      }
    };
  });

  document.querySelectorAll('[data-wh-toggle]').forEach(btn => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.whToggle);
      const wh = state.webhooks.find(x => x.id === id);
      if (!wh) return;
      try {
        await api(`/webhooks/${id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !wh.is_active }) });
        await openWebhooks();
      } catch(err) {
        showError(err);
      }
    };
  });

  document.querySelectorAll('[data-wh-delete]').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('Удалить этот вебхук?')) return;
      const id = Number(btn.dataset.whDelete);
      try {
        await api(`/webhooks/${id}`, { method: 'DELETE' });
        await openWebhooks();
      } catch(err) {
        showError(err);
      }
    };
  });

  document.querySelectorAll('[data-wh-logs]').forEach(btn => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.whLogs);
      const drawer = document.querySelector(`#wh-logs-${id}`);
      if (!drawer) return;
      if (drawer.style.display !== 'none') {
        drawer.style.display = 'none';
        return;
      }
      drawer.style.display = 'block';
      drawer.innerHTML = skeletonLines(3);
      try {
        const logs = await api(`/webhooks/${id}/logs`);
        if (!logs.length) {
          drawer.innerHTML = '<div class="muted">Запросов по этому вебхуку ещё не было.</div>';
          return;
        }
        drawer.innerHTML = `
          <strong>Последние доставки (${logs.length}):</strong>
          <div style="margin-top:6px">
            ${logs.map(l => `
              <div class="webhook-log-row">
                <span><code>${esc(l.event)}</code></span>
                <span class="webhook-log-status ${l.status_code && l.status_code < 400 ? 'ok' : 'err'}">
                  ${l.status_code || 'Err'} (${l.duration_ms} мс)
                </span>
                <small class="muted">${date(l.created_at)}</small>
              </div>
            `).join('')}
          </div>
        `;
      } catch(err) {
        drawer.innerHTML = `<div class="muted" style="color:var(--late)">Ошибка загрузки: ${esc(err.message)}</div>`;
      }
    };
  });
}

function formatRuDate(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr;
  return d.toLocaleDateString('ru-RU');
}

async function openBilling() {
  if (!billingOn()) { setView(state.user.role === 'customer' ? 'tickets' : 'tasks'); return; }
  setView('billing');
  syncRoute();
  try {
    state.billing = await api('/billing/overview');
    if (state.user.role !== 'customer') {
      state.billingClients = await api('/billing/clients');
    }
    renderBilling();
  } catch(err) {
    showError(err);
  }
}

function renderBilling() {
  const staff = state.user.role!=='customer';
  const canManage=canManageFinance();
  const employee = state.user.role==='employee'&&!state.user.is_manager;
  if (!state.billing) { shell('Биллинг и счета', '', skeleton('billing')); return; }
  const b = state.billing || {};
  const clients = staff ? (b.clients || state.billingClients || []) : [];
  const rub = value => `${(value || 0).toLocaleString('ru-RU')} ₽`;
  const kpi = (label, value, hint, cls = '') => `<div class="billing-kpi ${cls}"><span class="billing-kpi-label">${label}</span><strong class="billing-kpi-value">${value}</strong><span class="billing-kpi-hint">${hint}</span></div>`;
  const allDocs = b.invoices || b.recent_documents || [];
  const issuedDocs = allDocs.filter(d => d.status === 'issued' && d.doc_type === 'invoice');
  let totalUnbilled = 0;

  let kpis = '';
  if (staff) {
    const totalPaid = b.total_paid_rub ?? b.total_paid_rub_month ?? 0;
    totalUnbilled = b.total_unbilled_minutes ?? clients.reduce((acc, c) => acc + (c.unbilled_minutes || c.unbilled_done_minutes || 0), 0);
    const totalClients = clients.length || b.total_clients || 0;
    const withDebt = clients.filter(c => (c.balance_minutes || 0) < 0).length || b.clients_with_debt || 0;
    const withDeposit = clients.filter(c => (c.balance_minutes || 0) > 0).length || b.clients_with_positive_balance || 0;
    const debtMinutes = clients.filter(c => (c.balance_minutes || 0) < 0).reduce((acc, c) => acc + c.balance_minutes, 0);
    kpis = `<div class="billing-kpi-grid">${kpi('Поступило за месяц', rub(totalPaid), 'Оплаченные счета клиентов', 'positive')}${kpi('Готово к актированию', hours(totalUnbilled), 'Задачи и сопровождение без акта')}${kpi('Ожидают оплаты', rub(issuedDocs.reduce((acc, d) => acc + (d.total_rub || 0), 0)), `${issuedDocs.length} ${plural(issuedDocs.length, ['счёт', 'счёта', 'счетов'])} · ${totalClients} ${plural(totalClients, ['клиент', 'клиента', 'клиентов'])}, ${withDeposit} с депозитом`)}${kpi('Баланс в минусе', `${withDebt} ${plural(withDebt, ['клиент', 'клиента', 'клиентов'])}`, withDebt ? `Суммарно −${hours(Math.abs(debtMinutes))}` : 'Все балансы в норме', withDebt ? 'danger' : '')}</div>`;
  } else {
    const balMins = b.balance_minutes || 0;
    const balHours = b.balance_hours ?? (balMins / 60.0);
    const balRub = b.balance_rub ?? b.balance_rub_equiv ?? Math.round(balHours * (b.hourly_rate_rub || 3000));
    const activeMins = b.in_progress_minutes ?? b.active_billable_minutes ?? 0;
    const unbilledMins = b.unbilled_minutes ?? b.unbilled_done_minutes ?? 0;
    kpis = `<div class="billing-kpi-grid">${kpi('Баланс депозита', `${balHours.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч`, `Эквивалент: ${rub(balRub)}`, balMins > 0 ? 'positive' : balMins < 0 ? 'danger' : '')}${kpi('Тарифная ставка', `${(b.hourly_rate_rub || 3000).toLocaleString('ru-RU')} ₽/ч`, 'Фиксированная ставка по договору')}${kpi('Часы в работе', hours(activeMins), 'Согласованные активные заявки')}${kpi('Готово к актированию', hours(unbilledMins), 'Задачи и сопровождение без акта')}</div>`;
  }

  const actions = employee ? '' : staff
    ? `<button class="button" id="btn-create-deposit">Пополнить баланс</button><button class="button" id="btn-create-invoice">Выставить счёт</button><button class="button primary" id="btn-create-act">${icon('plus', 16)}Сформировать акт</button>`
    : `<button class="button primary" id="btn-customer-deposit">${icon('plus', 16)}Купить пакет часов</button>`;

  const availableTabs = staff ? ['docs', 'clients', 'service', 'tx'] : ['docs', 'tx'];
  const activeTab = availableTabs.includes(state.billingTab) ? state.billingTab : 'docs';
  const tabButton = (key, label, count) => `<button class="billing-tab ${activeTab === key ? 'active' : ''}" data-tab="${key}" role="tab" aria-selected="${activeTab === key}">${label}${count !== undefined ? ` <i>${count}</i>` : ''}</button>`;
  const tabs = `<div class="billing-tabs" role="tablist" aria-label="Разделы биллинга">${tabButton('docs', 'Счета и акты', allDocs.length)}${staff ? tabButton('clients', 'Клиенты и тарифы', clients.length) : ''}${staff ? tabButton('service', 'Сопровождение', (b.service_entries || []).length) : ''}${tabButton('tx', 'История операций')}</div>`;

  let content = '';
  if (activeTab === 'docs') {
    let docs = allDocs;
    const filter = state.billingFilter || 'all';
    if (filter === 'invoice') docs = docs.filter(d => d.doc_type === 'invoice');
    else if (filter === 'act') docs = docs.filter(d => d.doc_type === 'act');
    else if (filter === 'issued') docs = docs.filter(d => d.status === 'issued'&&d.doc_type==='invoice');
    else if (filter === 'paid') docs = docs.filter(d => d.status === 'paid'||(d.signed_at&&d.status!=='cancelled'));
    const pill = (key, label) => `<button class="billing-filter-pill ${filter === key ? 'active' : ''}" data-filter="${key}" aria-pressed="${filter === key}">${label}</button>`;
    const filterBar = `<div class="billing-filter-bar">${pill('all', 'Все документы')}${pill('invoice', 'Счета')}${pill('act', 'Акты')}${pill('issued', 'Ожидают оплаты')}${pill('paid', 'Оплаченные / подписанные')}</div>`;
    const statusPill = (doc) => {
      if (doc.doc_type==='act'&&doc.signed_at&&doc.status!=='cancelled')return '<span class="billing-status paid">Подписан</span>';
      if (doc.status === 'paid') return `<span class="billing-status paid">${doc.doc_type === 'act' ? 'Подписан' : 'Оплачен'}</span>`;
      if (doc.status === 'issued') return `<span class="billing-status issued">${doc.doc_type === 'act' ? 'На подписании' : 'Ожидает оплаты'}</span>`;
      return '<span class="billing-status cancelled">Аннулирован</span>';
    };
    const docRows = docs.map(d => {
      const typeBadge = d.doc_type === 'act' ? '<span class="billing-doc-pill act">Акт</span>' : '<span class="billing-doc-pill invoice">Счёт</span>';
      const clientName = d.organization_name || d.customer_name || d.client_name || 'Клиент';
      const period = d.period_start && d.period_end ? `${formatRuDate(d.period_start)} – ${formatRuDate(d.period_end)}` : '';
      let actionButtons = `<a href="/api/billing/invoices/${d.id}/print" target="_blank" rel="noopener" class="button small" aria-label="Печатная форма ${esc(d.number)}" title="Печатная форма / PDF">${icon('print', 15)}</a>`;
      if (canManage && d.status === 'issued') actionButtons = `${d.doc_type==='act'?(d.signed_at?'':`<button class="button small" data-mark-signed="${d.id}">Подтвердить подписание</button>`):`<button class="button small" data-mark-paid="${d.id}">Подтвердить оплату</button>`}${actionButtons}<button class="button small danger" data-mark-cancel="${d.id}" aria-label="Аннулировать ${esc(d.number)}" title="Аннулировать документ">✕</button>`;
      if (!staff && d.status === 'issued' && d.doc_type === 'invoice') actionButtons = `<span class="muted">Оплатите по реквизитам счёта. Менеджер подтвердит поступление.</span>${actionButtons}`;
      return `<tr><td><div class="doc-cell">${typeBadge}<div><strong>№ ${esc(d.number)}</strong><small>${period ? 'за ' + period : 'от ' + formatRuDate(d.created_at)}</small></div></div></td>${staff ? `<td><strong>${esc(clientName)}</strong></td>` : ''}<td class="num">${hours(d.total_minutes)}</td><td class="num"><strong>${rub(d.total_rub)}</strong></td><td>${statusPill(d)}</td><td><div class="billing-actions">${actionButtons}</div></td></tr>`;
    }).join('');
    content = `${filterBar}${docs.length ? `<div class="table-scroll"><table class="billing-table"><thead><tr><th>Документ</th>${staff ? '<th>Клиент</th>' : ''}<th class="num">Объём</th><th class="num">Сумма</th><th>Статус</th><th><span class="visually-hidden">Действия</span></th></tr></thead><tbody>${docRows}</tbody></table></div>` : '<div class="empty"><strong>Документов нет</strong>По выбранному фильтру ничего не найдено.</div>'}`;
  } else if (activeTab === 'clients' && staff) {
    const clientRows = clients.map(c => {
      const balance = c.balance_minutes || 0;
      return `<tr><td><strong>${esc(c.name)}</strong><div class="billing-client-meta">${c.client_type === 'org' || c.client_type === 'organization' ? 'Организация' : 'Физлицо / прямой клиент'}</div></td><td><div>${c.inn ? `ИНН: ${esc(c.inn)}` : '<span class="muted">ИНН не указан</span>'}</div>${c.legal_address ? `<div class="billing-client-meta">${esc(c.legal_address)}</div>` : ''}</td><td class="num"><strong>${(c.hourly_rate_rub || 3000).toLocaleString('ru-RU')} ₽/ч</strong></td><td class="num"><strong style="color:${balance < 0 ? 'var(--late)' : 'var(--ink)'}">${(c.balance_hours ?? (balance / 60)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч</strong><div class="billing-client-meta">${rub(c.balance_rub ?? c.balance_rub_equiv ?? Math.round((balance / 60) * (c.hourly_rate_rub || 3000)))}</div></td><td class="num"><strong>${hours(c.unbilled_minutes ?? c.unbilled_done_minutes ?? 0)}</strong></td><td><div class="billing-actions">${canManage?`<button class="button small" data-edit-client="${c.client_type}:${c.client_id}">Реквизиты</button><button class="button small" data-deposit-client="${c.client_type}:${c.client_id}">+ Часы</button><button class="button small primary" data-act-client="${c.client_type}:${c.client_id}">+ Акт</button>`:'Только просмотр'}</div></td></tr>`;
    }).join('');
    content = `<div class="table-scroll"><table class="billing-table"><thead><tr><th>Клиент</th><th>Реквизиты</th><th class="num">Ставка</th><th class="num">Депозит</th><th class="num">К актированию</th><th><span class="visually-hidden">Управление</span></th></tr></thead><tbody>${clientRows || '<tr><td colspan="6"><div class="empty"><strong>Клиентов пока нет</strong></div></td></tr>'}</tbody></table></div>`;
  } else if (activeTab === 'service' && staff) {
    const entries = b.service_entries || [];
    const intro = 'Переписка, созвоны и встречи с клиентами. Клиент их не видит: в акте записи без акта сворачиваются в строку «Консультационное сопровождение и координация работ» по ставке клиента. Вносить время можно в общем чате клиента или в карточке заявки.';
    content = `<div class="content"><p class="muted" style="margin-top:0">${intro}</p>${entries.length ? entries.map(e => serviceEntryItem(e, { showClient: true, canDelete: e.author_id === state.user.id || isDispatcher() })).join('') : '<div class="empty"><strong>Записей пока нет</strong>Время на коммуникацию появится здесь.</div>'}</div>`;
  } else {
    const txs = b.transactions || b.recent_transactions || [];
    const txRows = txs.map(t => {
      const kind = t.tx_type === 'charge' ? ['charge', 'Списание'] : t.tx_type === 'refund' ? ['refund', 'Возврат'] : ['deposit', 'Пополнение'];
      const clientName = t.organization_name || t.customer_name || t.client_name || 'Клиент';
      return `<tr><td>${date(t.created_at)}</td>${staff ? `<td><strong>${esc(clientName)}</strong></td>` : ''}<td><span class="billing-tx-badge ${kind[0]}">${kind[1]}</span></td><td class="num"><strong style="color:${t.minutes > 0 ? 'var(--accent-ink)' : t.minutes < 0 ? 'var(--late)' : 'inherit'}">${t.minutes > 0 ? '+' : ''}${hours(t.minutes)}</strong></td><td class="num"><strong>${rub(t.amount_rub)}</strong></td><td>${esc(t.description || '—')}</td><td><small class="muted">${esc(t.created_by_name || 'Система')}</small></td></tr>`;
    }).join('');
    content = txs.length ? `<div class="table-scroll"><table class="billing-table"><thead><tr><th>Дата</th>${staff ? '<th>Клиент</th>' : ''}<th>Операция</th><th class="num">Объём</th><th class="num">Сумма</th><th>Основание</th><th>Автор</th></tr></thead><tbody>${txRows}</tbody></table></div>` : '<div class="empty"><strong>Операций пока нет</strong>Пополнения и списания часов появятся здесь.</div>';
  }

  let side = '';
  if (staff) {
    const maxBalance = Math.max(1, ...clients.map(c => Math.abs(c.balance_minutes || 0)));
    const balanceRows = clients.slice().sort((x, y) => (y.balance_minutes || 0) - (x.balance_minutes || 0)).map(c => {
      const m = c.balance_minutes || 0;
      const width = Math.abs(m) / maxBalance * 100;
      return `<div class="balance-row"><span title="${esc(c.name)}">${esc(c.name)}</span><strong class="${m < 0 ? 'neg' : m > 0 ? 'pos' : ''}">${m > 0 ? '+' : m < 0 ? '−' : ''}${hours(Math.abs(m))}</strong><div class="balance-track" aria-hidden="true"><div>${m < 0 ? `<i class="neg" style="width:${width}%"></i>` : ''}</div><div>${m > 0 ? `<i class="pos" style="width:${width}%"></i>` : ''}</div></div></div>`;
    }).join('');
    side = `<div class="context-stack"><section class="panel content"><div class="card-head"><h2>Балансы клиентов</h2><span class="muted">часы депозита</span></div>${balanceRows || '<p class="muted">Клиентов пока нет.</p>'}</section>${canManage&&totalUnbilled > 0 ? `<section class="focus-panel"><span class="focus-overline">Пора закрыть период</span><h2>${hours(totalUnbilled)} выполнено без акта</h2><p>Сформируйте акт, чтобы списать часы с депозита клиента.</p><div class="focus-actions"><button class="button on-dark" id="btn-close-period">Сформировать акт</button></div></section>` : ''}</div>`;
  }

  const month = new Date().toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' });
  shell('Биллинг и счета', actions, `${kpis}<div class="${staff ? 'split billing-split' : ''}"><section class="panel">${tabs}${content}</section>${side}</div><div id="billing-modal-slot"></div>`, { kicker: month.charAt(0).toUpperCase() + month.slice(1) });

  attachBillingHandlers();
  bindWorkspaceTabs();
}

function bindWorkspaceTabs() {
  document.querySelectorAll('.conversation [role="tablist"], .billing-tabs').forEach(list => {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    tabs.forEach(tab => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('click', () => {
        const key = tab.dataset.detailTab || tab.dataset.tab;
        const current = document.querySelector(`[data-detail-tab="${key}"], .billing-tab[data-tab="${key}"]`);
        current?.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]').forEach(item => { item.tabIndex = item === current ? 0 : -1; });
        current?.focus({ preventScroll: true });
      });
    });
    list.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const index = tabs.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].click();
      const selected = document.querySelector('.conversation [role="tab"][aria-selected="true"], .billing-tabs [aria-selected="true"]');
      selected?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
    };
  });
}

function bindBillingDialog(slot) {
  const trigger = document.activeElement;
  const wrapper = slot.querySelector('#billing-modal');
  const dialog = document.createElement('dialog');
  dialog.id = wrapper.id;
  dialog.className = wrapper.className;
  dialog.append(...wrapper.childNodes);
  wrapper.replaceWith(dialog);
  const heading = dialog.querySelector('h2');
  heading.id = 'billing-dialog-title';
  dialog.setAttribute('aria-labelledby', heading.id);
  const closeButton = dialog.querySelector('#modal-close');
  closeButton.type = 'button';
  closeButton.setAttribute('aria-label', 'Закрыть окно');
  const close = () => {
    if (dialog.classList.contains('closing')) return;
    dialog.classList.add('closing');
    setTimeout(() => { dialog.close(); dialog.remove(); if (trigger?.isConnected) trigger.focus(); }, reduceMotion() ? 0 : 150);
  };
  closeButton.onclick = close;
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.showModal();
  dialog.querySelector('input:not([type="hidden"]), select, textarea')?.focus();
}

function prepareBillingTables() {
  document.querySelectorAll('.billing-table').forEach(table => {
    const labels = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
    table.querySelectorAll('tbody tr').forEach(row => [...row.cells].forEach((cell, i) => { if (cell.colSpan === 1) cell.dataset.label = labels[i] || ''; }));
  });
}

function attachBillingHandlers() {
  prepareBillingTables();
  document.querySelectorAll('.billing-tab').forEach(btn => {
    btn.onclick = () => {
      state.billingTab = btn.dataset.tab;
      renderBilling();
    };
  });

  document.querySelectorAll('.billing-filter-pill').forEach(btn => {
    btn.onclick = () => {
      state.billingFilter = btn.dataset.filter;
      renderBilling();
    };
  });

  document.querySelectorAll('[data-mark-signed]').forEach(button=>button.onclick=async()=>{if(!confirm('Отметить, что акт подписан сторонами?'))return;try{await api(`/billing/invoices/${button.dataset.markSigned}/status`,{method:'PATCH',body:JSON.stringify({status:'signed'})});await openBilling();}catch(error){showError(error);}});
  document.querySelectorAll('[data-mark-paid]').forEach(btn => {
    btn.onclick = async () => {
      if(!confirm('Подтвердить фактическое поступление денег по этому счёту? Часы будут зачислены клиенту.'))return;
      const id = Number(btn.dataset.markPaid);
      try {
        await api(`/billing/invoices/${id}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status: 'paid' })
        });
        await openBilling();
      } catch(err) {
        showError(err);
      }
    };
  });

  document.querySelectorAll('[data-mark-cancel]').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('Аннулировать этот документ? Если это акт, списанные часы будут возвращены на баланс клиента.')) return;
      const id = Number(btn.dataset.markCancel);
      try {
        await api(`/billing/invoices/${id}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status: 'cancelled' })
        });
        await openBilling();
      } catch(err) {
        showError(err);
      }
    };
  });



  bindServiceDelete(openBilling);
  document.querySelector('#btn-create-act')?.addEventListener('click', () => openActModal());
  document.querySelector('#btn-close-period')?.addEventListener('click', () => openActModal());
  document.querySelector('#btn-create-invoice')?.addEventListener('click', () => openInvoiceModal());
  document.querySelector('#btn-create-deposit')?.addEventListener('click', () => openDepositModal());
  document.querySelector('#btn-customer-deposit')?.addEventListener('click', () => openCustomerInvoiceModal());

  document.querySelectorAll('[data-edit-client]').forEach(btn => {
    btn.onclick = () => {
      const [type, id] = btn.dataset.editClient.split(':');
      const c = state.billingClients.find(x => x.client_type === type && x.client_id === Number(id));
      if (c) openClientRateModal(c);
    };
  });

  document.querySelectorAll('[data-act-client]').forEach(btn => {
    btn.onclick = () => openActModal(btn.dataset.actClient);
  });

  document.querySelectorAll('[data-deposit-client]').forEach(btn => {
    btn.onclick = () => openDepositModal(btn.dataset.depositClient);
  });
}

async function openActModal(preselectedKey = '') {
  const slot = document.querySelector('#billing-modal-slot');
  if (!slot) return;
  const clients = state.billingClients || [];

  slot.innerHTML = `
    <div class="billing-modal-backdrop" id="billing-modal">
      <div class="billing-modal-card">
        <div class="billing-modal-head">
          <h2>Сформировать акт выполненных работ</h2>
          <button class="billing-modal-close" id="modal-close">&times;</button>
        </div>
        <form id="act-form" class="form">
          <label>Клиент
            <select class="field" name="client_key" id="act-client-select" required>
              <option value="">-- Выберите организацию или клиента --</option>
              ${clients.map(c => `
                <option value="${c.client_type}:${c.client_id}" ${preselectedKey === `${c.client_type}:${c.client_id}` ? 'selected' : ''}>
                  ${esc(c.name)} (${c.client_type === 'organization' ? 'Организация' : 'Физлицо'}, ставка ${c.hourly_rate_rub} ₽/ч)
                </option>
              `).join('')}
            </select>
          </label>
          <div style="font-weight:700; margin-top:8px; font-size:13px">Заявки и сопровождение для включения в акт:</div>
          <div id="act-tickets-box" class="billing-ticket-list">
            <div class="muted">Выберите клиента для отображения заявок и сопровождения без акта</div>
          </div>
          <div class="row">
            <label style="flex:1">Период с
              <input class="field" type="date" name="period_start">
            </label>
            <label style="flex:1">по
              <input class="field" type="date" name="period_end">
            </label>
          </div>
          <label>Предмет акта / Примечание
            <textarea class="field" name="notes" placeholder="Оказание услуг по технической поддержке и сопровождению..."></textarea>
          </label>
          <div id="act-totals-bar" style="padding:10px 14px; background:var(--accent-soft); border-radius:var(--radius-sm); font-size:13.5px; margin: 10px 0">
            Выбрано заявок: <strong>0</strong> | Трудозатраты: <strong>0 ч</strong> | Сумма к списанию: <strong>0 ₽</strong>
          </div>
          <button class="button primary" id="act-submit-btn" disabled>Сформировать акт и списать часы</button>
        </form>
      </div>
    </div>
  `;

  bindBillingDialog(slot);

  const select = slot.querySelector('#act-client-select');
  const ticketsBox = slot.querySelector('#act-tickets-box');
  const totalsBar = slot.querySelector('#act-totals-bar');
  const submitBtn = slot.querySelector('#act-submit-btn');

  let currentTickets = [];
  let currentServices = [];

  async function loadTickets(key) {
    if (!key) {
      ticketsBox.innerHTML = '<div class="muted">Выберите клиента</div>';
      submitBtn.disabled = true;
      return;
    }
    const [cType, cId] = key.split(':');
    ticketsBox.innerHTML = skeletonLines(3);
    try {
      [currentTickets, currentServices] = await Promise.all([
        api(`/billing/unbilled-tickets?client_type=${cType}&client_id=${cId}`),
        api(`/service-entries?client_type=${cType}&client_id=${cId}&unbilled=true`)
      ]);
      if (!currentTickets.length && !currentServices.length) {
        ticketsBox.innerHTML = '<div class="muted">У этого клиента нет завершённых заявок и часов сопровождения без акта.</div>';
        submitBtn.disabled = true;
        recalc();
        return;
      }
      ticketsBox.innerHTML = `
        <div style="padding-bottom:6px; margin-bottom:6px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between">
          <label style="font-weight:700; cursor:pointer"><input type="checkbox" id="act-select-all" checked> Выбрать все</label>
          <small class="muted">${currentTickets.length} ${plural(currentTickets.length, ['заявка', 'заявки', 'заявок'])}${currentServices.length ? ` · ${currentServices.length} ${plural(currentServices.length, ['запись', 'записи', 'записей'])} сопровождения` : ''}</small>
        </div>
        ${currentServices.map(s => `
            <div class="billing-ticket-item">
              <input type="checkbox" class="act-service-cb" value="${s.id}" data-mins="${s.minutes}" checked id="act-sv-${s.id}">
              <label for="act-sv-${s.id}">
                <span><strong>${esc(serviceKindNames[s.kind] || s.kind)}</strong> ${date(s.occurred_at)}: ${esc(s.note)}</span>
                <strong>${hours(s.minutes)}</strong>
              </label>
            </div>`).join('')}
        ${currentTickets.map(t => {
          const mins = t.actual_minutes || t.approved_minutes || 0;
          return `
            <div class="billing-ticket-item">
              <input type="checkbox" class="act-ticket-cb" value="${t.id}" data-mins="${mins}" checked id="act-cb-${t.id}">
              <label for="act-cb-${t.id}">
                <span><strong>№${t.id}</strong>: ${esc(t.title)}</span>
                <strong>${hours(mins)}</strong>
              </label>
            </div>
          `;
        }).join('')}
      `;
      slot.querySelector('#act-select-all').onchange = (e) => {
        slot.querySelectorAll('.act-ticket-cb,.act-service-cb').forEach(cb => { cb.checked = e.target.checked; });
        recalc();
      };
      slot.querySelectorAll('.act-ticket-cb,.act-service-cb').forEach(cb => {
        cb.onchange = () => recalc();
      });
      recalc();
    } catch(err) {
      ticketsBox.innerHTML = `<div class="muted" style="color:var(--late)">Ошибка: ${esc(err.message)}</div>`;
    }
  }

  function recalc() {
    const key = select.value;
    if (!key) return;
    const [cType, cId] = key.split(':');
    const client = clients.find(x => x.client_type === cType && x.client_id === Number(cId));
    const rate = client ? client.hourly_rate_rub : 3000;
    const checked = Array.from(slot.querySelectorAll('.act-ticket-cb:checked,.act-service-cb:checked'));
    const checkedTickets = slot.querySelectorAll('.act-ticket-cb:checked').length;
    let totalMins = 0;
    checked.forEach(cb => { totalMins += Number(cb.dataset.mins || 0); });
    const rub = Math.round(totalMins / 60 * rate);
    totalsBar.innerHTML = `Выбрано заявок: <strong>${checkedTickets}</strong>, сопровождение: <strong>${checked.length - checkedTickets}</strong> | Трудозатраты: <strong>${hours(totalMins)}</strong> | Сумма к списанию: <strong>${rub.toLocaleString('ru-RU')} ₽</strong>`;
    submitBtn.disabled = checked.length === 0;
  }

  select.onchange = () => loadTickets(select.value);
  if (select.value) loadTickets(select.value);

  slot.querySelector('#act-form').onsubmit = async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    const form = new FormData(e.target);
    const [client_type, client_id_str] = form.get('client_key').split(':');
    const ticket_ids = Array.from(slot.querySelectorAll('.act-ticket-cb:checked')).map(cb => Number(cb.value));
    const service_entry_ids = Array.from(slot.querySelectorAll('.act-service-cb:checked')).map(cb => Number(cb.value));
    try {
      const doc = await api('/billing/invoices', {
        method: 'POST',
        body: JSON.stringify({
          doc_type: 'act',
          client_type,
          client_id: Number(client_id_str),
          period_start: form.get('period_start') || null,
          period_end: form.get('period_end') || null,
          notes: form.get('notes') || '',
          ticket_ids,
          service_entry_ids
        })
      });
      slot.innerHTML = '';
      await openBilling();
      window.open(`/api/billing/invoices/${doc.id}/print`, '_blank');
    } catch(err) {
      showError(err);
      submitBtn.disabled = false;
    }
  };
}

async function openInvoiceModal(preselectedKey = '') {
  const slot = document.querySelector('#billing-modal-slot');
  if (!slot) return;
  const clients = state.billingClients || [];

  slot.innerHTML = `
    <div class="billing-modal-backdrop" id="billing-modal">
      <div class="billing-modal-card">
        <div class="billing-modal-head">
          <h2>Выставить счёт на оплату часов</h2>
          <button class="billing-modal-close" id="modal-close">&times;</button>
        </div>
        <form id="invoice-form" class="form">
          <label>Клиент
            <select class="field" name="client_key" id="inv-client-select" required>
              <option value="">-- Выберите организацию или клиента --</option>
              ${clients.map(c => `
                <option value="${c.client_type}:${c.client_id}" ${preselectedKey === `${c.client_type}:${c.client_id}` ? 'selected' : ''}>
                  ${esc(c.name)} (ставка ${c.hourly_rate_rub} ₽/ч, баланс ${(c.balance_hours ?? ((c.balance_minutes || 0) / 60)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч)
                </option>
              `).join('')}
            </select>
          </label>
          <label>Количество часов в пакете
            <input class="field" type="number" name="deposit_hours" id="inv-hours" min="1" max="1000" step="1" value="10" required>
          </label>
          <div id="inv-preview-bar" style="padding:10px 14px; background:var(--accent-soft); border-radius:var(--radius-sm); font-size:14px; margin: 8px 0">
            Итого к оплате: <strong>30 000 ₽</strong>
          </div>
          <label>Назначение платежа / Примечание
            <textarea class="field" name="notes" placeholder="Предоплата пакета 10 часов технической поддержки и доработок"></textarea>
          </label>
          <button class="button primary" id="inv-submit-btn">Выставить счёт</button>
        </form>
      </div>
    </div>
  `;

  bindBillingDialog(slot);

  const select = slot.querySelector('#inv-client-select');
  const hoursInput = slot.querySelector('#inv-hours');
  const previewBar = slot.querySelector('#inv-preview-bar');

  function updateSum() {
    const key = select.value;
    const hoursVal = Number(hoursInput.value || 0);
    let rate = 3000;
    if (key) {
      const [cType, cId] = key.split(':');
      const c = clients.find(x => x.client_type === cType && x.client_id === Number(cId));
      if (c) rate = c.hourly_rate_rub;
    }
    const sum = Math.round(hoursVal * rate);
    previewBar.innerHTML = `Ставка: <strong>${rate.toLocaleString('ru-RU')} ₽/ч</strong> | Итого к оплате: <strong>${sum.toLocaleString('ru-RU')} ₽</strong>`;
  }

  select.onchange = updateSum;
  hoursInput.oninput = updateSum;
  updateSum();

  slot.querySelector('#invoice-form').onsubmit = async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const [client_type, client_id_str] = form.get('client_key').split(':');
    const deposit_hours = Number(form.get('deposit_hours'));
    try {
      const doc = await api('/billing/invoices', {
        method: 'POST',
        body: JSON.stringify({
          doc_type: 'invoice',
          client_type,
          client_id: Number(client_id_str),
          deposit_hours,
          notes: form.get('notes') || ''
        })
      });
      slot.innerHTML = '';
      await openBilling();
      window.open(`/api/billing/invoices/${doc.id}/print`, '_blank');
    } catch(err) {
      showError(err);
    }
  };
}

async function openDepositModal(preselectedKey = '') {
  const slot = document.querySelector('#billing-modal-slot');
  if (!slot) return;
  const clients = state.billingClients || [];

  slot.innerHTML = `
    <div class="billing-modal-backdrop" id="billing-modal">
      <div class="billing-modal-card">
        <div class="billing-modal-head">
          <h2>Прямое пополнение депозита часов</h2>
          <button class="billing-modal-close" id="modal-close">&times;</button>
        </div>
        <form id="deposit-form" class="form">
          <label>Клиент
            <select class="field" name="client_key" id="dep-client-select" required>
              <option value="">-- Выберите организацию или клиента --</option>
              ${clients.map(c => `
                <option value="${c.client_type}:${c.client_id}" ${preselectedKey === `${c.client_type}:${c.client_id}` ? 'selected' : ''}>
                  ${esc(c.name)} (текущий баланс: ${(c.balance_hours ?? ((c.balance_minutes || 0) / 60)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч)
                </option>
              `).join('')}
            </select>
          </label>
          <div class="row">
            <label style="flex:1">Количество часов
              <input class="field" type="number" name="hours" id="dep-hours" min="0.25" max="1000" step="0.25" value="10" required>
            </label>
            <label style="flex:1">Сумма (₽)
              <input class="field" type="number" name="amount_rub" id="dep-amount" min="0" max="10000000" step="100" value="30000" required>
            </label>
          </div>
          <label>Основание пополнения
            <input class="field" type="text" name="description" placeholder="Банковский платёж по договору №... / Бонусные часы" required>
          </label>
          <button class="button primary">Зачислить на баланс</button>
        </form>
      </div>
    </div>
  `;

  bindBillingDialog(slot);

  const select = slot.querySelector('#dep-client-select');
  const hoursInput = slot.querySelector('#dep-hours');
  const amountInput = slot.querySelector('#dep-amount');

  function updateDepositPreview() {
    const key = select.value;
    const hoursVal = Number(hoursInput.value || 0);
    if (key) {
      const [cType, cId] = key.split(':');
      const c = clients.find(x => x.client_type === cType && x.client_id === Number(cId));
      if (c) {
        amountInput.value = Math.round(hoursVal * c.hourly_rate_rub);
      }
    }
  }

  select.onchange = updateDepositPreview;
  hoursInput.oninput = updateDepositPreview;

  slot.querySelector('#deposit-form').onsubmit = async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const [client_type, client_id_str] = form.get('client_key').split(':');
    const hoursVal = Number(form.get('hours'));
    const amount_rub = Number(form.get('amount_rub'));
    const description = form.get('description');
    try {
      await api('/billing/deposit', {
        method: 'POST',
        body: JSON.stringify({
          client_type,
          client_id: Number(client_id_str),
          minutes: Math.round(hoursVal * 60),
          amount_rub,
          description
        })
      });
      slot.innerHTML = '';
      await openBilling();
    } catch(err) {
      showError(err);
    }
  };
}

function openClientRateModal(c) {
  const slot = document.querySelector('#billing-modal-slot');
  if (!slot) return;

  slot.innerHTML = `
    <div class="billing-modal-backdrop" id="billing-modal">
      <div class="billing-modal-card">
        <div class="billing-modal-head">
          <h2>Тариф и реквизиты: ${esc(c.name)}</h2>
          <button class="billing-modal-close" id="modal-close">&times;</button>
        </div>
        <form id="rate-form" class="form">
          <label>Почасовая ставка (₽/час)
            <input class="field" type="number" name="hourly_rate_rub" min="500" max="100000" step="100" value="${c.hourly_rate_rub || 3000}" required>
          </label>
          <div class="row">
            <label style="flex:1">ИНН
              <input class="field" type="text" name="inn" maxlength="20" value="${esc(c.inn || '')}" placeholder="7701234567">
            </label>
            <label style="flex:1">КПП
              <input class="field" type="text" name="kpp" maxlength="20" value="${esc(c.kpp || '')}" placeholder="770101001">
            </label>
          </div>
          <label>Юридический адрес
            <textarea class="field" name="legal_address" placeholder="125009, г. Москва, ул. Тверская, д. 1...">${esc(c.legal_address || '')}</textarea>
          </label>
          <button class="button primary">Сохранить изменения</button>
        </form>
      </div>
    </div>
  `;

  bindBillingDialog(slot);

  slot.querySelector('#rate-form').onsubmit = async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      await api(`/billing/clients/${c.client_type}/${c.client_id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          hourly_rate_rub: Number(form.get('hourly_rate_rub')),
          inn: form.get('inn') || '',
          kpp: form.get('kpp') || '',
          legal_address: form.get('legal_address') || ''
        })
      });
      slot.innerHTML = '';
      await openBilling();
    } catch(err) {
      showError(err);
    }
  };
}

function openCustomerInvoiceModal() {
  const slot = document.querySelector('#billing-modal-slot');
  if (!slot) return;
  const b = state.billing || {};
  const rate = b.hourly_rate_rub || 3000;

  slot.innerHTML = `
    <div class="billing-modal-backdrop" id="billing-modal">
      <div class="billing-modal-card">
        <div class="billing-modal-head">
          <h2>Заказ пакета часов поддержки</h2>
          <button class="billing-modal-close" id="modal-close">&times;</button>
        </div>
        <form id="cust-invoice-form" class="form">
          <p class="muted" style="margin-bottom:12px">
            Выберите желаемый объём часов. Система сформирует счёт с реквизитами для оплаты. Часы поступят на баланс после подтверждения платежа менеджером.
          </p>
          <label>Пакет часов
            <select class="field" name="deposit_hours" id="cust-hours-select">
              <option value="5">5 часов (${(5 * rate).toLocaleString('ru-RU')} ₽)</option>
              <option value="10" selected>10 часов (${(10 * rate).toLocaleString('ru-RU')} ₽)</option>
              <option value="20">20 часов (${(20 * rate).toLocaleString('ru-RU')} ₽)</option>
              <option value="50">50 часов (${(50 * rate).toLocaleString('ru-RU')} ₽)</option>
            </select>
          </label>
          <div id="cust-inv-preview" style="padding:10px 14px; background:var(--accent-soft); border-radius:var(--radius-sm); font-size:14px; margin: 8px 0">
            Ваша ставка: <strong>${rate.toLocaleString('ru-RU')} ₽/ч</strong> | К оплате: <strong>${(10 * rate).toLocaleString('ru-RU')} ₽</strong>
          </div>
          <button class="button primary">Сформировать счёт</button>
        </form>
      </div>
    </div>
  `;

  bindBillingDialog(slot);

  const select = slot.querySelector('#cust-hours-select');
  const preview = slot.querySelector('#cust-inv-preview');

  select.onchange = () => {
    const h = Number(select.value);
    preview.innerHTML = `Ваша ставка: <strong>${rate.toLocaleString('ru-RU')} ₽/ч</strong> | К оплате: <strong>${(h * rate).toLocaleString('ru-RU')} ₽</strong>`;
  };

  slot.querySelector('#cust-invoice-form').onsubmit = async (e) => {
    e.preventDefault();
    const h = Number(select.value);
    try {
      const doc = await api('/billing/invoices', {
        method: 'POST',
        body: JSON.stringify({
          doc_type: 'invoice',
          client_type: b.client_type,
          client_id: b.client_id,
          deposit_hours: h,
          notes: `Предоплата пакета ${h} часов технической поддержки`
        })
      });
      slot.innerHTML = '';
      await openBilling();
      window.open(`/api/billing/invoices/${doc.id}/print`, '_blank');
    } catch(err) {
      showError(err);
    }
  };
}

async function openHash(){
  if(!state.user||state.user.must_change_credentials)return;
  state.restoringRoute=true;
  try{
    const route=location.hash.slice(1).replace(/^\//, '');const taskMatch=route.match(/^task\/(\d+)$/);if(taskMatch){if(state.user.role==='customer')return setView('tickets');return await TasksUI.open(Number(taskMatch[1]));}const match=route.match(/^(ticket|chat|ticket-chat)\/(\d+)$/);
    if(match?.[1]==='ticket-chat')return await openTicketChat(Number(match[2]));
    if(match)return await (match[1]==='ticket'?openTicket(Number(match[2])):openChat(Number(match[2])));
    if(route==='payroll')return setView(state.user.role==='customer'?'tickets':'payroll');
    const loaders={messengers:openMessengers,analytics:openAnalytics,kb:openKb,webhooks:openWebhooks,billing:openBilling,specialists:openSpecialists};
    if(route==='webhooks'&&state.user.role!=='admin')return setView('tickets');
    if(route==='analytics'&&!isDispatcher())return setView('tickets');
    if(loaders[route])return await loaders[route]();
    const views=['tasks','deals','meetings','tickets','queue','organizations','team','profile','new','notifications','chats','specialists'];
    if(views.includes(route)&&!(['team','tasks'].includes(route)&&state.user.role==='customer')&&!(route==='queue'&&state.user.role==='customer'))setView(route);
    else setView(state.user.role==='customer'?'tickets':'tasks');
  }catch(error){showError(error);}finally{state.restoringRoute=false;}
}

async function renderPayroll(){
  try{const module=await import('/payroll.js');if(state.view==='payroll')module.render({state,api,shell,esc,hours,toast,showError});}catch(error){showError(error);}
}
function render() {syncRoute();if(!state.user)return renderAuth();if(state.user.must_change_credentials)return renderCredentials();if(state.view==='organizations')return renderOrganizations();if(state.view==='profile')return renderProfile();if(state.view==='messengers')return renderMessengers();if(state.view==='queue')return renderQueue();if(state.view==='new')return renderNew();if(state.view==='detail'&&state.current)return renderDetail();if(state.view==='ticket-chat'&&state.current)return renderTicketChat();if(state.view==='tasks')return TasksUI.render();if(state.view==='task')return TasksUI.renderDetail();if(state.view==='team')return renderTeam();if(state.view==='deals')return TeamUI.renderDeals();if(state.view==='meetings')return TeamUI.renderMeetings();if(state.view==='notifications')return renderNotifications();if(state.view==='chats')return renderChats();if(state.view==='chat'&&state.currentChat)return renderChatDetail();if(state.view==='analytics')return renderAnalytics();if(state.view==='kb')return renderKb();if(state.view==='webhooks')return renderWebhooks();if(state.view==='payroll')return renderPayroll();if(state.view==='billing')return renderBilling();if(state.view==='specialists')return renderSpecialists();renderTickets();}
async function start(){
  const params=new URLSearchParams(location.search);
  if(params.has('invite')||params.has('reset')){renderAuth();return;}
  if(params.has('register'))state.authMode='register';
  if(params.has('register')||params.has('login'))history.replaceState(null,'',location.pathname+location.hash);
  if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
  try{
    state.user=await api('/me');
    state.view=state.user.role==='customer'?'tickets':'tasks';
    if(state.user.must_change_credentials){renderCredentials();return;}
    initRealtime();
    state.restoringRoute=true;
    await refresh();
    await openHash();
    maybeStartTour();
    syncPush();
  }catch(error){
    if(error.status===401){state.user=null;renderAuth();}
    else if(state.user){render();showError(error);}
    else {app.innerHTML='<main class="auth-main"><section class="auth-card"><h1>Не удалось загрузить кабинет</h1><p>Проверьте соединение и повторите попытку.</p><button class="button primary" id="retry-start">Повторить</button></section></main>';document.querySelector('#retry-start').onclick=start;}
  }
}
let routeTimer;const restoreRoute=()=>{clearTimeout(routeTimer);routeTimer=setTimeout(()=>openHash(),0);};
window.addEventListener('hashchange',restoreRoute);
window.addEventListener('popstate',restoreRoute);
document.addEventListener('visibilitychange',()=>{
  if(document.visibilityState!=='visible'||!state.user)return;
  if(['detail','ticket-chat'].includes(state.view)&&state.current)markRead('ticket',state.current.ticket.id,state.current.messages);
  if(state.view==='chat'&&state.currentChat)markRead('chat',state.currentChat.chat.id,state.currentChat.messages);
  if(state.user.role==='customer')api('/waiting-on-me').then(w=>{state.waiting=w;}).catch(()=>{});
});
themeMedia.addEventListener?.('change',syncThemeUi);
window.matchMedia('(max-width: 900px)').addEventListener('change', event => {
  if (!event.matches && document.body.classList.contains('nav-open')) document.querySelector('[data-nav-close]')?.click();
});
window.addEventListener('dragover',e=>{if([...(e.dataTransfer?.types||[])].includes('Files'))e.preventDefault();});
window.addEventListener('drop',e=>{if([...(e.dataTransfer?.types||[])].includes('Files'))e.preventDefault();});
navigator.serviceWorker?.addEventListener('message',e=>{if(e.data?.type!=='open-url')return;const target=new URL(e.data.url,location.origin);if(location.hash===target.hash)openHash();else location.hash=target.hash;});
document.addEventListener('keydown',e=>{
  if(e.defaultPrevented||e.ctrlKey||e.metaKey||e.altKey||!['KeyJ','KeyK'].includes(e.code)||!state.user)return;
  if(e.target.closest?.('input, textarea, select, [contenteditable="true"]')||document.querySelector('.palette-backdrop, .tour-layer, .billing-modal-backdrop'))return;
  const rows=[...document.querySelectorAll('#main .qrow, #main .trow, #main .chat-item:not([hidden]), #main .notification-row')];
  if(!rows.length)return;
  e.preventDefault();
  const current=rows.indexOf(document.activeElement);
  const next=current<0?0:Math.min(rows.length-1,Math.max(0,current+(e.code==='KeyJ'?1:-1)));
  rows[next].focus({preventScroll:true});
  rows[next].scrollIntoView({block:'nearest',behavior:reduceMotion()?'auto':'smooth'});
});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.code==='KeyK'&&state.user){e.preventDefault();openPalette();return;}
  if(e.key==='Escape'){if(document.body.classList.contains('nav-open'))document.querySelector('[data-nav-close]')?.click();}
});
start();
setInterval(()=>loadNotifications().catch(()=>{}),15000);
setInterval(async()=>{
  if(state.view!=='ticket-chat'||!state.current||composerHasDraft('#message-form'))return;
  const id=state.current.ticket.id;
  try{
    const fresh=await api(`/tickets/${id}`);
    if(state.view!=='ticket-chat'||state.current?.ticket.id!==id||composerHasDraft('#message-form'))return;
    if(JSON.stringify(fresh)!==JSON.stringify(state.current)){state.current=fresh;renderTicketChat();}
  }catch{}
},15000);
setInterval(async()=>{
  if(state.view!=='chat'||!state.currentChat||composerHasDraft('#chat-message-form')) return;
  const id=state.currentChat.chat.id;
  try{
    const fresh=await api(`/chats/${id}`);
    if(state.view!=='chat'||state.currentChat?.chat.id!==id||composerHasDraft('#chat-message-form'))return;
    if(fresh.messages.length!==state.currentChat.messages.length||fresh.chat.assignee_id!==state.currentChat.chat.assignee_id){state.currentChat=fresh;renderChatDetail();}
  }catch{}
},15000);

