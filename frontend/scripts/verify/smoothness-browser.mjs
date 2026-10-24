import { chromium, webkit } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
// Run against npm run build + vite preview (no mock mode). All backend traffic is intercepted.
const origin=process.env.SMOOTHNESS_ORIGIN || 'http://127.0.0.1:4317';
const engine=process.env.SMOOTHNESS_BROWSER || 'chromium';
assert(['chromium','webkit'].includes(engine));
const browser=await (engine==='webkit' ? webkit.launch({headless:true}) : chromium.launch({channel:'chrome',headless:true}));
const output={environment:{engine,browser:browser.version(),build:'production',backend:'intercepted synthetic data only'},cases:[]};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const pagination={has_more:false,next_cursor:null,total_count:20};
const timestamp='2026-10-03T01:00:00Z';
function session(id){return {id,patient_id:'p-'+id,patient_name:'AUDIT patient '+id,chief_complaint_text:'Synthetic test',status:'completed',red_flag:false,language:'zh-TW',created_at:timestamp,updated_at:timestamp};}
const report=(i)=>({id:'r'+i,session_id:'s'+i,status:'generated',review_status:'pending',summary:'Synthetic audit report',patient_name:'Already included '+i,chief_complaint_text:'Already included',session_status:'completed',red_flag:false,generated_at:timestamp,created_at:timestamp,updated_at:timestamp});
async function setup({authFailure=false,delayRead=0,delayPatients=0,offline=false,viewport={width:1280,height:800}}={}){
 const context=await browser.newContext({locale:'zh-TW',viewport});
 await context.addInitScript(()=>{localStorage.setItem('access_token','audit-fake-access');localStorage.setItem('refresh_token','audit-fake-refresh');localStorage.setItem('urosense:lng','zh-TW');});
 let version=0;
 const page=await context.newPage();const api=[],assets=[],errors=[],sockets=[];
 if(offline)await page.clock.install();
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(p.startsWith('/locales/'))assets.push({path:p,status:r.status()});});
 await page.routeWebSocket('**/*',socket=>{sockets.push(socket);if(offline)socket.close({code:1011,reason:'synthetic outage'});else socket.onMessage(()=>{});});
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url()),p=url.pathname;
  if(p.includes('/api/v1/')){
   const path=p.split('/api/v1')[1];api.push({path,search:url.search,method:route.request().method(),time:Date.now()});
   let data={},status=200;
   if(path==='/auth/me'){if(authFailure){status=503;data={detail:'synthetic temporary outage'};}else data={id:'audit-doctor',name:'AUDIT doctor',email:'audit@example.invalid',role:'doctor',is_active:true};}
   else if(path==='/reports')data={data:Array.from({length:20},(_,i)=>({...report(i),patient_name:'Already included '+i+(version?' updated':'')})),review_counts:{pending:120,approved:30},pagination:{...pagination,total_count:150}};
   else if(path.startsWith('/reports/'))data=report(0);
   else if(path==='/sessions')data={data:[session('s0')],pagination:{...pagination,total_count:1}};
   else if(/^\/sessions\/[^/]+$/.test(path))data=session(path.split('/').at(-1));
   else if(path.endsWith('/conversations'))data={data:[],pagination};
   else if(path==='/notifications')data={data:[{id:'n1',type:'session_complete',title:'AUDIT notification'+(version?' updated':''),is_read:false,data:{session_id:'s0'},created_at:timestamp}],unread_count:version?2:1,pagination:{...pagination,total_count:1}};
   else if(path==='/notifications/n1/read'){await pause(delayRead);data={id:'n1',is_read:true,read_at:timestamp};}
   else if(path.endsWith('count'))data={count:1+version};
   else if(path.includes('/alerts'))data={data:[],pagination};
   else if(path==='/dashboard/monthly-summary')data={month:'2026-10',month_label:'2026年10月',total_sessions:1,total_red_flag_alerts:0,chief_complaint_distribution:[],language_distribution:[],status_distribution:[],daily_trend:[]};
   else data={data:[],pagination};
   try{await route.fulfill({status,json:data});}catch{}return;
  }
  if(url.origin!==origin){await route.abort();return;}
  if(p.includes('/assets/PatientListPage-'))await pause(delayPatients);
  await route.continue();
 });
 return {context,page,api,assets,errors,sockets,setVersion:v=>{version=v;}};
}
try{
 const a=await setup({delayRead:1200,delayPatients:1000});
 let started=Date.now();await a.page.goto(origin+'/zh-TW/reports');
 await a.page.locator('aside').waitFor({state:'visible',timeout:20000});
 await a.page.getByText('Already included 0',{exact:true}).waitFor({timeout:20000});
 await pause(150);
 const listCalls=a.api.filter(x=>x.path==='/reports'||/^\/sessions\/[^/]+$/.test(x.path));
 output.cases.push({name:'report-list',ready_ms:Date.now()-started,report_requests:listCalls.filter(x=>x.path==='/reports').map(x=>x.search),session_requests:listCalls.filter(x=>x.path.startsWith('/sessions/')).length,total:listCalls.length,locale_requests:a.assets,errors:a.errors.slice()});
 assert.equal(listCalls.filter(x=>x.path.startsWith('/sessions/')).length,0);
 assert.equal(listCalls.length,1);
 assert(a.assets.every(x=>!/^\/locales\/(zh|en|ja|ko|vi)\//.test(x.path)));
 await a.page.getByText('150',{exact:true}).waitFor();
 await a.page.locator('a[href="/zh-TW/patients"]').click();
 await pause(250);
 output.cases.push({name:'lazy-route-shell',injected_chunk_delay_ms:1000,at_250ms:{sidebar_visible:await a.page.locator('aside').isVisible(),header_visible:await a.page.locator('header').isVisible(),spinner_count:await a.page.locator('.animate-spin').count()}});
 assert.equal(await a.page.locator('aside').isVisible(),true);
 assert.equal(await a.page.locator('header').isVisible(),true);
 await pause(1000);
 // Navigate with the persistent header bell after the research chunk has settled.
 await a.page.locator('header button[aria-label]').evaluateAll(nodes=>nodes.map(n=>({label:n.getAttribute('aria-label')}))).then(labels=>output.header_labels=labels);
 await a.page.getByRole('button',{name:'通知',exact:true}).click();
 await a.page.getByText('AUDIT notification',{exact:true}).waitFor();
 await a.page.evaluate(()=>{window.__navStarted=performance.now();window.__navElapsed=null;const push=history.pushState.bind(history);history.pushState=(...args)=>{push(...args);if(String(args[2]).includes('/sessions/s0'))window.__navElapsed=performance.now()-window.__navStarted;};});
 started=Date.now();await a.page.getByText('AUDIT notification',{exact:true}).click();
 await pause(250);
 const at250={path:new URL(a.page.url()).pathname,loading_spinners:await a.page.locator('.animate-spin').count()};
 assert.equal(at250.path,'/zh-TW/sessions/s0');
 await a.page.waitForURL('**/sessions/s0',{timeout:5000});
 output.cases.push({name:'notification-click',injected_mark_read_delay_ms:1200,at_250ms:at250,navigation_ms:await a.page.evaluate(()=>window.__navElapsed)});
 await a.context.close();
 const live=await setup();await live.page.goto(origin+'/zh-TW/notifications');
 await live.page.getByText('AUDIT notification',{exact:true}).waitFor();await pause(200);
 let countBefore=live.api.filter(x=>x.path==='/notifications').length;
 live.setVersion(1);
 for(const type of ['report_generated','stats_updated','session_status_changed'])live.sockets[0].send(JSON.stringify({type,payload:{},timestamp}));
 await live.page.getByText('AUDIT notification updated',{exact:true}).waitFor({timeout:2000});
 assert.equal(live.api.filter(x=>x.path==='/notifications').length-countBefore,1);
 await live.page.locator('a[href="/zh-TW/reports"]').click();
 await live.page.getByText('Already included 0 updated',{exact:true}).waitFor();
 assert.equal(live.sockets.length,1,'Route change must retain the dashboard connection');
 live.setVersion(0);countBefore=live.api.filter(x=>x.path==='/reports').length;
 live.sockets[0].send(JSON.stringify({type:'report_generated',payload:{},timestamp}));
 await live.page.getByText('Already included 0',{exact:true}).waitFor({timeout:2000});
 assert.equal(live.api.filter(x=>x.path==='/reports').length-countBefore,1);
 assert.deepEqual(live.errors,[]);output.cases.push({name:'live-notifications-and-reports',passed:true,sockets:live.sockets.length});
 await live.context.close();
 const b=await setup({authFailure:true});
 await b.page.goto(origin+'/zh-TW/notifications');
 await b.page.getByRole('button').filter({hasText:'重試'}).waitFor({timeout:20000});
 assert.equal(new URL(b.page.url()).pathname,'/zh-TW/notifications');
 assert(await b.page.evaluate(()=>!!localStorage.getItem('access_token')&&!!localStorage.getItem('refresh_token')));
 output.cases.push({name:'bootstrap-503',path:new URL(b.page.url()).pathname,tokens:await b.page.evaluate(()=>({access_present:!!localStorage.getItem('access_token'),refresh_present:!!localStorage.getItem('refresh_token')})),requests:b.api.map(x=>({path:x.path,status:x.path==='/auth/me'?503:200}))});
 await b.context.close();
 const c=await setup();await c.page.goto(origin+'/zh-TW/sessions');
 await c.page.getByText('AUDIT patient s0',{exact:true}).waitFor({timeout:20000});
 const before=c.api.filter(x=>x.path==='/sessions').length;
 assert(c.sockets.length>0);
 for(const type of ['session_created','session_status_changed','queue_updated'])c.sockets.at(-1).send(JSON.stringify({type,payload:{sessionId:'s0',status:'in_progress'},timestamp}));
 await pause(250);
 output.cases.push({name:'ws-event-burst',events:3,additional_list_requests:c.api.filter(x=>x.path==='/sessions').length-before});
 assert.equal(c.api.filter(x=>x.path==='/sessions').length-before,1);
 assert.equal(c.sockets.length,1);
 assert.deepEqual(c.errors,[]);
 await c.context.close();
 const d=await setup({offline:true});await d.page.goto(origin+'/zh-TW/notifications');
 await d.page.getByText('AUDIT notification',{exact:true}).waitFor();await pause(250);
 d.setVersion(1);await d.page.clock.fastForward(20500);
 await d.page.getByRole('status').filter({hasText:'紅旗'}).waitFor({timeout:3000});
 assert.deepEqual(d.errors,[]);output.cases.push({name:'disconnected-poll-alert',passed:true});
 await d.context.close();
 // Mobile layout must leave room for content and retain keyboard-accessible navigation.
 for(const width of [320,390]){
  const m=await setup({viewport:{width,height:844}});
  await m.page.goto(origin+'/zh-TW/reports');
  await m.page.getByText('Already included 0',{exact:true}).waitFor();
  const checkLayout=async()=>{
   const layout=await m.page.locator('main').evaluate(e=>({left:e.getBoundingClientRect().left,outer:e.getBoundingClientRect().width,width:e.clientWidth,scroll:e.scrollWidth,viewport:innerWidth,document:document.documentElement.scrollWidth,header:document.querySelector('header').getBoundingClientRect().height}));
   assert.equal(layout.left,0);assert.equal(layout.outer,width);
   assert(layout.scroll<=layout.width+1,JSON.stringify(layout));
   assert.equal(layout.document,layout.viewport);assert.equal(layout.header,56);
  };
  await checkLayout();
  assert.equal(await m.page.locator('aside').isVisible(),false);
  const toggle=m.page.getByRole('button',{name:'導覽選單',exact:true});
  await toggle.focus();await toggle.press('Enter');
  const dialog=m.page.getByRole('dialog',{name:'導覽選單'});
  await dialog.waitFor();
  await m.page.keyboard.press('Shift+Tab');
  assert(await dialog.evaluate(e=>e.contains(document.activeElement)));
  await m.page.keyboard.press('Escape');
  await dialog.waitFor({state:'hidden'});
  assert(await toggle.evaluate(e=>e===document.activeElement));
  await toggle.click();
  await dialog.locator('a[href="/zh-TW/sessions"]').click();
  await m.page.getByText('AUDIT patient s0',{exact:true}).waitFor();
  assert.equal(await dialog.count(),0);await checkLayout();
  await m.page.goto(origin+'/zh-TW/patient');
  await m.page.locator('header').waitFor();await checkLayout();
  assert.deepEqual(m.errors,[]);
  output.cases.push({name:'mobile-navigation',width,passed:true});
  await m.context.close();
 }
} catch(e){output.failure=e.stack;process.exitCode=1;} finally{await writeFile(process.env.SMOOTHNESS_OUTPUT || '/tmp/gu-smoothness-acceptance.json',JSON.stringify(output,null,2));console.log(JSON.stringify(output,null,2));await browser.close();}
