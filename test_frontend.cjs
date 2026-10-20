const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function page(state) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML:'', textContent:'', value:'', dataset:{}, addEventListener(){}, disabled:false});
    return elements.get(id);
  };
  const context = vm.createContext({document:{getElementById:element,querySelectorAll:()=>[]},window:{},Date,Map,Set,URL,AbortSignal,setInterval(){},setTimeout(){},clearTimeout(){},fetch:async()=>({ok:true,json:async()=>state})});
  vm.runInContext(script.replace(/;load\(\);setInterval/, ';setInterval'), context);
  return {context, element};
}
test('timestamps follow the viewer timezone instead of a hardcoded one',()=>{
 assert.ok(!html.includes('Asia/Bangkok'));
 assert.ok(!html.includes('UTC+07:00'));
 assert.ok(html.includes('Intl.DateTimeFormat().resolvedOptions().timeZone'));
});
test('all application-authored dashboard text is English',()=>{
 assert.doesNotMatch(html, /[\u0E00-\u0E7F]/);
 assert.match(html, /<html lang="en">/);
});
test('dashboard text is at least 14px including mobile overrides',()=>{
 const css=html.match(/<style>([\s\S]*?)<\/style>/)[1];
 const sizes=[...css.matchAll(/font(?:-size)?\s*:\s*(\d+(?:\.\d+)?)px/g)].map(m=>Number(m[1]));
 assert.ok(sizes.length>0);
 assert.deepEqual(sizes.filter(size=>size<14),[]);
});
test('console defaults to a light color scheme',()=>{
 assert.match(html, /name="color-scheme" content="light"/);
 assert.match(html, /--bg:#f4f6f8/);
 assert.match(html, /--panel:#ffffff/);
 assert.ok(!html.includes('background:#15191c'));
});
test('session gate rejects methods that could mutate or echo state',()=>{
 const source=fs.readFileSync('desktop_service.py','utf8');
 assert.match(source,/def do_POST\(self\):\s*self\.send_error\(405\)/);
 assert.match(source,/class GuardedHandler\(dashboard\.H\)/);
 assert.match(source,/if self\.command != 'GET':/);
});
test('untrusted names and links cannot inject HTML', async()=>{
  const p = page({runners:[{name:'<img src=x onerror=alert(1)>',repo:'o/r',status:'online'}],jobs:[{repo:'o/r',name:'<script>bad<script>',status:'queued',created:null,url:'javascript:alert(1)'}],error:'<img src=x>',updated:null});
  await vm.runInContext('load()',p.context);
  const rendered = ['runners','queue','err'].map(id=>p.element(id).innerHTML).join('');
  assert.equal(vm.runInContext('esc("<script>bad<script>")', p.context), '&lt;script&gt;bad&lt;script&gt;');
  assert.ok(!rendered.includes('<img'));
  assert.ok(!rendered.includes('<script>bad'));
  assert.ok(!rendered.includes('href="javascript:'));
  assert.ok(rendered.includes('&lt;img'));
});
test('identical runner names in different repos stay separate', async()=>{
  const p=page({runners:[{name:'worker',repo:'o/a',status:'online'},{name:'worker',repo:'o/b',status:'online'}],jobs:[]});
  await vm.runInContext('load()',p.context);
  assert.equal((p.element('runners').innerHTML.match(/class="card /g)||[]).length,2);
});
test('repository filter hides unrelated runners and jobs', async()=>{
 const p=page({runners:[{name:'alpha',repo:'o/a',status:'online'},{name:'beta',repo:'o/b',status:'online'}],jobs:[]});
 await vm.runInContext('load()',p.context);
 p.element('repo').value='o/a';
 vm.runInContext('render()',p.context);
 assert.ok(!p.element('runners').innerHTML.includes('beta'));
 assert.ok(p.element('summary').innerHTML.includes('1'));
});
test('operations overview exposes fleet health and completion metrics from actual jobs',async()=>{
 const p=page({runners:[{repo:'o/a',name:'w1',status:'online',busy:true},{repo:'o/a',name:'w2',status:'offline'}],jobs:[{repo:'o/a',name:'passed',status:'completed',conclusion:'success'},{repo:'o/a',name:'failed',status:'completed',conclusion:'failure'},{repo:'o/a',name:'build',status:'in_progress',runner:'w1'}]});
 await vm.runInContext('load()',p.context);
 const view=p.element('summary').innerHTML;
 assert.ok(view.includes('Online capacity'));
 assert.ok(view.includes('50%'));
 assert.ok(p.element('health').textContent.includes('offline'));
});
test('repository health separates counts by repository',async()=>{
 const p=page({runners:[{repo:'o/a',name:'worker',status:'online'},{repo:'o/b',name:'worker',status:'offline'}],jobs:[{repo:'o/a',name:'ok',status:'completed',conclusion:'success'},{repo:'o/b',name:'bad',status:'completed',conclusion:'failure'}]});
 await vm.runInContext('load()',p.context);
 assert.ok(p.element('repo-health').innerHTML.includes('o/a'));
 assert.ok(p.element('repo-health').innerHTML.includes('o/b'));
 assert.ok(p.element('repo-health').innerHTML.includes('1 failed'));
});
test('footer advertises a newer release when one is detected',async()=>{
 const p=page({runners:[],jobs:[],version:'1.0.5',latest_version:'1.0.6'});
 await vm.runInContext('load()',p.context);
 assert.match(p.element('app-version').textContent,/Update available: v1\.0\.6/);
 assert.match(p.element('app-version').textContent,/v1\.0\.5/);
});
test('footer treats a two-digit minor as newer',async()=>{
 const p=page({runners:[],jobs:[],version:'1.0.9',latest_version:'1.0.10'});
 await vm.runInContext('load()',p.context);
 assert.match(p.element('app-version').textContent,/Update available: v1\.0\.10/);
});
test('footer does not advertise an update when versions match',async()=>{
 const p=page({runners:[],jobs:[],version:'1.0.6',latest_version:'1.0.6'});
 await vm.runInContext('load()',p.context);
 assert.doesNotMatch(p.element('app-version').textContent,/Update available/);
});
test('missing timestamps render a dash rather than NaN',async()=>{
 const p=page({runners:[],jobs:[{name:'waiting',repo:'o/a',status:'queued',created:null}]});
 await vm.runInContext('load()',p.context);
 assert.equal(vm.runInContext('dur(NaN)',p.context),'—');
});
test('failed refresh is visible and keeps previously rendered content', async()=>{
  const p=page({runners:[],jobs:[]});
  await vm.runInContext('load()',p.context);
  const before=p.element('runners').innerHTML;
  p.context.fetch=async()=>{throw Error('offline')};
  await vm.runInContext('load()',p.context);
  assert.equal(p.element('runners').innerHTML,before);
  assert.ok(p.element('connection').textContent.includes('failed'));
});
