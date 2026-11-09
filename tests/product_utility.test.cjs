const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/main.js'), 'utf8');
function fn(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists`);
  const end = source.indexOf('\n}', start) + 2;
  return source.slice(start, end);
}
test('global search finds authorized tasks by title and id, customer sees none', () => {
  for (const role of ['employee', 'customer']) for (const query of ['Проверить интеграцию', '71', '#71', '№71']) {
    const input = {value:query, addEventListener(){}, setAttribute(){}, focus(){}};
    const list = {innerHTML:'', querySelector(){}, addEventListener(){}};
    const backdrop = {querySelector: s => s === '#palette-input' ? input : list, addEventListener(){}};
    let inserted = false;
    const ctx = vm.createContext({state:{user:{role},tickets:[],chats:[],teamWorkspace:{tasks:[{id:71,title:'Проверить интеграцию',status:'new'}]}},
      document:{querySelector:()=>inserted?backdrop:null,querySelectorAll:()=>[],body:{insertAdjacentHTML(){inserted=true}}},
      icon:()=>'',esc:String,effectiveTheme:()=> 'light',statusNames:{},TasksUI:{},setTimeout});
    vm.runInContext(fn('openPalette')+';openPalette()',ctx);
    assert.equal(list.innerHTML.includes('№71'), role === 'employee');
  }
});
test('PM manual price is distinct from computed price, zero is an explicit price', () => {
  const ctx = vm.createContext({});
  vm.runInContext(fn('pmOfferAmounts')+';globalThis.calc=pmOfferAmounts',ctx);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.calc(5,0,3000,'20000'))), {calculated:15000,final:20000,difference:5000,manual:true});
  assert.equal(ctx.calc(5,0,3000,'').manual,false);
  assert.equal(ctx.calc(5,0,3000,'0').final,0);
});
