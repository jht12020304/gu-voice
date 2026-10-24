import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
// Run against npm run build + vite preview (no mock mode). All backend traffic is intercepted.
const origin=process.env.SMOOTHNESS_ORIGIN || 'http://127.0.0.1:4317';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
const output={environment:{browser:browser.version(),build:'production',backend:'intercepted synthetic data only'},cases:[]};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const pagination={has_more:false,next_cursor:null,total_count:20};
const timestamp='2026-10-03T01:00:00Z';
function session(id){return {id,patient_id:'p-'+id,patient_name:'AUDIT patient '+id,chief_complaint_text:'Synthetic test',status:'completed',red_flag:false,language:'zh-TW',created_at:timestamp,updated_at:timestamp};}
const report=(i)=>({id:'r'+i,session_id:'s'+i,status:'generated',review_status:'pending',summary:'Synthetic audit report',patient_name:'Already included '+i,chief_complaint_text:'Already included',session_status:'completed',red_flag:false,generated_at:timestamp,created_at:timestamp,updated_at:timestamp});
async function setup({authFailure=false,delayRead=0,delayPatients=0,activeSession=false,transcriptRows=40,listRows=20}={}){
 const context=await browser.newContext({permissions:['microphone'],locale:'zh-TW',viewport:{width:1280,height:800}});
 await context.addInitScript(()=>{localStorage.setItem('access_token','audit-fake-access');localStorage.setItem('refresh_token','audit-fake-refresh');localStorage.setItem('urosense:lng','zh-TW');});
 await context.addInitScript(()=>{
  window.__smoothness={commits:0,bubbleUpdates:0,microphone:false,longTasks:[]};
  const lastBubbleProps = new Map();
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__={supportsFiber:true,inject:()=>1,onCommitFiberRoot:(_id,root)=>{
   window.__smoothness.commits++;
   const visit=f=>{if(!f)return;if(f.memoizedProps?.message?.id){const id=f.memoizedProps.message.id;if(lastBubbleProps.get(id)!==f.memoizedProps)window.__smoothness.bubbleUpdates++;lastBubbleProps.set(id,f.memoizedProps);}visit(f.child);visit(f.sibling);};visit(root.current);
  },onCommitFiberUnmount:()=>{}};
  new PerformanceObserver(list=>{for(const e of list.getEntries())window.__smoothness.longTasks.push(e.duration);}).observe({type:'longtask',buffered:true});
  const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia=async options=>{const result=await original(options);window.__smoothness.microphone=true;return result;};
 });
 const page=await context.newPage();const api=[],assets=[],errors=[],sockets=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(p.startsWith('/locales/'))assets.push({path:p,status:r.status()});});
 await page.routeWebSocket('**/*',socket=>{sockets.push(socket);socket.onMessage(()=>{});});
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url()),p=url.pathname;
  if(p.includes('/api/v1/')){
   const path=p.split('/api/v1')[1];api.push({path,search:url.search,method:route.request().method(),time:Date.now()});
   let data={},status=200;
   if(path==='/auth/me'){if(authFailure){status=503;data={detail:'synthetic temporary outage'};}else data={id:'audit-doctor',name:'AUDIT doctor',email:'audit@example.invalid',role:'doctor',is_active:true};}
   else if(path==='/reports')data={data:Array.from({length:listRows},(_,i)=>report(i)),review_counts:{pending:120,approved:30},pagination:{...pagination,total_count:150}};
   else if(path.startsWith('/reports/'))data=report(0);
   else if(path==='/sessions')data={data:[session('s0')],pagination:{...pagination,total_count:1}};
   else if(/^\/sessions\/[^/]+$/.test(path))data={...session(path.split('/').at(-1)),status:activeSession?'in_progress':'completed'};
   else if(path.endsWith('/conversations'))data={data:Array.from({length:transcriptRows},(_,i)=>({id:'c'+i,session_id:'s0',role:i%2?'patient':'assistant',content_text:'Audit transcript '+i,sequence_number:i,created_at:timestamp})),pagination};
   else if(path==='/notifications')data={data:Array.from({length:listRows},(_,i)=>({id:'n'+i,type:'system',title:'AUDIT notification '+i,is_read:false,data:{},created_at:timestamp})),unread_count:1,pagination:{...pagination,total_count:1}};
   else if(path==='/notifications/n1/read'){await pause(delayRead);data={id:'n1',is_read:true,read_at:timestamp};}
   else if(path.endsWith('count'))data={count:1};
   else if(path.includes('/alerts'))data={data:[],pagination};
   else if(path==='/dashboard/monthly-summary')data={month:'2026-10',month_label:'2026年10月',total_sessions:1,total_red_flag_alerts:0,chief_complaint_distribution:[],language_distribution:[],status_distribution:[],daily_trend:[]};
   else data={data:[],pagination};
   try{await route.fulfill({status,json:data});}catch{}return;
  }
  if(url.origin!==origin){await route.abort();return;}
  if(p.includes('/assets/PatientListPage-'))await pause(delayPatients);
  await route.continue();
 });
 return {context,page,api,assets,errors,sockets};
}
try {
 for(const transcriptRows of [40,200]) {
  const a=await setup({activeSession:true,transcriptRows});
  await a.page.goto(origin+'/zh-TW/conversation/s0');
  await a.page.getByText('Audit transcript '+(transcriptRows-1),{exact:true}).waitFor();
  await a.page.waitForFunction(()=>window.__smoothness.microphone);
  await pause(500);
  const initial=await a.page.evaluate(()=>({...window.__smoothness,longTasks:window.__smoothness.longTasks.length,time:performance.now()}));
  await pause(3000);
  const end=await a.page.evaluate(()=>({...window.__smoothness,time:performance.now()}));
  const result={name:'voice',transcriptRows,sample_ms:end.time-initial.time,root_commits:end.commits-initial.commits,bubble_updates:end.bubbleUpdates-initial.bubbleUpdates,long_tasks_ms:end.longTasks.slice(initial.longTasks)};
  output.cases.push(result);
  assert(result.bubble_updates<=transcriptRows*2,'Waveform must not repeatedly rebuild transcript');
  assert.deepEqual(a.errors,[]);await a.context.close();
 }
 for(const path of ['reports','notifications']) for(const listRows of [100,1000]) {
  const a=await setup({listRows});let started=Date.now();
  await a.page.goto(origin+'/zh-TW/'+path);
  await a.page.locator('button.card').last().waitFor({state:'attached'});
  await a.page.waitForFunction(n=>document.querySelectorAll('button.card').length===n,listRows);
  const ready=Date.now()-started;
  await pause(300);
  const initial=await a.page.evaluate(()=>({longTasks:window.__smoothness.longTasks.length,dom:document.querySelectorAll('*').length}));
  started=Date.now();
  if(path==='reports')await a.page.locator('input[type="text"]').fill('999');
  else await a.page.locator('button.card').first().click();
  await a.page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  const interaction=Date.now()-started;
  const longTasks=await a.page.evaluate(n=>window.__smoothness.longTasks.slice(n),initial.longTasks);
  output.cases.push({name:path,listRows,ready_ms:ready,dom_nodes:initial.dom,interaction_ms:interaction,long_tasks_ms:longTasks});
  assert(interaction<200, 'Loaded list interaction exceeded 200ms on this host');
  if(path==='notifications' && listRows===1000){
    await a.page.locator('button.card').last().focus();
    await a.page.keyboard.press('Tab');await a.page.keyboard.press('Shift+Tab');
    assert(await a.page.locator('button.card').last().evaluate(n=>n===document.activeElement),'Offscreen rows must remain keyboard-accessible');
  }
  assert.deepEqual(a.errors,[]);await a.context.close();
 }
} catch(error) {output.failure=error.stack;process.exitCode=1;}
finally {await writeFile(process.env.SMOOTHNESS_OUTPUT || '/tmp/gu-smoothness-performance.json',JSON.stringify(output,null,2));console.log(JSON.stringify(output,null,2));await browser.close();}
