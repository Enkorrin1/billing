const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadTasks(overrides = {}) {
  const notices = [];
  const state = { user: { id: 8 }, view: 'tasks', teamWorkspace: { tasks: [] } };
  const context = vm.createContext({
    state,
    document: { addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] },
    toast: (message, kind) => notices.push({ message, kind }),
    beginNavigation: () => 1,
    isNavigationCurrent: () => true,
    ...overrides,
  });
  const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'tasks.js'), 'utf8');
  // Expose existing module internals only in the isolated test VM.
  vm.runInContext(source.replace('return {render,renderDetail,', 'return {rememberSettings,restoreSettingsDraft,checklistCompletionStatus,action,render,renderDetail,') + '\nglobalThis.tasks = TasksUI;', context);
  return { tasks: context.tasks, state, notices };
}

function form(values, checked = []) {
  const fields = Object.fromEntries(Object.entries(values).map(([name, value]) => [name, { name, value }]));
  const participants = ['8', '9', '10'].map(value => ({ name: 'participants', value, checked: checked.includes(value) }));
  return { fields, participants, dataset: {}, elements: { namedItem: name => fields[name] }, querySelectorAll: selector => selector.endsWith(':checked') ? participants.filter(input => input.checked) : participants };
}

test('task settings survive checklist/refresh rendering without replacing fresh untouched fields', () => {
  const { tasks } = loadTasks();
  const old = form({ priority: 'high', status: 'working' }, ['8', '9']);
  tasks.rememberSettings(old, old.fields.priority, 7);
  tasks.rememberSettings(old, { name: 'participants' }, 7);
  const refreshed = form({ priority: 'normal', status: 'review' }, ['10']);
  tasks.restoreSettingsDraft(refreshed, 7);
  assert.equal(refreshed.fields.priority.value, 'high');
  assert.equal(refreshed.fields.status.value, 'review');
  assert.deepEqual(refreshed.participants.filter(input => input.checked).map(input => input.value), ['8', '9']);
  assert.equal(refreshed.dataset.dirty, 'true');
  const otherTask = form({ priority: 'normal' });
  tasks.restoreSettingsDraft(otherTask, 8);
  assert.equal(otherTask.fields.priority.value, 'normal');
});

test('last checklist item completes directly without reviewer, otherwise submits for review', () => {
  const { tasks } = loadTasks();
  const task = { can_edit: true, status: 'working', reviewer_id: null, checklist: [{ checked: true }] };
  assert.equal(tasks.checklistCompletionStatus(task), 'done');
  assert.equal(tasks.checklistCompletionStatus({ ...task, reviewer_id: 9 }), 'review');
  for (const override of [{ blocked_reason: 'waiting' }, { can_edit: false }, { status: 'done' }, { checklist: [] }, { checklist: [{ checked: false }] }]) {
    assert.equal(tasks.checklistCompletionStatus({ ...task, ...override }), null);
  }
});

test('failed task action returns false and reports only the actual error', async () => {
  const { tasks, notices } = loadTasks();
  assert.equal(await tasks.action(async () => { throw new Error('Conflict'); }), false);
  assert.deepEqual(notices, [{ message: 'Conflict', kind: 'error' }]);
});

test('late task response cannot overwrite navigation after user leaves', async () => {
  let resolve;
  let current = true;
  const { tasks, state } = loadTasks({ api: () => new Promise(done => { resolve = done; }), isNavigationCurrent: () => current });
  const pending = tasks.open(7);
  state.view = 'profile';
  current = false;
  resolve({ id: 7 });
  await pending;
  assert.equal(state.view, 'profile');
  assert.equal(state.currentTaskId, undefined);
});
