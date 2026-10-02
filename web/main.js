const app = document.querySelector('#app');
const state = { user: null, profile: null, tickets: [], chats: [], queue: [], staff: [], customers: [], organizations: [], notifications: [], current: null, currentChat: null, view: 'tickets', filter: 'all', search: '', authMode: 'login', error: '', internalNotes: [], cannedResponses: [], analytics: null, kbCategories: [], kbArticles: [], kbActiveCategory: null, kbSearch: '', kbReadingArticle: null, kbEditingArticle: null, gitLinks: [], webhooks: [], billing: null, billingTab: 'docs', billingFilter: 'all', billingModal: null, owner: 'all', queueScope: 'all', queueSource: 'all', queueGroup: null, detailTab: 'messages', chatSearch: '' };
const statusNames = { new: 'Новая', working: 'В работе', waiting: 'Ожидает заказчика', done: 'Выполнена', closed: 'Закрыта' };
const estimateNames = {pending:'Ожидает решения',approved:'Одобрена',rejected:'Отклонена',revision_requested:'Запрошена корректировка'};
const serviceNames = {development:'Доработка',integration:'Интеграция',support:'Поддержка',consultation:'Консультация',other:'Другое'};
const serviceHints = {development:'Что нужно изменить? Как должен выглядеть готовый результат? Где это работает сейчас?',integration:'Какие системы нужно связать? Какие данные передавать и в каком направлении? Есть ли документация API?',support:'Что не работает? Когда возникла проблема? Какие действия её повторяют?',consultation:'По какому вопросу нужна помощь? Какое решение вы хотите принять?',other:'Что нужно сделать? Какой результат вы ожидаете?'};
const hours = minutes => `${(minutes/60).toLocaleString('ru-RU',{maximumFractionDigits:2})} ч`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const avatar = (person, extra='') => `<span class="person-avatar ${extra}">${person?.avatar_url?`<img src="${esc(person.avatar_url)}" alt="">`:esc((person?.name||'?').trim().split(/\s+/).slice(0,2).map(word=>word[0]).join('').toUpperCase())}</span>`;
const date = value => new Date(value).toLocaleString('ru-RU', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
const statusChipNames = { new: 'Новые', working: 'В работе', waiting: 'Ожидают', done: 'Выполнены', closed: 'Закрыты' };
const ICONS = {
  queue: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  ticket: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"/><path d="M20 17v5H6.5A2.5 2.5 0 0 1 4 19.5"/>',
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
};
const icon = (name, size = 18) => `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
const initials = name => esc((name || '?').trim().split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase());
const plural = (n, [one, few, many]) => { const a = Math.abs(n) % 100, b = a % 10; return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many; };
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
  el.innerHTML = `${icon(tone === 'error' ? 'alert' : tone === 'info' ? 'bell' : 'check', 16)}<span>${esc(text)}</span>`;
  host.append(el);
  setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 260); }, 3600);
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
    { group: 'Действия', svg: icon('plus'), label: 'Создать заявку', run: () => setView('new') },
    ...(staff ? [] : [{ group: 'Действия', svg: icon('help'), label: 'Пройти обучение по кабинету', run: () => startTour() }]),
    { group: 'Действия', svg: icon(effectiveTheme() === 'dark' ? 'sun' : 'moon'), label: effectiveTheme() === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему', run: () => toggleTheme() },
  ].map(item => ({ ...item, hay: item.label.toLocaleLowerCase('ru-RU') }));
  const tickets = state.tickets.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(t => ({ group: 'Заявки', svg: icon('ticket'), label: `№${t.id} · ${t.title}`, hint: statusNames[t.status], run: () => openTicket(t.id), hay: [t.id, t.title, t.customer_name, t.customer_company].join(' ').toLocaleLowerCase('ru-RU') }));
  const chats = staff ? state.chats.map(c => ({ group: 'Чаты', svg: icon('chat'), label: c.customer_name, hint: c.last_message || '', run: () => openChat(c.id), hay: [c.customer_name, c.last_message].join(' ').toLocaleLowerCase('ru-RU') })) : [];
  document.body.insertAdjacentHTML('beforeend', `<div class="palette-backdrop"><div class="palette" role="dialog" aria-modal="true" aria-label="Быстрый переход"><div class="palette-search">${icon('search', 18)}<input id="palette-input" role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list" autocomplete="off" placeholder="Найти заявку, чат или раздел…"><kbd>Esc</kbd></div><div class="palette-list" id="palette-list" role="listbox" aria-label="Результаты"></div><div class="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> выбрать</span><span><kbd>Enter</kbd> открыть</span><span><kbd>Esc</kbd> закрыть</span></div></div></div>`);
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
  if (state.user?.role === 'customer' && !location.hash && !tourDone()) setTimeout(startTour, 700);
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
    { target: '.overview-card', title: 'Сводка по заявкам', text: 'Сколько задач на каждом этапе, сколько часов уже согласовано и сколько оценок ждут вашего решения.', before: toTickets },
    { target: ['#ticket-list .trow', '#ticket-list'], title: 'Список заявок', text: 'Фильтруйте по статусу и ищите по номеру или теме. Нажмите на заявку, чтобы открыть её. Сейчас откроем одну для примера.', before: toTickets },
    { target: '.ticket-progress', title: 'Этапы заявки', text: 'Каждая заявка проходит пять шагов: создание, оценка, согласование, работа и завершение. Текущий шаг подсвечен.', before: toDetail, skip: noTickets },
    { target: '.estimate-panel', title: 'Согласуйте оценку', text: 'Команда оценивает задачу в часах. Вы можете одобрить оценку, отклонить её или предложить свой вариант — без вашего решения работа не начнётся.', before: toDetail, skip: noTickets },
    { target: '.conversation', title: 'Переписка по заявке', text: 'Задавайте вопросы и уточняйте детали прямо в заявке. Для быстрой отправки нажмите Ctrl + Enter.', before: toDetail, skip: noTickets },
    { target: '.detail-grid > div:last-child > .operations-panel', title: 'Сроки работы', text: 'Сроки ответа, оценки и сдачи. Если срок подходит, полоска становится жёлтой, если прошёл — красной.', before: toDetail, skip: noTickets },
    { target: ['aside [data-nav="chats"]', '.tabbar [data-nav="chats"]'], title: 'Общий чат', text: 'Для вопросов без привязки к заявке. Если из разговора вырастет задача, команда оформит её как заявку.', before: toTickets },
    { target: '.billing-kpi-grid', title: 'Часы и счета', text: 'Баланс депозита, ставка и часы в работе. Здесь же можно купить пакет часов и открыть счета и акты.', before: async () => { if (state.view !== 'billing') await openBilling(); } },
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
function bindChatFiles() {
  const form = document.querySelector('#chat-message-form');
  if (!form) return;
  const input = form.elements.files;
  const list = form.querySelector('#chat-files');
  const paint = () => {
    list.innerHTML = [...input.files].map((file, i) => `<span class="file-chip">${icon('paperclip', 13)}<span>${esc(file.name)}</span><button type="button" data-remove-file="${i}" aria-label="Убрать ${esc(file.name)}">×</button></span>`).join('');
    list.querySelectorAll('[data-remove-file]').forEach(button => button.onclick = () => { const dt = new DataTransfer(); [...input.files].forEach((file, i) => { if (i !== Number(button.dataset.removeFile)) dt.items.add(file); }); input.files = dt.files; paint(); });
  };
  const add = files => { const dt = new DataTransfer(); [...input.files, ...files].forEach(file => dt.items.add(file)); input.files = dt.files; paint(); };
  input.addEventListener('change', () => { const ok = checkFiles([...input.files]); if (ok.length !== input.files.length) { const dt = new DataTransfer(); ok.forEach(f => dt.items.add(f)); input.files = dt.files; } paint(); });
  form.querySelector('textarea').addEventListener('paste', e => { const files = checkFiles([...(e.clipboardData?.files || [])]); if (files.length) { e.preventDefault(); add(files); toast(`Прикреплено файлов: ${files.length}`); } });
  bindDropzone(document.querySelector('.inbox-thread'), 'Отпустите, чтобы приложить к сообщению', files => { add(files); toast(`Прикреплено файлов: ${files.length} — они уйдут с сообщением`); });
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
let eventSource = null;
function initRealtime() {
  if (eventSource) {
    try { eventSource.close(); } catch(e) {}
    eventSource = null;
  }
  if (!state.user) return;
  try {
    eventSource = new EventSource('/api/events');
    eventSource.addEventListener('update', async (e) => {
      try {
        const data = JSON.parse(e.data);
        playNotificationSound();
        if (data.type === 'notification') {
          if (!state.pushEnabled) showBrowserNotification('Линия · Новое уведомление', data.text);
          toast(data.text, 'info');
          await loadNotifications();
        } else if (data.type === 'ticket_message') {
          if (state.view === 'detail' && state.current && state.current.ticket.id === data.ticket_id) {
            const textarea = document.querySelector('#message-form textarea');
            if (!textarea || !textarea.value) {
              await openTicket(data.ticket_id);
            }
          }
          await loadNotifications();
        } else if (data.type === 'chat_message') {
          if (state.view === 'chat' && state.currentChat && state.currentChat.chat.id === data.chat_id) {
            const textarea = document.querySelector('#chat-message-form textarea');
            if (!textarea || !textarea.value) {
              const fresh = await api(`/chats/${data.chat_id}`);
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
  const response = await fetch('/api' + path, {headers:{'Content-Type':'application/json'}, ...options});
  if (!response.ok) { const data = await response.json().catch(()=>({})); throw new Error(typeof data.detail === 'string' ? data.detail : `Ошибка ${response.status}`); }
  return response.json();
}
function notice() { return state.error ? `<div class="notice" role="alert">${esc(state.error)}</div>` : ''; }
async function upload(path, file, extra={}) {
  const body=new FormData();body.append('file',file);Object.entries(extra).forEach(([key,value])=>body.append(key,value));
  const response=await fetch('/api'+path,{method:'POST',body});
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(typeof data.detail==='string'?data.detail:`Ошибка ${response.status}`);}
  return response.json();
}
function showError(error) { state.error = error.message || String(error); render(); }
function setView(view) { state.view=view; state.error=''; render(); }
async function fetchNotifications() {
  const [tickets, chats] = await Promise.all([api('/notifications'), api('/chat-notifications')]);
  return [...tickets.map(n=>({...n,target:'ticket'})), ...chats.map(n=>({...n,target:'chat'}))].sort((a,b)=>b.created_at.localeCompare(a.created_at));
}
async function loadNotifications() {
  if (!state.user) return;
  const incoming = await fetchNotifications();
  const changed = JSON.stringify(incoming) !== JSON.stringify(state.notifications);
  state.notifications = incoming;
  const unread = state.notifications.filter(n=>!n.read_at).length;
  const count = document.querySelector('#notification-count');
  const previous = Number(count?.textContent || 0);
  if (count) count.textContent = unread ? String(unread) : '';
  if (count && unread > previous) { count.classList.remove('bump'); void count.offsetWidth; count.classList.add('bump'); }
  if (changed && state.view === 'notifications') renderNotifications();
}
async function refresh() {
  const staff = state.user.role !== 'customer';
  const [tickets, chats, organizations, profile, notifications, staffList, customers, queue] = await Promise.all([
    api('/tickets'), api('/chats'), api('/organizations'), api(staff?'/profile/me':'/customer-profile/me'), fetchNotifications(),
    staff?api('/staff'):null, staff?api('/customers'):null, staff?api('/work-queue'):null,
  ]);
  Object.assign(state, {tickets, chats, organizations, profile, notifications});
  state.user.name=profile.name;
  if (staff) Object.assign(state, {staff: staffList, customers, queue});
  render();
}
function renderAuth() {
  const registration = state.authMode === 'register';
  const feature = (ic, title, text) => `<div class="auth-feature"><i>${icon(ic)}</i><div><strong>${title}</strong><span>${text}</span></div></div>`;
  app.innerHTML = `<div class="auth"><section class="auth-brand"><div class="brand"><span class="brand-mark" aria-hidden="true">Л</span><span><span class="brand-name">Линия<span class="brand-dot">.</span></span><small>Кабинет заявок</small></span></div><div><h2>Заявки, переписка и часы — в одном кабинете</h2><div class="auth-features">${feature('ticket', 'Статус каждой задачи', 'От оценки до сдачи видно, на каком этапе работа и кто её ведёт.')}${feature('clock', 'Часы согласуете вы', 'Работа начинается после того, как вы одобрите оценку трудозатрат.')}${feature('send', 'Уведомления в мессенджерах', 'Заявки и переписка доступны в Telegram и MAX.')}</div></div><a class="auth-foot" href="/landing">О сервисе →</a></section><main class="auth-main"><div class="auth-card"><div class="auth-mobile-brand"><span class="brand-mark" aria-hidden="true">Л</span>Линия</div><div class="top-text"><h1>${registration ? 'Создать кабинет' : 'Вход в кабинет'}</h1><p class="lead">${registration ? 'Уже есть кабинет?' : 'Нет кабинета?'} <button class="auth-switch" id="auth-switch" type="button">${registration ? 'Войти' : 'Зарегистрироваться'}</button></p></div>${notice()}<form class="form" id="auth-form">${registration ? '<label>Ваше имя<input class="field" name="name" required minlength="2" maxlength="100" autocomplete="name"></label>' : ''}<label>Email<input class="field" name="email" type="email" required autocomplete="email" placeholder="name@company.ru"></label><label>Пароль<input class="field" name="password" type="password" required minlength="8" autocomplete="${registration ? 'new-password' : 'current-password'}"></label><label class="row" style="display:flex;font-weight:600"><input type="checkbox" id="show-password" style="width:18px;height:18px;accent-color:var(--accent)">Показать пароль</label><button class="button primary">${registration ? 'Зарегистрироваться' : 'Войти'}</button></form></div></main></div>`;
  document.querySelector('#auth-switch').onclick = () => { state.authMode = registration ? 'login' : 'register'; state.error = ''; renderAuth(); };
  document.querySelector('#show-password').onchange = e => { document.querySelector('#auth-form [name="password"]').type = e.target.checked ? 'text' : 'password'; };
  document.querySelector('#auth-form').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button.primary'); button.disabled = true; const data = Object.fromEntries(new FormData(e.target)); try { state.user = await api(registration ? '/register' : '/login', { method: 'POST', body: JSON.stringify(data) }); state.view = state.user.role === 'customer' ? 'tickets' : 'queue'; state.error = ''; await refresh(); await openHash(); maybeStartTour(); } catch (error) { showError(error); } };
}
function shell(title, action, body, opts = {}) {
  const staff = state.user.role !== 'customer';
  const admin = state.user.role === 'admin';
  const dispatcher = isDispatcher();
  const v = state.view;
  const unread = state.notifications.filter(n => !n.read_at).length;
  const chatUnread = state.notifications.filter(n => n.target === 'chat' && !n.read_at).length;
  const activeTickets = state.tickets.filter(t => !['done', 'closed'].includes(t.status)).length;
  const ticketsActive = ['tickets', 'detail', 'new'].includes(v);
  const chatsActive = ['chats', 'chat'].includes(v);
  const item = (id, label, ic, active, count, tone = '') => `<button class="nav-item ${active ? 'active' : ''}" data-nav="${id}" ${active ? 'aria-current="page"' : ''}>${icon(ic)}<span>${label}</span>${count ? `<span class="nav-count ${tone}">${count}</span>` : ''}</button>`;
  const groups = [
    ['Работа', [staff && item('queue', 'Рабочая очередь', 'queue', v === 'queue', state.queue.length, 'accent'), item('tickets', staff ? 'Заявки' : 'Мои заявки', 'ticket', ticketsActive, activeTickets), item('chats', 'Общий чат', 'chat', chatsActive, chatUnread, 'accent')]],
    ['Клиенты', [(dispatcher || (!staff && state.organizations.length)) && item('organizations', staff ? 'Компании' : 'Моя компания', 'building', v === 'organizations'), item('kb', 'База знаний', 'book', v === 'kb')]],
    ['Финансы', [item('billing', 'Биллинг и счета', 'wallet', v === 'billing'), staff && dispatcher && item('analytics', 'Аналитика и SLA', 'chart', v === 'analytics')]],
    ['Настройки', [admin && item('team', 'Команда', 'users', v === 'team'), item('messengers', 'Мессенджеры', 'send', v === 'messengers'), admin && item('webhooks', 'Вебхуки', 'link', v === 'webhooks')]],
  ].map(([label, items]) => { const list = items.filter(Boolean); return list.length ? `<div class="nav-group-label">${label}</div>${list.join('')}` : ''; }).join('');
  const tab = (id, label, ic, active, count) => `<button class="${active ? 'active' : ''}" data-nav="${id}" ${active ? 'aria-current="page"' : ''}>${icon(ic, 22)}${label}${count ? `<span class="dot-count">${count}</span>` : ''}</button>`;
  const tabs = [
    staff ? tab('queue', 'Очередь', 'queue', v === 'queue') : tab('tickets', 'Заявки', 'ticket', ticketsActive),
    staff ? tab('tickets', 'Заявки', 'ticket', ticketsActive) : tab('notifications', 'События', 'bell', v === 'notifications', unread),
    tab('chats', 'Чат', 'chat', chatsActive, chatUnread),
    tab('billing', 'Счета', 'wallet', v === 'billing'),
    `<button data-nav-toggle aria-controls="sidebar">${icon('more', 22)}Ещё</button>`,
  ].join('');
  const role = admin ? 'Администратор' : state.user.is_manager ? 'Менеджер' : 'Сотрудник';
  const subtitle = staff ? (state.profile?.job_title || role) : (state.organizations[0]?.name || state.profile?.company_name || 'Заказчик');
  const kicker = opts.kicker ?? (staff ? 'Рабочее место' : 'Личный кабинет');
  const viewKey = `${v}:${v === 'detail' ? state.current?.ticket?.id : v === 'chat' ? state.currentChat?.chat?.id : ''}`;
  clearTimeout(loadingTimer);
  const preserved = viewKey === lastViewKey ? captureUi() : null;
  const entering = viewKey !== lastViewKey && !reduceMotion();
  lastViewKey = viewKey;
  document.body.classList.remove('nav-open');
  app.innerHTML = `<div class="shell"><aside id="sidebar" aria-label="Основное меню"><div class="brand"><span class="brand-mark" aria-hidden="true">Л</span><span><span class="brand-name">Линия<span class="brand-dot">.</span></span><small>Кабинет заявок</small></span></div><nav class="nav">${groups}</nav><div class="aside-bottom aside-user">${avatar(state.profile, 'small')}<div class="aside-user-meta"><strong>${esc(state.user.name)}</strong><small>${esc(subtitle)}</small></div><button id="theme-toggle" class="aside-logout" aria-label="Сменить тему">${icon(effectiveTheme() === 'dark' ? 'sun' : 'moon')}</button><button id="logout" class="aside-logout" aria-label="Выйти" title="Выйти">${icon('logout')}</button></div></aside><div class="nav-backdrop" data-nav-close></div><div class="workspace"><header class="topbar"><button class="icon-btn menu-btn" data-nav-toggle aria-controls="sidebar" aria-label="Открыть меню">${icon('menu')}</button><button type="button" class="global-search" id="open-palette" aria-haspopup="dialog">${icon('search', 17)}<span class="global-search-text">Поиск заявок, чатов и разделов</span><kbd>Ctrl K</kbd></button><span class="topbar-spacer"></span><button class="button primary" id="top-new-ticket">${icon('plus', 16)}<span>Новая заявка</span></button>${staff ? '' : `<button class="icon-btn" id="help-tour" aria-label="Пройти обучение по кабинету" title="Обучение по кабинету">${icon('help')}</button>`}<button class="icon-btn ${v === 'notifications' ? 'active' : ''}" data-nav="notifications" aria-label="Уведомления${unread ? `: ${unread} новых` : ''}">${icon('bell')}<span class="dot-count" id="notification-count">${unread || ''}</span></button><button class="top-profile ${v === 'profile' ? 'active' : ''}" data-nav="profile" aria-label="Мой профиль">${avatar(state.profile, 'small')}${icon('chevron', 14)}</button></header><main id="main" class="${entering ? 'is-entering' : ''}">${opts.crumbs ? `<nav class="crumbs" aria-label="Навигационная цепочка">${opts.crumbs}</nav>` : ''}<div class="top"><div class="top-text">${opts.badges ? `<div class="top-badges">${opts.badges}</div>` : kicker ? `<div class="eyebrow">${kicker}</div>` : ''}<h1>${esc(title)}</h1>${opts.lead ? `<p class="lead">${opts.lead}</p>` : ''}</div>${action ? `<div class="top-actions">${action}</div>` : ''}</div>${notice()}${body}</main></div><nav class="tabbar" aria-label="Быстрая навигация">${tabs}</nav></div>`;
  const navActions = {
    queue: () => setView('queue'), tickets: () => setView('tickets'), notifications: () => setView('notifications'), profile: () => setView('profile'),
    organizations: () => setView('organizations'), team: () => setView('team'), kb: () => openKb(), billing: () => openBilling(),
    analytics: () => openAnalytics(), webhooks: () => openWebhooks(), messengers: () => openMessengers(),
    chats: async () => { if (staff) return setView('chats'); try { const chat = await api('/chats', { method: 'POST' }); await refresh(); await openChat(chat.id); } catch (error) { showError(error); } },
  };
  document.querySelectorAll('[data-nav]').forEach(button => button.onclick = () => { document.body.classList.remove('nav-open'); if (location.hash) history.replaceState(null, '', location.pathname); navActions[button.dataset.nav]?.(); });
  document.querySelectorAll('[data-nav-toggle]').forEach(button => button.onclick = () => document.body.classList.toggle('nav-open'));
  document.querySelector('[data-nav-close]').onclick = () => document.body.classList.remove('nav-open');
  document.querySelector('#top-new-ticket').onclick = () => setView('new');
  document.querySelector('#open-palette').onclick = () => openPalette();
  document.querySelector('#help-tour')?.addEventListener('click', () => startTour());
  document.querySelector('#theme-toggle').onclick = toggleTheme;
  syncThemeUi();
  if (entering) queueMicrotask(animateEntrance);
  queueMicrotask(() => { bindDrafts(); if (preserved) restoreUi(preserved); });
  document.querySelector('#logout').onclick = async () => { await disablePush(); await api('/logout', { method: 'POST' }); state.user = null; state.current = null; state.bots = null; state.pairings = {}; state.pendingOps = {}; state.error = ''; renderAuth(); };
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
  const pending = all.filter(t => t.estimate_state === 'pending');
  const pendingMinutes = pending.reduce((sum, t) => sum + (t.effort_minutes || 0), 0);
  const parts = Object.keys(statusChipNames).map(key => ({ key, label: statusChipNames[key], count: all.filter(t => t.status === key).length }));
  const chart = parts.filter(p => p.count).map(p => `<button class="portfolio-segment ${p.key}" data-overview-filter="${p.key}" style="width:${p.count / total * 100}%" aria-label="${p.label}: ${p.count}" title="${p.label}: ${p.count}"></button>`).join('');
  return `<section class="panel overview-card" aria-label="Сводка по заявкам"><div><div class="overview-head"><span class="eyebrow">По статусам</span><strong>${total} ${plural(total, ['заявка', 'заявки', 'заявок'])} · ${done} завершено</strong></div><div class="portfolio-track" role="group" aria-label="Фильтр по статусам заявок">${chart}</div><div class="portfolio-legends">${parts.map(p => `<span>${p.label} <strong>${p.count}</strong></span>`).join('')}</div></div><div><span class="eyebrow">Согласовано часов</span><strong class="big">${hours(approved)}</strong><span class="muted">${approvedTickets.length ? `по ${approvedTickets.length} ${plural(approvedTickets.length, ['заявке', 'заявкам', 'заявкам'])}` : 'Пока нет согласованных оценок'}</span></div><div><span class="eyebrow">${staff ? 'Ждут решения заказчика' : 'Ждут вашего решения'}</span><strong class="big">${pending.length} ${plural(pending.length, ['оценка', 'оценки', 'оценок'])}</strong><span class="muted">${pending.length ? `на ${hours(pendingMinutes)}` : 'Нет оценок на согласовании'}</span></div></section>`;
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
function renderTickets() {
  const staff = state.user.role !== 'customer';
  const dispatcher = isDispatcher();
  const owned = state.tickets.filter(t => state.owner === 'mine' ? t.assignee_id === state.user.id : state.owner === 'unassigned' ? !t.assignee_id : true);
  if (!statusChipNames[state.filter]) state.filter = 'all';
  const visible = owned.filter(t => state.filter === 'all' || t.status === state.filter);
  const chip = (key, label, count, dot = '') => `<button type="button" class="chip ${state.filter === key ? 'active' : ''}" data-status-filter="${key}" aria-pressed="${state.filter === key}">${dot ? `<span class="dot ${dot}"></span>` : ''}${label} <i>${count}</i></button>`;
  const chips = chip('all', 'Все', owned.length) + Object.entries(statusChipNames).map(([key, label]) => chip(key, label, owned.filter(t => t.status === key).length, key)).join('');
  const ownerSelect = staff ? `<label class="select-inline"><span>Ответственный</span><select id="owner-filter"><option value="all">Все</option><option value="mine">Мои</option>${dispatcher ? '<option value="unassigned">Без ответственного</option>' : ''}</select></label>` : '';
  const ticketRow = t => {
    const sla = nearestSla(t);
    const finished = ['done', 'closed'].includes(t.status);
    const deadline = sla ? slaTag(sla) : finished ? `<span class="sla met">${icon('check', 13)}Завершена</span>` : `<span class="tdate">${esc(t.next_step || '—')}</span>`;
    return `<button class="trow" data-ticket="${t.id}"><span class="tnum">${t.id}</span><span class="ttitle"><strong>${esc(t.title)}</strong><small>${esc([t.customer_name, staff ? t.customer_company : '', serviceNames[t.service_type]].filter(Boolean).join(' · '))}</small></span><span class="badge ${esc(t.status)}">${statusNames[t.status]}</span><span>${deadline}</span><span class="tnum-strong">${t.effort_minutes ? hours(t.effort_minutes) : '—'}</span><span class="twho">${avatarOf(t.assignee_id, t.assignee_name)}<span>${esc(t.assignee_name || (staff ? 'Не назначен' : 'Назначается'))}</span></span><span class="tdate">${date(t.updated_at)}</span></button>`;
  };
  const head = '<div class="table-head" aria-hidden="true"><span>№</span><span>Заявка</span><span>Статус</span><span>Ближайший срок</span><span>Оценка</span><span>Ответственный</span><span>Обновлена</span></div>';
  shell(staff ? 'Заявки' : 'Мои заявки', '', `${portfolioOverview(owned)}<section class="panel"><div class="toolbar"><div class="chips" role="group" aria-label="Фильтр по статусу">${chips}</div><div class="ticket-tools"><input class="field ticket-search" id="ticket-search" type="search" maxlength="100" aria-label="Поиск по заявкам" placeholder="Номер, тема, клиент" value="${esc(state.search)}">${ownerSelect}</div></div>${head}<div id="ticket-list"></div><div class="toolbar" style="border-top:1px solid var(--line-light);border-bottom:0;min-height:52px"><span class="muted" id="ticket-count"></span><span class="kbd-hint"><kbd>J</kbd><kbd>K</kbd> по строкам · <kbd>Enter</kbd> открыть</span></div></section>`, { kicker: staff ? (dispatcher ? 'Все клиенты' : 'Назначенные мне и команде') : 'Личный кабинет' });
  const updateList = () => {
    const query = state.search.trim().toLocaleLowerCase('ru-RU');
    const matches = query ? visible.filter(t => [t.id, t.title, t.description, t.customer_name, t.customer_company, t.assignee_name, statusNames[t.status]].some(value => String(value || '').toLocaleLowerCase('ru-RU').includes(query))) : visible;
    document.querySelector('#ticket-count').textContent = `Показано ${matches.length} из ${owned.length}`;
    document.querySelector('#ticket-list').innerHTML = matches.map(ticketRow).join('') || (query ? '<div class="empty"><strong>Ничего не найдено</strong>Попробуйте другой запрос или фильтр.</div>' : '<div class="empty"><strong>Заявок пока нет</strong>Создайте новую заявку или выберите другой фильтр.</div>');
    document.querySelectorAll('#ticket-list [data-ticket]').forEach(el => el.onclick = () => openTicket(Number(el.dataset.ticket)));
  };
  const ownerFilter = document.querySelector('#owner-filter');
  if (ownerFilter) { ownerFilter.value = state.owner; ownerFilter.onchange = e => { state.owner = e.target.value; renderTickets(); }; }
  document.querySelector('#ticket-search').oninput = e => { state.search = e.target.value; updateList(); };
  updateList();
  document.querySelectorAll('[data-status-filter],[data-overview-filter]').forEach(button => button.onclick = () => { const key = button.dataset.statusFilter || button.dataset.overviewFilter; state.filter = state.filter === key && button.dataset.overviewFilter ? 'all' : key; renderTickets(); });
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
function renderNotifications() {
  const rows=state.notifications.map(n=>`<button class="ticket-row notification-row ${n.read_at?'':'unread'}" data-notice="${n.id}" data-target="${n.target}" data-record="${n.target==='chat'?n.chat_id:n.ticket_id}"><span><strong>${esc(n.text)}</strong><small>${n.target==='chat'?'Общий чат':'Заявка №'+n.ticket_id} · ${date(n.created_at)}</small></span><span class="badge ${n.read_at?'':'new'}">${n.read_at?'Прочитано':'Новое'}</span></button>`).join('');
  const pushAction=pushSupported()&&!state.pushEnabled&&Notification.permission!=='denied'?`<button class="button" id="enable-push">${icon('bell',16)}Уведомления на телефон</button>`:'';
  shell('Уведомления',pushAction,`<div class="panel">${rows||'<div class="empty"><strong>Уведомлений пока нет</strong>Здесь появятся события по вашим заявкам.</div>'}</div>`);
  document.querySelector('#enable-push')?.addEventListener('click',async e=>{e.target.disabled=true;try{await enablePush();toast('Уведомления включены');renderNotifications();}catch(error){toast(error.message,'error');e.target.disabled=false;}});
  document.querySelectorAll('[data-notice]').forEach(el=>el.onclick=async()=>{try{await api(`/${el.dataset.target==='chat'?'chat-notifications':'notifications'}/${el.dataset.notice}/read`,{method:'POST'});await refresh();if(el.dataset.target==='chat')await openChat(Number(el.dataset.record));else await openTicket(Number(el.dataset.record));}catch(error){showError(error);}});
}
function renderNew() {
  const staff=state.user.role!=='customer';
  const dispatcher=state.user.role==='admin'||state.user.is_manager;
  const customerField=staff?`<label>Заказчик<select class="field" name="customer_id" required><option value="">Выберите заказчика</option>${state.customers.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.email)}</option>`).join('')}</select></label>`:'';
  const assigneeField=dispatcher?`<label>Ответственный<select class="field" name="assignee_id"><option value="">Назначить позже</option>${state.staff.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></label>`:staff?'<p class="muted">Вы будете назначены ответственным за эту заявку.</p>':'';
  const help=staff?['Выберите заказчика, которому нужна помощь.','Опишите задачу его словами — он увидит текст в своём кабинете.','После создания заказчик получит уведомление.']:['Коротко назовите задачу, чтобы её было легко найти.','Напишите, какой результат нужен и какие детали важны.','Команда оценит трудозатраты в часах; решение останется за вами.'];
  shell('Новая заявка','',`<button class="back" id="back">← К заявкам</button><div class="form-layout"><div class="panel content"><h2>${staff?'Создать заявку для заказчика':'Опишите задачу'}</h2>${staff&&!state.customers.length?'<div class="notice">Нет доступных заказчиков. Менеджер или администратор может создать заявку для любого зарегистрированного заказчика.</div>':''}<form class="form" id="ticket-form">${customerField}<label>Тема<input class="field" name="title" required minlength="3" maxlength="140" placeholder="Коротко о задаче"></label><div id="kb-suggest-box" class="kb-suggest-box" style="display:none"></div><label>Описание<textarea name="description" data-draft="new-ticket" required minlength="5" maxlength="10000" placeholder="Что нужно сделать? Укажите важные детали."></textarea></label>${assigneeField}<button class="button primary" ${staff&&!state.customers.length?'disabled':''}>Создать заявку</button></form></div><div class="form-help"><span>ПОДСКАЗКА</span><h2>Чтобы быстрее начать</h2>${help.map((item,index)=>`<div class="help-step"><b>${String(index+1).padStart(2,'0')}</b><p>${item}</p></div>`).join('')}</div></div>`);
  document.querySelector('#ticket-form [name="title"]').parentElement.insertAdjacentHTML('beforebegin',`<label>Тип задачи<select class="field" name="service_type">${Object.entries(serviceNames).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label>`);
  document.querySelector('#ticket-form [name="service_type"]').onchange=e=>{document.querySelector('#ticket-form [name="description"]').placeholder=serviceHints[e.target.value];document.querySelector('.form-help h2').textContent=serviceNames[e.target.value];};
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
  document.querySelector('#ticket-form button').insertAdjacentHTML('beforebegin',`<label id="visibility-field" ${!staff&&!state.organizations.length?'hidden':''}>Кому видна заявка<select class="field" name="visibility"><option value="organization">Всей компании</option><option value="private">Только автору</option></select></label><label>Файлы к заявке<input class="field" name="files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.zip"><small>До 10 МБ на файл. Можно приложить после создания.</small></label>`);
  if(!staff&&state.organizations[0]?.members.some(m=>m.user_id===state.user.id&&m.role==='viewer')){document.querySelector('#visibility-field').hidden=true;document.querySelector('#visibility-field select').value='private';}
  if(staff)document.querySelector('#ticket-form [name="customer_id"]').onchange=e=>{const member=state.organizations.some(o=>o.members.some(m=>m.user_id===Number(e.target.value)));document.querySelector('#visibility-field').hidden=!member;document.querySelector('#visibility-field select').value=member?'organization':'private';};
  document.querySelector('#back').onclick=()=>setView('tickets');
  document.querySelector('#ticket-form').onsubmit=async e=>{e.preventDefault();const files=[...e.target.elements.files.files];const data=Object.fromEntries(new FormData(e.target));delete data.files;if(document.querySelector('#visibility-field').hidden)data.visibility='private';if(staff){data.customer_id=Number(data.customer_id);if(dispatcher)data.assignee_id=data.assignee_id?Number(data.assignee_id):null;}e.target.querySelector('button').disabled=true;try{const ticket=await api('/tickets',{method:'POST',body:JSON.stringify(data)});clearDraft('new-ticket');const failed=[];for(const file of files){try{await upload(`/tickets/${ticket.id}/attachments`,file);}catch(error){failed.push(file.name);}}await refresh();await openTicket(ticket.id);if(failed.length){state.error=`Заявка создана, но файлы не загрузились: ${failed.join(', ')}. Прикрепите их в карточке.`;render();}}catch(error){showError(error);}};
}
async function openTicket(id) {if(state.view!=='detail'||state.current?.ticket?.id!==id)delayedLoading(`Заявка №${id}`,'detail');try{const sameTicket=state.current?.ticket?.id===id;state.current=await api(`/tickets/${id}`);if(!sameTicket)state.detailTab='messages';state.current.assignee_profile=state.current.ticket.assignee_id?await api(`/staff/${state.current.ticket.assignee_id}/profile`).catch(()=>null):null;state.gitLinks=await api(`/tickets/${id}/git-links`).catch(()=>[]);state.view='detail';state.error='';render();}catch(error){showError(error);}}
function ticketProgress(ticket, estimates) {
  const estimate = estimates[0];
  const step = ['done', 'closed'].includes(ticket.status) ? 4 : ['working', 'waiting'].includes(ticket.status) ? 3 : estimate?.state === 'approved' ? 2 : estimate ? 1 : 0;
  const steps = ['Создана', 'Оценка', 'Согласование', 'В работе', 'Готово'];
  return `<section class="ticket-progress" aria-label="Этапы заявки"><ol>${steps.map((label, index) => `<li class="${index < step ? 'passed' : index === step ? 'current' : ''}" ${index === step ? 'aria-current="step"' : ''}><span class="step-dot">${index < step ? '✓' : index + 1}</span><span class="step-label">${label}</span></li>`).join('')}</ol></section>`;
}
function renderCsat(t, staff) {
  if (!['done', 'closed'].includes(t.status)) return '';
  if (!staff) {
    if (t.rating) {
      return `<div class="csat-box"><div class="csat-title">Ваша оценка работы</div><div class="csat-stars">${[1,2,3,4,5].map(s=>`<span class="csat-star active">${s<=t.rating?'★':'☆'}</span>`).join('')}</div>${t.rating_comment?`<p style="margin:6px 0;font-size:13px">«${esc(t.rating_comment)}»</p>`:''}<div class="csat-result">✓ Спасибо за вашу оценку!</div></div>`;
    }
    return `<div class="csat-box" id="csat-form-wrap"><div class="csat-title">Оцените качество решения задачи</div><div class="csat-subtitle">Поставьте оценку от 1 до 5 звёзд</div><div class="csat-stars" id="csat-star-picker">${[1,2,3,4,5].map(s=>`<span class="csat-star" data-val="${s}">★</span>`).join('')}</div><textarea class="csat-comment" id="csat-comment" placeholder="Что вам понравилось или что улучшить? (необязательно)" maxlength="2000"></textarea><div><button class="button primary" id="csat-submit" disabled>Отправить оценку</button></div></div>`;
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

function renderDetail() {
  const { ticket: t, messages, events, estimates = [] } = state.current;
  const staff = state.user.role !== 'customer';
  const dispatcher = isDispatcher();
  const viewer = !staff && t.visibility === 'organization' && state.organizations.some(o => o.id === t.organization_id && o.members.some(m => m.user_id === state.user.id && m.role === 'viewer'));
  const canStatus = staff && (state.user.role === 'admin' || t.assignee_id === state.user.id);
  const late = ticketSla(t).filter(s => s.tone === 'late');
  const badges = `<span class="badge ${esc(t.status)}">${statusNames[t.status]}</span>${late.map(s => `<span class="sla late">${icon('clock', 13)}${s.label} ${s.label === 'Ответ' ? 'просрочен' : 'просрочена'} на ${formatDuration(-s.diff)}</span>`).join('')}<span class="badge">${serviceNames[t.service_type] || 'Другое'}</span>`;
  const lead = [`№${t.id}`, staff ? (t.customer_company || t.customer_name) : '', `создана ${date(t.created_at)}`, t.organization_id ? (t.visibility === 'organization' ? 'видна всей компании' : 'личная заявка') : ''].filter(Boolean).map(esc).join(' · ');
  const statusControl = canStatus ? `<label class="select-inline"><span>Статус</span><select id="status">${Object.entries(statusNames).map(([key, label]) => `<option value="${key}">${label}</option>`).join('')}</select></label>` : '';
  const assignee = dispatcher ? `<select id="assignee" aria-label="Ответственный"><option value="">Без ответственного</option>${state.staff.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select>` : `<span class="meta-person">${t.assignee_id ? avatarOf(t.assignee_id, t.assignee_name) : ''}${esc(t.assignee_name || 'Не назначен')}</span>`;
  const chat = messages.map(m => `<div class="message ${m.author_id === state.user.id ? 'mine' : ''}"><small>${esc(m.author_name)} · ${date(m.created_at)}</small>${esc(m.body)}</div>`).join('') || '<div class="empty">Сообщений пока нет. Напишите первое сообщение.</div>';
  const history = events.map(e => `<li><div>${esc(e.actor_name)}: ${e.kind === 'status' ? 'статус изменён на «' + esc(statusNames[e.new_value] || e.new_value) + '»' : 'ответственный изменён'}<small>${date(e.created_at)}</small></div></li>`).join('');
  const person = state.current.assignee_profile;
  if (!staff && state.detailTab === 'notes') state.detailTab = 'messages';
  const tab = state.detailTab || 'messages';
  const tabButton = (id, label, count, ic = '') => `<button type="button" role="tab" class="tab ${tab === id ? 'active' : ''}" aria-selected="${tab === id}" data-detail-tab="${id}">${ic}${label}${count !== undefined ? ` <i>${count}</i>` : ''}</button>`;
  const composer = viewer ? '<div class="content muted">У вас доступ только к просмотру заявки.</div>' : t.status !== 'closed' ? `<form class="composer" id="message-form"><label class="visually-hidden" for="message-body">Сообщение</label><textarea id="message-body" data-draft="ticket-${t.id}" name="body" required maxlength="10000" placeholder="${staff ? 'Напишите сообщение заказчику…' : 'Напишите сообщение команде…'}"></textarea><div class="composer-bar"><span class="composer-hint">Ctrl + Enter — отправить</span><button class="button primary">Отправить</button></div></form>` : '<div class="content muted">Заявка закрыта. Переписка доступна для чтения.</div>';
  const meta = `<dl class="meta"><dt>Заказчик</dt><dd>${esc(t.customer_name)}${staff && t.customer_company ? `<small>${esc(t.customer_company)}</small>` : ''}</dd><dt>Ответственный</dt><dd>${assignee}</dd><dt>Тип задачи</dt><dd>${serviceNames[t.service_type] || 'Другое'}</dd>${t.organization_id ? `<dt>Видимость</dt><dd>${t.visibility === 'organization' ? 'Вся компания' : 'Личная заявка'}</dd>` : ''}<dt>Создана</dt><dd>${date(t.created_at)}</dd>${t.created_by_name ? `<dt>Создал</dt><dd>${esc(t.created_by_name)}</dd>` : ''}</dl>`;
  const personCard = person ? `<section class="panel content assigned-person"><div class="person-heading">${avatar(person)}<div><span class="eyebrow">${staff ? 'Ответственный' : 'Ваш специалист'}</span><h2>${esc(person.name)}</h2><p>${esc(person.job_title || 'Сотрудник команды')}</p></div></div>${person.bio ? `<p class="person-bio">${esc(person.bio)}</p>` : ''}</section>` : '';
  const body = `${ticketProgress(t, estimates)}<div class="detail-grid"><div>${t.next_step ? `<div class="next-step"><span>Следующий шаг</span><strong>${esc(t.next_step)}</strong></div>` : ''}<section class="panel content"><h2>Описание задачи</h2><p class="description">${esc(t.description)}</p>${state.current.linked_chat ? `<button class="button linked-chat" id="linked-chat">${icon('chat', 16)}Обсуждение в общем чате</button>` : ''}</section><section class="panel conversation"><div class="tabs" role="tablist" aria-label="Обсуждение заявки">${tabButton('messages', 'Переписка', messages.length)}${staff ? tabButton('notes', 'Заметки команды', undefined, icon('lock', 14)) : ''}${tabButton('history', 'История', events.length)}</div><div class="tab-pane" data-pane="messages" ${tab !== 'messages' ? 'hidden' : ''}><div class="messages">${chat}</div>${composer}</div>${staff ? `<div class="tab-pane" data-pane="notes" ${tab !== 'notes' ? 'hidden' : ''}><div id="internal-notes-container"></div></div>` : ''}<div class="tab-pane" data-pane="history" ${tab !== 'history' ? 'hidden' : ''}>${history ? `<ol class="events">${history}</ol>` : '<div class="empty">Статус и ответственный пока не менялись.</div>'}</div></section>${renderCsat(t, staff)}</div><div><section class="panel content"><h2>Детали</h2>${meta}</section>${personCard}</div></div>`;
  shell(t.title, statusControl, body, { crumbs: `<button class="crumb-link" id="back">Заявки</button><span aria-hidden="true">/</span><span>№${t.id}</span>`, badges, lead });
  renderEstimate(t, estimates, staff);
  renderOperations();
  document.querySelector('#linked-chat')?.addEventListener('click', () => openChat(state.current.linked_chat.chat_id));
  document.querySelector('#back').onclick = () => setView('tickets');
  if (dispatcher) document.querySelector('#assignee').value = t.assignee_id || '';
  if (canStatus) document.querySelector('#status').value = t.status;
  document.querySelectorAll('[data-detail-tab]').forEach(button => button.onclick = () => { state.detailTab = button.dataset.detailTab; document.querySelectorAll('[data-detail-tab]').forEach(x => { const on = x === button; x.classList.toggle('active', on); x.setAttribute('aria-selected', String(on)); }); document.querySelectorAll('.tab-pane').forEach(pane => pane.hidden = pane.dataset.pane !== state.detailTab); });
  const box = document.querySelector('.tab-pane[data-pane="messages"] .messages');
  if (box) box.scrollTop = box.scrollHeight;
  popLastMessage(box);
  document.querySelector('#assignee')?.addEventListener('change', async e => { try { await api(`/tickets/${t.id}/assignee`, { method: 'PATCH', body: JSON.stringify({ assignee_id: e.target.value ? Number(e.target.value) : null }) }); toast('Ответственный обновлён'); await refresh(); await openTicket(t.id); } catch (error) { showError(error); } });
  document.querySelector('#status')?.addEventListener('change', async e => { try { await api(`/tickets/${t.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: e.target.value }) }); toast(`Статус изменён: ${statusNames[e.target.value]}`); await refresh(); await openTicket(t.id); } catch (error) { showError(error); } });
  bindCtrlEnter('#message-form');
  document.querySelector('#message-form')?.addEventListener('submit', async e => { e.preventDefault(); const body = new FormData(e.target).get('body'); e.target.querySelector('button.primary').disabled = true; try { await api(`/tickets/${t.id}/messages`, { method: 'POST', body: JSON.stringify({ body, request_id: crypto.randomUUID() }) }); clearDraft(`ticket-${t.id}`); state.justSent = true; await refresh(); await openTicket(t.id); } catch (error) { showError(error); } });
  if (staff) {
    loadInternalNotes(t.id);
    if (t.status !== 'closed') renderCannedTrigger();
  }
  if (!viewer && t.status !== 'closed') bindDropzone(document.querySelector('.conversation'), 'Отпустите, чтобы прикрепить к заявке', async files => {
    toast(`Загружаем файлы: ${files.length}`, 'info');
    const failed = [];
    for (const file of files) { try { await upload(`/tickets/${t.id}/attachments`, file); } catch (error) { failed.push(file.name); } }
    if (failed.length) toast(`Не удалось загрузить: ${failed.join(', ')}`, 'error'); else toast(files.length === 1 ? 'Файл прикреплён к заявке' : `Файлы прикреплены к заявке: ${files.length}`);
    await refresh(); await openTicket(t.id);
  });
  attachCsatHandlers(t);
}
function renderEstimate(ticket, estimates, staff) {
  const latest=estimates[0];
  const legacy=latest&&latest.effort_minutes===null;
  const canCreate=staff&&ticket.assignee_id===state.user.id&&ticket.status!=='closed'&&(!latest||legacy||['rejected','revision_requested'].includes(latest.state));
  const canDecide=!staff&&(ticket.visibility!=='organization'||!state.organizations.some(o=>o.id===ticket.organization_id&&o.members.some(m=>m.user_id===state.user.id&&m.role==='viewer')))&&(ticket.customer_id===state.user.id||state.organizations.some(o=>o.id===ticket.organization_id&&o.members.some(m=>m.user_id===state.user.id&&m.role==='owner')))&&latest?.state==='pending'&&!legacy&&ticket.status!=='closed';
  const history=estimates.map(e=>`<div class="estimate-version"><div class="row"><strong>Версия ${e.version} · ${e.effort_minutes===null?'Старая оценка без часов':hours(e.effort_minutes)}</strong><span class="badge">${estimateNames[e.state]||'Требуется новая оценка'}</span></div><div class="muted">Оценил ${esc(e.author_name)} · ${date(e.created_at)} · на оценку потрачено ${e.assessment_minutes} мин.</div>${e.note?`<p>${esc(e.note)}</p>`:''}${e.customer_comment?`<p>Комментарий заказчика: ${esc(e.customer_comment)}</p>`:''}${e.proposed_effort_minutes!==null?`<p>Предложение заказчика: ${hours(e.proposed_effort_minutes)}</p>`:''}</div>`).join('');
  const create=canCreate?`<form class="form" id="estimate-form"><label>Плановые трудозатраты, часов<input class="field" name="effort_hours" type="number" min="0.25" max="1666" step="0.25" required></label><label>Потрачено на оценку, минут<input class="field" name="minutes" type="number" min="1" max="100000" step="1" required></label><label>Пояснение к оценке<textarea name="note" maxlength="3000" placeholder="Что входит в работу"></textarea></label><button class="button primary">Отправить оценку заказчику</button></form>`:'';
  const decide=canDecide?`<div class="row estimate-actions"><button class="button primary" id="approve-estimate">Одобрить</button><button class="button" id="reject-estimate">Отклонить</button></div><form class="form" id="revision-form"><label>Ваш вариант, часов (необязательно)<input class="field" name="effort_hours" type="number" min="0.25" max="1666" step="0.25"></label><label>Что скорректировать<textarea name="comment" maxlength="3000" placeholder="Напишите ваши пожелания"></textarea></label><button class="button">Запросить корректировку</button></form>`:'';
  document.querySelector('.detail-grid>div:first-child>.panel.content').insertAdjacentHTML('afterend',`<section class="panel content estimate-panel ${canCreate||canDecide?'needs-action':''}">${canCreate||canDecide?'<div class="eyebrow" style="color:var(--accent-ink);margin-bottom:6px">Ваше действие</div>':''}<h2>Оценка трудозатрат</h2>${legacy?'<div class="notice">Старая оценка была указана в деньгах. Нужна новая оценка в часах.</div>':''}${latest?history:'<p class="muted">Оценка ещё не подготовлена.</p>'}${create}${decide}</section>`);
  const update=async(path,data,message)=>{try{await api(path,{method:'POST',body:JSON.stringify(data)});if(message)toast(message);await refresh();await openTicket(ticket.id);}catch(error){showError(error);}};
  document.querySelector('#estimate-form')?.addEventListener('submit',e=>{e.preventDefault();const data=new FormData(e.target);update(`/tickets/${ticket.id}/estimates`,{effort_minutes:Math.round(Number(data.get('effort_hours'))*60),assessment_minutes:Number(data.get('minutes')),note:data.get('note')},'Оценка отправлена заказчику');});
  document.querySelector('#approve-estimate')?.addEventListener('click',()=>update(`/tickets/${ticket.id}/estimates/decision`,{estimate_id:latest.id,action:'approve'},'Оценка одобрена — команда приступит к работе'));
  document.querySelector('#reject-estimate')?.addEventListener('click',()=>update(`/tickets/${ticket.id}/estimates/decision`,{estimate_id:latest.id,action:'reject'},'Оценка отклонена'));
  document.querySelector('#revision-form')?.addEventListener('submit',e=>{e.preventDefault();const data=new FormData(e.target);update(`/tickets/${ticket.id}/estimates/decision`,{estimate_id:latest.id,action:'request_revision',comment:data.get('comment'),proposed_effort_minutes:data.get('effort_hours')===''?null:Math.round(Number(data.get('effort_hours'))*60)},'Запрос на корректировку отправлен');});
}
function renderOperations(){
  const {ticket:t,time_entries=[],hour_requests=[],attachments=[]}=state.current;
  const staff=state.user.role!=='customer';
  const assigned=staff&&t.assignee_id===state.user.id;
  const viewer=!staff&&t.visibility==='organization'&&state.organizations.some(o=>o.id===t.organization_id&&o.members.some(m=>m.user_id===state.user.id&&m.role==='viewer'));
  const canDecide=!staff&&!viewer&&(t.customer_id===state.user.id||state.organizations.some(o=>o.id===t.organization_id&&o.members.some(m=>m.user_id===state.user.id&&m.role==='owner')));
  const remaining=Math.max(0,(t.approved_minutes||0)-(t.actual_minutes||0));
  const progress=t.approved_minutes?Math.min(100,Math.round(t.actual_minutes/t.approved_minutes*100)):0;
  const requests=hour_requests.map(r=>`<div class="hours-request"><div class="row"><strong>+${hours(r.minutes)}</strong><span class="badge">${r.state==='approved'?'Одобрено':r.state==='rejected'?'Отклонено':'На согласовании'}</span></div><p>${esc(r.reason)}</p><small>${esc(r.author_name)} · ${date(r.created_at)}</small>${r.state==='pending'&&canDecide?`<div class="row"><button class="button primary" data-hours-approve="${r.id}">Одобрить часы</button><button class="button" data-hours-reject="${r.id}">Отклонить</button></div>`:''}</div>`).join('');
  const entries=time_entries.map(w=>`<div class="time-entry"><div class="row"><strong>${hours(w.minutes)}</strong><small>${date(w.created_at)}</small></div><p>${esc(w.note)}</p><small>${esc(w.author_name)}</small></div>`).join('');
  const logForm=assigned&&['working','waiting','done'].includes(t.status)&&t.approved_minutes?`<form class="form" id="time-entry-form"><label>Фактически потрачено, часов<input class="field" type="number" name="hours" min="0.25" step="0.25" max="${remaining/60}" required></label><label>Что сделано<textarea name="note" required minlength="3" maxlength="2000" placeholder="Кратко опишите результат работы"></textarea></label><button class="button primary" ${remaining<15?'disabled':''}>Внести время</button></form>`:'';
  const requestForm=assigned&&['working','waiting'].includes(t.status)&&t.approved_minutes&&!t.pending_hour_request?`<form class="form" id="hour-request-form"><label>Дополнительные часы<input class="field" type="number" name="hours" min="0.25" step="0.25" required></label><label>Почему нужны дополнительные часы<textarea name="reason" required minlength="3" maxlength="2000"></textarea></label><button class="button">Запросить согласование</button></form>`:'';
  const deadlineForm=staff&&(state.user.role==='admin'||state.user.is_manager)?`<form class="deadline-form" id="deadline-form"><label>Установить срок выполнения<input class="field" type="datetime-local" name="due_at" value="${t.delivery_due_at?new Date(t.delivery_due_at).toLocaleString('sv-SE').replace(' ','T').slice(0,16):''}"></label><button class="button">Сохранить срок</button></form>`:'';
  document.querySelector('.detail-grid>div:last-child').insertAdjacentHTML('afterbegin',`<section class="panel content operations-panel"><h2>Сроки SLA</h2>${slaCard(t)}${deadlineForm}</section>`);
  document.querySelector('.detail-grid>div:last-child').insertAdjacentHTML('beforeend', `<div id="git-links-container">${renderGitLinksPanel(t.id, staff)}</div>`);
  const rateRub = t.hourly_rate_rub || 3000;
  const costRub = t.cost_rub || Math.round((t.approved_minutes || 0) / 60 * rateRub);
  const actBadge = t.act_invoice ? `<span style="margin: 0 10px; color: var(--line)">|</span><a href="/api/billing/invoices/${t.act_invoice.id}/print" target="_blank" class="billing-doc-pill act" title="Открыть печатную форму акта">Акт №${esc(t.act_invoice.number)} ✓</a>` : '';
  const financeHtml = `<div class="hours-finance"><span>Ставка: <strong>${rateRub.toLocaleString('ru-RU')} ₽/ч</strong></span><span style="margin: 0 10px; color: var(--line)">|</span><span>Стоимость: <strong>${costRub.toLocaleString('ru-RU')} ₽</strong></span>${actBadge}</div>`;
  document.querySelector('.detail-grid>div:first-child').insertAdjacentHTML('beforeend',`<section class="panel content operations-panel"><h2>Фактические трудозатраты</h2><div class="hours-summary"><div><small>Согласовано</small><strong>${hours(t.approved_minutes||0)}</strong></div><div><small>Выполнено</small><strong>${hours(t.actual_minutes||0)}</strong></div><div><small>Осталось</small><strong>${hours(remaining)}</strong></div></div><div class="work-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}" aria-label="Использовано согласованных часов"><span style="width:${progress}%"></span></div>${financeHtml}${logForm}${entries?`<h3>Записи времени</h3>${entries}`:'<p class="muted">Фактическое время пока не внесено.</p>'}${requests?`<h3>Дополнительные часы</h3>${requests}`:''}${requestForm}</section><section class="panel content operations-panel"><h2>Файлы</h2>${attachments.map(a=>`<a class="attachment-link" href="/api/attachments/${a.id}"><span>${icon('paperclip',14)} ${esc(a.filename)}</span><small>${Math.ceil(a.size/1024)} КБ</small></a>`).join('')||'<p class="muted">Файлов пока нет.</p>'}${t.status!=='closed'&&!viewer?'<label class="upload-label">Прикрепить файл<input id="ticket-file" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.zip"></label>':''}</section>`);
  state.pendingOps ||= {};
  const submit=async(path,data,key)=>{try{await api(path,{method:'POST',body:JSON.stringify(data)});if(key)delete state.pendingOps[key];await refresh();await openTicket(t.id);}catch(error){showError(error);}};
  document.querySelector('#time-entry-form')?.addEventListener('submit',e=>{e.preventDefault();e.target.querySelector('button').disabled=true;const form=new FormData(e.target);const key=`time-${t.id}`;const request_id=state.pendingOps[key] ||= crypto.randomUUID();submit(`/tickets/${t.id}/time-entries`,{minutes:Math.round(Number(form.get('hours'))*60),note:form.get('note'),request_id},key);});
  document.querySelector('#hour-request-form')?.addEventListener('submit',e=>{e.preventDefault();e.target.querySelector('button').disabled=true;const form=new FormData(e.target);const key=`hours-${t.id}`;const request_id=state.pendingOps[key] ||= crypto.randomUUID();submit(`/tickets/${t.id}/hour-requests`,{minutes:Math.round(Number(form.get('hours'))*60),reason:form.get('reason'),request_id},key);});
  document.querySelectorAll('[data-hours-approve],[data-hours-reject]').forEach(button=>button.onclick=()=>submit(`/tickets/${t.id}/hour-requests/${button.dataset.hoursApprove||button.dataset.hoursReject}/decision`,{action:button.dataset.hoursApprove?'approve':'reject'}));
  document.querySelector('#ticket-file')?.addEventListener('change',async e=>{try{for(const file of e.target.files)await upload(`/tickets/${t.id}/attachments`,file);await refresh();await openTicket(t.id);}catch(error){showError(error);}});
  document.querySelector('#deadline-form')?.addEventListener('submit',async e=>{e.preventDefault();const raw=e.target.elements.due_at.value;try{await api(`/tickets/${t.id}/deadline`,{method:'PATCH',body:JSON.stringify({due_at:raw?new Date(raw).toISOString():null})});await refresh();await openTicket(t.id);}catch(error){showError(error);}});
}
function chatUnreadCount(id) { return state.notifications.filter(n => n.target === 'chat' && !n.read_at && n.chat_id === id).length; }
function chatListPanel(activeId) {
  const query = (state.chatSearch || '').trim().toLocaleLowerCase('ru-RU');
  const items = state.chats.map(c => {
    const unread = chatUnreadCount(c.id);
    const hidden = query && ![c.customer_name, c.last_message].some(value => String(value || '').toLocaleLowerCase('ru-RU').includes(query));
    return `<button class="chat-item ${c.id === activeId ? 'active' : ''}" data-chat="${c.id}" ${hidden ? 'hidden' : ''} ${c.id === activeId ? 'aria-current="true"' : ''}><span class="chat-logo" aria-hidden="true">${initials(c.customer_name)}</span><span class="chat-item-text"><strong>${esc(c.customer_name)}</strong><small>${esc(c.last_message || 'Диалог пока пуст')}</small></span><span class="chat-item-meta">${date(c.updated_at)}${unread ? `<span class="unread-count" aria-label="${unread} непрочитанных">${unread}</span>` : ''}</span></button>`;
  }).join('');
  return `<div class="inbox-list"><div class="inbox-list-head"><label class="inbox-search">${icon('search', 15)}<span class="visually-hidden">Поиск по диалогам</span><input type="search" id="chat-search" placeholder="Заказчик или сообщение" value="${esc(state.chatSearch || '')}"></label></div><div class="inbox-items">${items || '<div class="empty"><strong>Диалогов пока нет</strong>Когда заказчик напишет в общий чат, он появится здесь.</div>'}</div></div>`;
}
function bindChatList() {
  document.querySelectorAll('[data-chat]').forEach(el => el.onclick = () => openChat(Number(el.dataset.chat)));
  document.querySelector('#chat-search')?.addEventListener('input', e => { state.chatSearch = e.target.value; const query = state.chatSearch.trim().toLocaleLowerCase('ru-RU'); document.querySelectorAll('.chat-item').forEach(el => { el.hidden = Boolean(query) && !el.textContent.toLocaleLowerCase('ru-RU').includes(query); }); });
}
function renderChats() {
  const unread = state.notifications.filter(n => n.target === 'chat' && !n.read_at).length;
  shell('Общий чат', '', `<section class="panel inbox no-thread">${chatListPanel(null)}<div class="inbox-empty"><div>${icon('chat', 28)}<p><strong>Выберите диалог</strong><br>Переписка с заказчиком откроется здесь.</p></div></div></section>`, { kicker: 'Переписка без привязки к заявке', lead: `${state.chats.length} ${plural(state.chats.length, ['диалог', 'диалога', 'диалогов'])}${unread ? ` · ${unread} ${plural(unread, ['непрочитанное', 'непрочитанных', 'непрочитанных'])}` : ''}` });
  bindChatList();
}
async function openChat(id) {
  if(state.view!=='chat'||state.currentChat?.chat?.id!==id)delayedLoading('Общий чат','list');
  try{state.currentChat=await api(`/chats/${id}`);state.view='chat';state.error='';render();}
  catch(error){showError(error);}
}
function renderChatDetail() {
  const { chat, messages, linked_tickets = [], attachments = [] } = state.currentChat;
  const staff = state.user.role !== 'customer';
  const dispatcher = isDispatcher();
  let lastDay = '';
  const items = messages.map(m => {
    const day = new Date(m.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
    const separator = day !== lastDay ? `<div class="day-separator">${day}</div>` : '';
    lastDay = day;
    return `${separator}<div class="message ${m.author_id === state.user.id ? 'mine' : ''}"><small>${esc(m.author_name)} · ${new Date(m.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</small>${esc(m.body)}${attachments.filter(a => a.chat_message_id === m.id).map(a => `<a class="attachment-link" href="/api/attachments/${a.id}">${icon('paperclip', 14)}${esc(a.filename)}</a>`).join('')}</div>`;
  }).join('') || '<div class="empty">Начните разговор. Сообщение увидит наша команда.</div>';
  const otherTickets = state.tickets.filter(t => t.customer_id === chat.customer_id && !['done', 'closed'].includes(t.status) && !linked_tickets.some(l => l.id === t.id));
  const ticketButton = t => `<button class="linked-ticket" data-linked-ticket="${t.id}"><span>№${t.id} · ${esc(t.title)}</span>${t.status ? `<span class="badge ${esc(t.status)}">${statusNames[t.status]}</span>` : ''}</button>`;
  const assigneeSelect = dispatcher ? `<label class="select-inline"><span>Ведёт</span><select id="chat-assignee" aria-label="Ответственный за чат"><option value="">Без ответственного</option>${state.staff.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></label>` : '';
  const info = `<div class="inbox-info" role="complementary" aria-label="О диалоге"><div class="info-block"><span class="eyebrow">Заказчик</span><strong>${esc(chat.customer_name)}</strong></div><div class="info-block"><span class="eyebrow">Ответственный</span><strong>${esc(chat.assignee_name || 'Не назначен')}</strong></div>${linked_tickets.length ? `<div class="info-block"><span class="eyebrow">Заявки из этого чата <span>${linked_tickets.length}</span></span>${linked_tickets.map(ticketButton).join('')}</div>` : ''}${otherTickets.length ? `<div class="info-block"><span class="eyebrow">Открытые заявки <span>${otherTickets.length}</span></span>${otherTickets.slice(0, 5).map(ticketButton).join('')}</div>` : ''}</div>`;
  const thread = `<section class="inbox-thread"><div class="inbox-thread-head">${staff ? `<button class="icon-btn thread-back" id="back-chats" aria-label="К списку диалогов">←</button>` : ''}<span class="chat-logo" aria-hidden="true">${initials(staff ? chat.customer_name : 'Линия')}</span><div><strong>${esc(staff ? chat.customer_name : 'Команда поддержки')}</strong><small>${messages.length} ${plural(messages.length, ['сообщение', 'сообщения', 'сообщений'])}</small></div>${assigneeSelect}</div><div class="messages" id="chat-messages">${items}</div><form class="composer" id="chat-message-form"><label class="visually-hidden" for="chat-body">Сообщение</label><textarea id="chat-body" data-draft="chat-${chat.id}" name="body" required maxlength="10000" placeholder="${staff ? `Ответить: ${esc(chat.customer_name)}` : 'Напишите сообщение команде…'}"></textarea><div class="composer-files" id="chat-files"></div><div class="composer-bar"><label class="upload-label">${icon('paperclip', 15)}Файлы<input name="files" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.zip"></label><span class="composer-hint">Ctrl + Enter — отправить</span><button class="button primary">Отправить</button></div></form></section>`;
  shell(staff ? 'Общий чат' : 'Чат с командой', '', `<section class="panel inbox has-thread ${staff ? '' : 'customer'}">${staff ? chatListPanel(chat.id) : ''}${thread}${info}</section>`, { kicker: staff ? 'Переписка без привязки к заявке' : 'Личный кабинет' });
  if (staff) bindChatList();
  document.querySelectorAll('[data-linked-ticket]').forEach(el => el.onclick = () => openTicket(Number(el.dataset.linkedTicket)));
  if (staff) {
    document.querySelectorAll('#chat-messages .message').forEach((el, index) => {
      const msg = messages[index];
      if (msg.author_id === chat.customer_id && !linked_tickets.some(t => t.source_message_id === msg.id)) {
        el.insertAdjacentHTML('beforeend', `<button class="chat-to-ticket" data-message="${msg.id}">${icon('plus', 13)}Создать заявку из сообщения</button>`);
      }
    });
    document.querySelector('#chat-message-form').insertAdjacentHTML('afterend', '<form class="form chat-ticket-form" id="chat-ticket-form" hidden><strong>Новая заявка из чата</strong><label>Тема<input class="field" name="title" required minlength="3" maxlength="140"></label><input type="hidden" name="message_id"><div class="row"><button class="button primary">Создать заявку</button><button class="button" type="button" id="cancel-chat-ticket">Отмена</button></div></form>');
    document.querySelectorAll('[data-message]').forEach(el => el.onclick = () => { const msg = messages.find(m => m.id === Number(el.dataset.message)); const form = document.querySelector('#chat-ticket-form'); form.hidden = false; form.elements.message_id.value = msg.id; form.elements.title.value = msg.body.slice(0, 100); form.elements.title.focus(); });
    document.querySelector('#cancel-chat-ticket').onclick = () => document.querySelector('#chat-ticket-form').hidden = true;
    document.querySelector('#chat-ticket-form').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button.primary'); button.disabled = true; try { const data = Object.fromEntries(new FormData(e.target)); const ticket = await api(`/chats/${chat.id}/tickets`, { method: 'POST', body: JSON.stringify({ title: data.title, message_id: Number(data.message_id) }) }); await refresh(); await openTicket(ticket.id); } catch (error) { showError(error); } };
  }
  document.querySelector('#back-chats')?.addEventListener('click', () => setView('chats'));
  if (dispatcher) { document.querySelector('#chat-assignee').value = chat.assignee_id || ''; document.querySelector('#chat-assignee').onchange = async e => { try { await api(`/chats/${chat.id}/assignee`, { method: 'PATCH', body: JSON.stringify({ assignee_id: e.target.value ? Number(e.target.value) : null }) }); await refresh(); await openChat(chat.id); } catch (error) { showError(error); } }; }
  bindCtrlEnter('#chat-message-form');
  document.querySelector('#chat-message-form').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button.primary'); button.disabled = true; const requestId = e.target.dataset.requestId || (e.target.dataset.requestId = crypto.randomUUID()); try { const files = [...e.target.elements.files.files]; const message = await api(`/chats/${chat.id}/messages`, { method: 'POST', body: JSON.stringify({ body: new FormData(e.target).get('body'), request_id: requestId }) }); clearDraft(`chat-${chat.id}`); for (const file of files) await upload(`/chats/${chat.id}/attachments`, file, { message_id: message.id }); state.justSent = true; await refresh(); await openChat(chat.id); } catch (error) { state.error = error.message; button.disabled = false; const alert = document.querySelector('.notice'); if (alert) alert.textContent = state.error; else document.querySelector('main .top').insertAdjacentHTML('afterend', notice()); } };
  document.querySelector('#chat-messages').scrollTop = document.querySelector('#chat-messages').scrollHeight;
  popLastMessage(document.querySelector('#chat-messages'));
  bindChatFiles();
}
function renderTeam() {
  shell('Команда','',`<div class="detail-grid"><section class="panel content"><h2>Сотрудники</h2>${state.staff.map(x=>`<div class="team-person">${avatar(x)}<span><strong>${esc(x.name)}</strong><small>${esc(x.job_title||x.email)}</small></span><span class="badge">${x.role==='admin'?'Администратор':'Сотрудник'}</span></div>`).join('')}</section><section class="panel content"><h2>Добавить сотрудника</h2><form class="form" id="staff-form"><label>Имя<input class="field" name="name" required minlength="2"></label><label>Email<input class="field" name="email" type="email" required></label><label>Временный пароль<input class="field" name="password" type="password" required minlength="8"></label><button class="button primary">Добавить</button></form></section></div>`);
  document.querySelector('#staff-form button').insertAdjacentHTML('beforebegin','<label>Роль<select class="field" name="staff_role"><option value="employee">Сотрудник · только свои заявки</option><option value="manager">Менеджер · вся очередь и назначение</option></select></label>');
  document.querySelectorAll('.team-person .badge').forEach((badge,index)=>{
    if(state.staff[index]?.is_manager) badge.textContent='Менеджер';
  });
  document.querySelector('#staff-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{await api('/staff',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});state.error='';await refresh();}catch(error){showError(error);}};
}
function renderProfile(){
  const p=state.profile;
  if(!p)return;
  if(state.user.role==='customer'){
    shell('Мой профиль','',`<div class="profile-layout"><section class="panel content profile-main"><div class="profile-heading customer-profile-heading">${avatar(p,'large')}<div><span class="eyebrow">КАБИНЕТ ЗАКАЗЧИКА</span><h2>${esc(p.name)}</h2><p>${esc(p.company_name||'Добавьте название компании')}</p><small>${esc(p.email)}</small></div></div><form class="form" id="customer-profile-form"><label>Ваше имя<input class="field" name="name" required minlength="2" maxlength="100" autocomplete="name" value="${esc(p.name)}"></label><label>Компания или команда<input class="field" name="company_name" maxlength="150" autocomplete="organization" placeholder="Например, Студия Север" value="${esc(p.company_name)}"></label><label>Контактный телефон<input class="field" name="phone" type="tel" maxlength="40" autocomplete="tel" placeholder="+7 999 123-45-67" value="${esc(p.phone)}"></label><p class="profile-hint">Email для входа: <strong>${esc(p.email)}</strong></p><div class="profile-actions"><button class="button primary">Сохранить изменения</button><span id="profile-saved" role="status"></span></div></form></section><div class="profile-note"><span class="eyebrow">НА СВЯЗИ С КОМАНДОЙ</span><h2>Ваши обращения в одном месте</h2><p>Имя и название компании помогут команде узнавать ваши задачи в заявках и общем чате. Контактный телефон доступен только вам в этом кабинете.</p><div class="profile-facts"><div><strong>${state.tickets.length}</strong><span>заявок</span></div><div><strong>${state.chats.length}</strong><span>общих чатов</span></div></div></div></div>`);
    if(state.organizations[0]){document.querySelector('.customer-profile-heading p').textContent=state.organizations[0].name;document.querySelector('#customer-profile-form [name="company_name"]').parentElement.innerHTML=`Компания <strong>${esc(state.organizations[0].name)}</strong><input type="hidden" name="company_name" value="${esc(p.company_name)}"><small>Состав компании управляется в разделе «Моя компания».</small>`;}
    mountPushCard();
    document.querySelector('#customer-profile-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{state.profile=await api('/customer-profile/me',{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});state.user.name=state.profile.name;state.error='';renderProfile();document.querySelector('#profile-saved').textContent='Изменения сохранены';}catch(error){showError(error);}};
    return;
  }
  shell('Мой профиль','',`<div class="profile-layout"><section class="panel content profile-main"><div class="profile-heading"><div>${avatar(p,'large')}<label class="avatar-upload" for="avatar-file">Загрузить фото</label><input id="avatar-file" type="file" accept="image/png,image/jpeg,image/webp" hidden>${p.avatar_url?'<button class="avatar-remove" id="avatar-remove">Удалить фото</button>':''}</div><div><span class="eyebrow">ПРОФИЛЬ СОТРУДНИКА</span><h2>${esc(p.name)}</h2><p>${esc(p.job_title||'Укажите должность')}</p><small>${esc(p.email)}</small></div></div><form class="form" id="profile-form"><label>ФИО<input class="field" name="name" required minlength="2" maxlength="100" autocomplete="name" value="${esc(p.name)}"></label><label>Должность<input class="field" name="job_title" maxlength="100" placeholder="Например, ведущий разработчик" value="${esc(p.job_title)}"></label><label>О себе<textarea name="bio" maxlength="1000" placeholder="Чем вы помогаете заказчикам, ваш опыт и специализация">${esc(p.bio)}</textarea></label><div class="profile-actions"><button class="button primary">Сохранить изменения</button><span id="profile-saved" role="status"></span></div></form></section><aside class="profile-note"><span class="eyebrow">КАК ЭТО РАБОТАЕТ</span><h2>Знакомое лицо в каждой заявке</h2><p>Заказчик увидит ваше имя, должность, описание и фотографию в заявках, за которые вы отвечаете. Это помогает понимать, с кем идёт работа.</p><p>Подойдёт PNG, JPEG или WebP до 2 МБ. Изображение автоматически подстроится под кабинет.</p></aside></div>`);
  mountPushCard();
  document.querySelector('#profile-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{state.profile=await api('/profile/me',{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});state.user.name=state.profile.name;state.error='';renderProfile();document.querySelector('#profile-saved').textContent='Изменения сохранены';}catch(error){showError(error);}};
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
function renderOrganizations(){
  const dispatcher=state.user.role==='admin'||state.user.is_manager;
  const cards=state.organizations.map(org=>`<section class="panel content organization-card"><div class="row"><h2>${esc(org.name)}</h2><span class="badge">${org.members.length} участников</span></div><div class="org-members">${org.members.map(m=>`<div class="team-person org-person"><span><strong>${esc(m.name)}</strong><small>${esc(m.email)}</small></span>${dispatcher?`<span class="org-person-actions"><select class="field" data-member-role="${m.user_id}" data-org="${org.id}" aria-label="Роль ${esc(m.name)}"><option value="owner" ${m.role==='owner'?'selected':''}>Владелец</option><option value="member" ${m.role==='member'?'selected':''}>Участник</option><option value="viewer" ${m.role==='viewer'?'selected':''}>Наблюдатель</option></select><button class="button" data-remove-member="${m.user_id}" data-org="${org.id}" aria-label="Удалить ${esc(m.name)} из компании">Убрать</button></span>`:`<span class="badge">${m.role==='owner'?'Владелец':m.role==='viewer'?'Наблюдатель':'Участник'}</span>`}</div>`).join('')}</div>${dispatcher?`<form class="form org-member-form" data-org="${org.id}"><label>Email зарегистрированного заказчика<input class="field" name="email" type="email" required></label><label>Роль<select class="field" name="role"><option value="member">Участник</option><option value="viewer">Наблюдатель</option><option value="owner">Владелец</option></select></label><button class="button">Добавить в компанию</button></form>`:''}</section>`).join('');
  const create=dispatcher?`<section class="panel content"><h2>Создать компанию заказчика</h2><p class="muted">Владелец и участники должны иметь отдельные зарегистрированные кабинеты.</p><form class="form" id="org-form"><label>Название компании<input class="field" name="name" minlength="2" maxlength="150" required></label><label>Владелец<select class="field" name="owner_id" required><option value="">Выберите заказчика</option>${state.customers.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.email)}</option>`).join('')}</select></label><button class="button primary">Создать компанию</button></form></section>`:'';
  shell(dispatcher?'Компании заказчиков':'Моя компания','',`<p class="muted">Заявки компании видны её участникам, если при создании выбрана видимость «Вся компания». Личные заявки видит только их автор.</p><div class="org-grid">${cards||`<div class="panel content empty">${dispatcher?'Компаний пока нет. Создайте первую справа.':'Вы пока не состоите в компании. Менеджер добавит вас после регистрации.'}</div>`}${create}</div>`);
  document.querySelector('#org-form')?.addEventListener('submit',async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));try{await api('/organizations',{method:'POST',body:JSON.stringify({name:data.name,owner_id:Number(data.owner_id)})});await refresh();setView('organizations');}catch(error){showError(error);}});
  document.querySelectorAll('.org-member-form').forEach(form=>form.onsubmit=async e=>{e.preventDefault();try{await api(`/organizations/${form.dataset.org}/members`,{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});await refresh();setView('organizations');}catch(error){showError(error);}});
  document.querySelectorAll('[data-member-role]').forEach(select=>select.onchange=async()=>{try{await api(`/organizations/${select.dataset.org}/members/${select.dataset.memberRole}`,{method:'PATCH',body:JSON.stringify({role:select.value})});await refresh();setView('organizations');}catch(error){showError(error);}});
  document.querySelectorAll('[data-remove-member]').forEach(button=>button.onclick=async()=>{if(!confirm('Убрать участника из компании? Доступ к общим заявкам прекратится.'))return;try{await api(`/organizations/${button.dataset.org}/members/${button.dataset.removeMember}`,{method:'DELETE'});await refresh();setView('organizations');}catch(error){showError(error);}});
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
  const serviceRows = services.map(([key, count], index) => `<span><b style="background:${colors[index % colors.length]}"></b>${serviceNames[key] || esc(key)}</span><strong>${count}</strong>`).join('');
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
  setView('billing');
  location.hash = '#billing';
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
  const staff = state.user.role !== 'customer';
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
    kpis = `<div class="billing-kpi-grid">${kpi('Поступило за месяц', rub(totalPaid), 'Оплаченные счета клиентов', 'positive')}${kpi('Готово к актированию', hours(totalUnbilled), 'Выполненные задачи без акта')}${kpi('Ожидают оплаты', rub(issuedDocs.reduce((acc, d) => acc + (d.total_rub || 0), 0)), `${issuedDocs.length} ${plural(issuedDocs.length, ['счёт', 'счёта', 'счетов'])} · ${totalClients} ${plural(totalClients, ['клиент', 'клиента', 'клиентов'])}, ${withDeposit} с депозитом`)}${kpi('Баланс в минусе', `${withDebt} ${plural(withDebt, ['клиент', 'клиента', 'клиентов'])}`, withDebt ? `Суммарно −${hours(Math.abs(debtMinutes))}` : 'Все балансы в норме', withDebt ? 'danger' : '')}</div>`;
  } else {
    const balMins = b.balance_minutes || 0;
    const balHours = b.balance_hours ?? (balMins / 60.0);
    const balRub = b.balance_rub ?? b.balance_rub_equiv ?? Math.round(balHours * (b.hourly_rate_rub || 3000));
    const activeMins = b.in_progress_minutes ?? b.active_billable_minutes ?? 0;
    const unbilledMins = b.unbilled_minutes ?? b.unbilled_done_minutes ?? 0;
    kpis = `<div class="billing-kpi-grid">${kpi('Баланс депозита', `${balHours.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч`, `Эквивалент: ${rub(balRub)}`, balMins > 0 ? 'positive' : balMins < 0 ? 'danger' : '')}${kpi('Тарифная ставка', `${(b.hourly_rate_rub || 3000).toLocaleString('ru-RU')} ₽/ч`, 'Фиксированная ставка по договору')}${kpi('Часы в работе', hours(activeMins), 'Согласованные активные заявки')}${kpi('Готово к актированию', hours(unbilledMins), 'Выполненные задачи без акта')}</div>`;
  }

  const actions = staff
    ? `<button class="button" id="btn-create-deposit">Пополнить баланс</button><button class="button" id="btn-create-invoice">Выставить счёт</button><button class="button primary" id="btn-create-act">${icon('plus', 16)}Сформировать акт</button>`
    : `<button class="button primary" id="btn-customer-deposit">${icon('plus', 16)}Купить пакет часов</button>`;

  const activeTab = state.billingTab || 'docs';
  const tabButton = (key, label, count) => `<button class="billing-tab ${activeTab === key ? 'active' : ''}" data-tab="${key}" role="tab" aria-selected="${activeTab === key}">${label}${count !== undefined ? ` <i>${count}</i>` : ''}</button>`;
  const tabs = `<div class="billing-tabs" role="tablist" aria-label="Разделы биллинга">${tabButton('docs', 'Счета и акты', allDocs.length)}${staff ? tabButton('clients', 'Клиенты и тарифы', clients.length) : ''}${tabButton('tx', 'История операций')}</div>`;

  let content = '';
  if (activeTab === 'docs') {
    let docs = allDocs;
    const filter = state.billingFilter || 'all';
    if (filter === 'invoice') docs = docs.filter(d => d.doc_type === 'invoice');
    else if (filter === 'act') docs = docs.filter(d => d.doc_type === 'act');
    else if (filter === 'issued') docs = docs.filter(d => d.status === 'issued');
    else if (filter === 'paid') docs = docs.filter(d => d.status === 'paid');
    const pill = (key, label) => `<button class="billing-filter-pill ${filter === key ? 'active' : ''}" data-filter="${key}" aria-pressed="${filter === key}">${label}</button>`;
    const filterBar = `<div class="billing-filter-bar">${pill('all', 'Все документы')}${pill('invoice', 'Счета')}${pill('act', 'Акты')}${pill('issued', 'Ожидают оплаты')}${pill('paid', 'Оплаченные')}</div>`;
    const statusPill = (doc) => {
      if (doc.status === 'paid') return `<span class="billing-status paid">${doc.doc_type === 'act' ? 'Подписан' : 'Оплачен'}</span>`;
      if (doc.status === 'issued') return `<span class="billing-status issued">${doc.doc_type === 'act' ? 'На подписании' : 'Ожидает оплаты'}</span>`;
      return '<span class="billing-status cancelled">Аннулирован</span>';
    };
    const docRows = docs.map(d => {
      const typeBadge = d.doc_type === 'act' ? '<span class="billing-doc-pill act">Акт</span>' : '<span class="billing-doc-pill invoice">Счёт</span>';
      const clientName = d.organization_name || d.customer_name || d.client_name || 'Клиент';
      const period = d.period_start && d.period_end ? `${formatRuDate(d.period_start)} – ${formatRuDate(d.period_end)}` : '';
      let actionButtons = `<a href="/api/billing/invoices/${d.id}/print" target="_blank" rel="noopener" class="button small" aria-label="Печатная форма ${esc(d.number)}" title="Печатная форма / PDF">${icon('print', 15)}</a>`;
      if (staff && d.status === 'issued') actionButtons = `<button class="button small" data-mark-paid="${d.id}">Оплачен</button>${actionButtons}<button class="button small danger" data-mark-cancel="${d.id}" aria-label="Аннулировать ${esc(d.number)}" title="Аннулировать документ">✕</button>`;
      if (!staff && d.status === 'issued' && d.doc_type === 'invoice') actionButtons = `<button class="button small primary" data-customer-pay="${d.id}">Оплатить онлайн (демо)</button>${actionButtons}`;
      return `<tr><td><div class="doc-cell">${typeBadge}<div><strong>№ ${esc(d.number)}</strong><small>${period ? 'за ' + period : 'от ' + formatRuDate(d.created_at)}</small></div></div></td>${staff ? `<td><strong>${esc(clientName)}</strong></td>` : ''}<td class="num">${hours(d.total_minutes)}</td><td class="num"><strong>${rub(d.total_rub)}</strong></td><td>${statusPill(d)}</td><td><div class="billing-actions">${actionButtons}</div></td></tr>`;
    }).join('');
    content = `${filterBar}${docs.length ? `<div class="table-scroll"><table class="billing-table"><thead><tr><th>Документ</th>${staff ? '<th>Клиент</th>' : ''}<th class="num">Объём</th><th class="num">Сумма</th><th>Статус</th><th><span class="visually-hidden">Действия</span></th></tr></thead><tbody>${docRows}</tbody></table></div>` : '<div class="empty"><strong>Документов нет</strong>По выбранному фильтру ничего не найдено.</div>'}`;
  } else if (activeTab === 'clients' && staff) {
    const clientRows = clients.map(c => {
      const balance = c.balance_minutes || 0;
      return `<tr><td><strong>${esc(c.name)}</strong><div class="billing-client-meta">${c.client_type === 'org' || c.client_type === 'organization' ? 'Организация' : 'Физлицо / прямой клиент'}</div></td><td><div>${c.inn ? `ИНН: ${esc(c.inn)}` : '<span class="muted">ИНН не указан</span>'}</div>${c.legal_address ? `<div class="billing-client-meta">${esc(c.legal_address)}</div>` : ''}</td><td class="num"><strong>${(c.hourly_rate_rub || 3000).toLocaleString('ru-RU')} ₽/ч</strong></td><td class="num"><strong style="color:${balance < 0 ? 'var(--late)' : 'var(--ink)'}">${(c.balance_hours ?? (balance / 60)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч</strong><div class="billing-client-meta">${rub(c.balance_rub ?? c.balance_rub_equiv ?? Math.round((balance / 60) * (c.hourly_rate_rub || 3000)))}</div></td><td class="num"><strong>${hours(c.unbilled_minutes ?? c.unbilled_done_minutes ?? 0)}</strong></td><td><div class="billing-actions"><button class="button small" data-edit-client="${c.client_type}:${c.client_id}">Реквизиты</button><button class="button small" data-deposit-client="${c.client_type}:${c.client_id}">+ Часы</button><button class="button small primary" data-act-client="${c.client_type}:${c.client_id}">+ Акт</button></div></td></tr>`;
    }).join('');
    content = `<div class="table-scroll"><table class="billing-table"><thead><tr><th>Клиент</th><th>Реквизиты</th><th class="num">Ставка</th><th class="num">Депозит</th><th class="num">К актированию</th><th><span class="visually-hidden">Управление</span></th></tr></thead><tbody>${clientRows || '<tr><td colspan="6"><div class="empty"><strong>Клиентов пока нет</strong></div></td></tr>'}</tbody></table></div>`;
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
    side = `<div class="context-stack"><section class="panel content"><div class="card-head"><h2>Балансы клиентов</h2><span class="muted">часы депозита</span></div>${balanceRows || '<p class="muted">Клиентов пока нет.</p>'}</section>${totalUnbilled > 0 ? `<section class="focus-panel"><span class="focus-overline">Пора закрыть период</span><h2>${hours(totalUnbilled)} выполнено без акта</h2><p>Сформируйте акт, чтобы списать часы с депозита клиента.</p><div class="focus-actions"><button class="button on-dark" id="btn-close-period">Сформировать акт</button></div></section>` : ''}</div>`;
  }

  const month = new Date().toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' });
  shell('Биллинг и счета', actions, `${kpis}<div class="${staff ? 'split billing-split' : ''}"><section class="panel">${tabs}${content}</section>${side}</div><div id="billing-modal-slot"></div>`, { kicker: month.charAt(0).toUpperCase() + month.slice(1) });

  attachBillingHandlers();
}

function attachBillingHandlers() {
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

  document.querySelectorAll('[data-mark-paid]').forEach(btn => {
    btn.onclick = async () => {
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

  document.querySelectorAll('[data-customer-pay]').forEach(btn => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.customerPay);
      if (!confirm('Подтвердить оплату счёта онлайн (демо)? Депозит часов будет сразу зачислен на ваш баланс.')) return;
      try {
        await api(`/billing/invoices/${id}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status: 'paid' })
        });
        toast('Оплата подтверждена — часы зачислены на баланс');
        await openBilling();
      } catch(err) {
        showError(err);
      }
    };
  });

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
          <div style="font-weight:700; margin-top:8px; font-size:13px">Завершённые заявки для включения в акт:</div>
          <div id="act-tickets-box" class="billing-ticket-list">
            <div class="muted">Выберите клиента для отображения не выставленных заявок</div>
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

  const modal = slot.querySelector('#billing-modal');
  slot.querySelector('#modal-close').onclick = () => { slot.innerHTML = ''; };
  modal.onclick = (e) => { if (e.target === modal) slot.innerHTML = ''; };

  const select = slot.querySelector('#act-client-select');
  const ticketsBox = slot.querySelector('#act-tickets-box');
  const totalsBar = slot.querySelector('#act-totals-bar');
  const submitBtn = slot.querySelector('#act-submit-btn');

  let currentTickets = [];

  async function loadTickets(key) {
    if (!key) {
      ticketsBox.innerHTML = '<div class="muted">Выберите клиента</div>';
      submitBtn.disabled = true;
      return;
    }
    const [cType, cId] = key.split(':');
    ticketsBox.innerHTML = skeletonLines(3);
    try {
      currentTickets = await api(`/billing/unbilled-tickets?client_type=${cType}&client_id=${cId}`);
      if (!currentTickets.length) {
        ticketsBox.innerHTML = '<div class="muted">У этого клиента нет завершённых не выставленных в акт заявок.</div>';
        submitBtn.disabled = true;
        recalc();
        return;
      }
      ticketsBox.innerHTML = `
        <div style="padding-bottom:6px; margin-bottom:6px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between">
          <label style="font-weight:700; cursor:pointer"><input type="checkbox" id="act-select-all" checked> Выбрать все</label>
          <small class="muted">${currentTickets.length} заявок</small>
        </div>
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
        slot.querySelectorAll('.act-ticket-cb').forEach(cb => { cb.checked = e.target.checked; });
        recalc();
      };
      slot.querySelectorAll('.act-ticket-cb').forEach(cb => {
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
    const checked = Array.from(slot.querySelectorAll('.act-ticket-cb:checked'));
    let totalMins = 0;
    checked.forEach(cb => { totalMins += Number(cb.dataset.mins || 0); });
    const rub = Math.round(totalMins / 60 * rate);
    totalsBar.innerHTML = `Выбрано заявок: <strong>${checked.length}</strong> | Трудозатраты: <strong>${hours(totalMins)}</strong> | Сумма к списанию: <strong>${rub.toLocaleString('ru-RU')} ₽</strong>`;
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
          ticket_ids
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
                  ${esc(c.name)} (ставка ${c.hourly_rate_rub} ₽/ч, баланс ${c.balance_hours} ч)
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

  const modal = slot.querySelector('#billing-modal');
  slot.querySelector('#modal-close').onclick = () => { slot.innerHTML = ''; };
  modal.onclick = (e) => { if (e.target === modal) slot.innerHTML = ''; };

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
                  ${esc(c.name)} (текущий баланс: ${c.balance_hours} ч)
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

  const modal = slot.querySelector('#billing-modal');
  slot.querySelector('#modal-close').onclick = () => { slot.innerHTML = ''; };
  modal.onclick = (e) => { if (e.target === modal) slot.innerHTML = ''; };

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

  const modal = slot.querySelector('#billing-modal');
  slot.querySelector('#modal-close').onclick = () => { slot.innerHTML = ''; };
  modal.onclick = (e) => { if (e.target === modal) slot.innerHTML = ''; };

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
            Выберите желаемый объём часов. Система сформирует официальный счёт для безналичной оплаты или мгновенного онлайн-платежа.
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

  const modal = slot.querySelector('#billing-modal');
  slot.querySelector('#modal-close').onclick = () => { slot.innerHTML = ''; };
  modal.onclick = (e) => { if (e.target === modal) slot.innerHTML = ''; };

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
  if(!state.user)return;
  const match=location.hash.match(/^#(ticket|chat)\/(\d+)$/);
  if(match)return match[1]==='ticket'?openTicket(Number(match[2])):openChat(Number(match[2]));
  if(location.hash==='#messengers')return openMessengers();
  if(location.hash==='#analytics')return openAnalytics();
  if(location.hash==='#kb')return openKb();
  if(location.hash==='#webhooks')return openWebhooks();
  if(location.hash==='#billing')return openBilling();
}
function render() {if(!state.user)return renderAuth();if(state.view==='organizations')return renderOrganizations();if(state.view==='profile')return renderProfile();if(state.view==='messengers')return renderMessengers();if(state.view==='queue')return renderQueue();if(state.view==='new')return renderNew();if(state.view==='detail'&&state.current)return renderDetail();if(state.view==='team')return renderTeam();if(state.view==='notifications')return renderNotifications();if(state.view==='chats')return renderChats();if(state.view==='chat'&&state.currentChat)return renderChatDetail();if(state.view==='analytics')return renderAnalytics();if(state.view==='kb')return renderKb();if(state.view==='webhooks')return renderWebhooks();if(state.view==='billing')return renderBilling();renderTickets();}
async function start(){
  const params=new URLSearchParams(location.search);
  if(params.has('register'))state.authMode='register';
  if(params.has('register')||params.has('login'))history.replaceState(null,'',location.pathname+location.hash);
  if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
  try{
    state.user=await api('/me');
    state.view=state.user.role==='customer'?'tickets':'queue';
    initRealtime();
    await refresh();
    await openHash();
    maybeStartTour();
    syncPush();
  }catch{
    state.user=null;
    renderAuth();
  }
}
window.addEventListener('hashchange',()=>openHash());
themeMedia.addEventListener?.('change',syncThemeUi);
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
  if(e.key==='Escape'){document.body.classList.remove('nav-open');const slot=document.querySelector('#billing-modal-slot');if(slot?.firstElementChild)slot.innerHTML='';}
});
start();
setInterval(()=>loadNotifications().catch(()=>{}),15000);
setInterval(async()=>{
  if(state.view!=='chat'||!state.currentChat||document.querySelector('#chat-message-form textarea')?.value) return;
  try{
    const fresh=await api(`/chats/${state.currentChat.chat.id}`);
    if(fresh.messages.length!==state.currentChat.messages.length||fresh.chat.assignee_id!==state.currentChat.chat.assignee_id){state.currentChat=fresh;renderChatDetail();}
  }catch{}
},15000);

