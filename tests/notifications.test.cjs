const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const source = readFileSync(require('node:path').join(__dirname, '../web/main.js'), 'utf8');
const start = source.indexOf('function notificationGroups(');
const end = source.indexOf('\nfunction renderNotifications()', start);
const group = runInNewContext(`${source.slice(start, end)}; notificationGroups`);

test('groups repeated events by object, keeps source IDs separate and preserves unread counts', () => {
  const events = [
    {id:1,target:'ticket',ticket_id:7,kind:'assignment',text:'Assigned',created_at:'2026-10-13T10:00:00',read_at:null},
    {id:2,target:'ticket',ticket_id:7,kind:'message',text:'Message',created_at:'2026-10-14T10:00:00',read_at:'read'},
    {id:1,target:'chat',chat_id:7,kind:'message',text:'Chat',created_at:'2026-10-14T11:00:00',read_at:null},
  ];
  const taskEvents = [{id:1,entity:'tasks',entity_id:7,title:'Task title',event_kind:'mention',created_at:'2026-10-14T12:00:00',read_at:null}];
  const result = group(events, taskEvents, [{id:7,title:'Ticket title',status:'working'}], [{id:7,customer_name:'Company'}]);
  assert.equal(result.length, 3);
  assert.equal(result[0].key, 'task-7');
  assert.equal(result[0].events[0].label, 'Вас упомянули');
  const ticket = result.find(g=>g.target==='ticket');
  assert.equal(ticket.title, 'Ticket title');
  assert.equal(ticket.events.length, 2);
  assert.equal(ticket.events[0].id, 2);
  assert.equal(ticket.unread, 1);
  assert.equal(result.find(g=>g.target==='chat').title, 'Company');
  assert.equal(events[0].label, undefined, 'input objects are not mutated');
});

test('empty data, missing records and future event kinds have safe fallbacks', () => {
  assert.equal(group([], [], [], []).length, 0);
  const result = group([{id:1,target:'ticket',ticket_id:99,kind:'future_event',text:'Details',created_at:'2026-10-14',read_at:'read'}], [], [], []);
  assert.equal(result[0].title, 'Заявка №99');
  assert.equal(result[0].events[0].label, 'Обновление');
  assert.equal(result[0].unread, 0);
});
