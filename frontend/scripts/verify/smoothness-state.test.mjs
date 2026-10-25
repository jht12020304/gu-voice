import assert from 'node:assert/strict';
import axios from 'axios';
const values = new Map();
globalThis.localStorage = {getItem: k => values.get(k) ?? null, setItem: (k,v) => values.set(k,String(v)), removeItem: k => values.delete(k), clear: () => values.clear()};
globalThis.window = {location:{pathname:'/zh-TW/notifications',href:''}};
globalThis.document = {cookie:''};
globalThis.__IMPORT_META_ENV__ = {VITE_API_BASE_URL:'http://api.test/api/v1'};
const {default: client, invalidateAuthSession, refreshAccessToken} = await import('../../src/services/api/client.ts');
const {useAuthStore: auth} = await import('../../src/stores/authStore.ts');
const {useReportStore: reports} = await import('../../src/stores/reportStore.ts');
const {useAlertStore: alerts} = await import('../../src/stores/alertStore.ts');
const {useNotificationStore: notifications} = await import('../../src/stores/notificationStore.ts');
const {coalesceRefresh} = await import('../../src/utils/coalesceRefresh.ts');
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;});return {promise,resolve,reject}; };
let handle;
const adapter = async config => {
  const response = {data:null,status:200,statusText:'OK',headers:{},config};
  try { response.data = await handle(config); return response; }
  catch(error) { error.config=config; if(error.status)error.response={...response,status:error.status};throw error; }
};
client.defaults.adapter=adapter; axios.defaults.adapter=adapter;
const page = (id, extras={}) => ({data:[{id}],pagination:{has_more:false,next_cursor:null,total_count:1},...extras});
function reset(id='a') {
  invalidateAuthSession(); values.clear(); values.set('access_token','access-'+id);values.set('refresh_token','refresh-'+id);
  auth.setState({...auth.getInitialState(),user:{id,role:'doctor'},isAuthenticated:true,isLoading:false});
}
for(const status of [503,undefined]) {
  reset('transient-'+status);
  handle=async()=>{throw Object.assign(new Error('temporary outage'),{status});};
  await auth.getState().hydrateFromStorage();
  assert(auth.getState().recoveryRequired);assert(values.has('access_token'));assert(values.has('refresh_token'));
  handle=async()=>({id:'restored',role:'doctor'});
  await auth.getState().hydrateFromStorage();
  assert(!auth.getState().recoveryRequired);assert.equal(auth.getState().user.id,'restored');
}
reset('invalid');
handle=async()=>{throw Object.assign(new Error('unauthorized'),{status:401});};
await auth.getState().hydrateFromStorage();
assert(!values.has('access_token'));assert(!values.has('refresh_token'));assert.equal(window.location.href,'/zh-TW/login');

reset('old');const old = deferred();handle=()=>old.promise;
const hydrating=auth.getState().hydrateFromStorage();await pause(0);
reset('new');old.reject(Object.assign(new Error('old unauthorized'),{status:401}));await hydrating;
assert.equal(auth.getState().user.id,'new');assert.equal(values.get('access_token'),'access-new');

reset('refresh');let calls=0;const gate=deferred();
handle=async()=>{calls++;await gate.promise;return {access_token:'rotated',refresh_token:'rotated-refresh'};};
const refreshing=[refreshAccessToken(),refreshAccessToken(),refreshAccessToken()];await pause(0);assert.equal(calls,1);
gate.resolve();await Promise.all(refreshing);assert.equal(values.get('access_token'),'rotated');

for(const [store,action] of [[reports,'fetchReports'],[alerts,'fetchAlerts']]) {
  for(const staleFailure of [false,true]) {
    reset('list-'+action+staleFailure);const oldList=deferred(),freshList=deferred();let call=0;
    handle=()=>++call===1?oldList.promise:freshList.promise;
    const a=store.getState()[action]();await pause(0);const b=store.getState()[action]();await pause(0);
    freshList.resolve(page('fresh'));await b;
    staleFailure ? oldList.reject(new Error('late failure')) : oldList.resolve(page('stale'));
    await a;assert.equal((store.getState().reports ?? store.getState().alerts)[0].id,'fresh');assert.equal(store.getState().error,null);
  }
}
reset('read');notifications.setState({notifications:[{id:'n',isRead:false}],unreadCount:1});
const read=deferred();handle=config=>config.url.endsWith('/read')?read.promise:config.url.endsWith('count')?{count:0}:page('n',{data:[{id:'n',is_read:false}],unread_count:1});
const reading=notifications.getState().markRead('n');assert(notifications.getState().notifications[0].isRead);
await notifications.getState().fetchNotifications(false);assert(notifications.getState().notifications[0].isRead);assert.equal(notifications.getState().unreadCount,0);
read.resolve({id:'n',is_read:true});await reading;await pause(0);assert.equal(notifications.getState().unreadCount,0);
reset('read-fail');notifications.setState({notifications:[{id:'n',isRead:false}],unreadCount:1});
handle=config=>{if(config.url.endsWith('/read'))throw new Error('offline');return config.url.endsWith('count')?{count:1}:page('n',{data:[{id:'n',is_read:false}],unread_count:1});};
await notifications.getState().markRead('n');await pause(0);assert(!notifications.getState().notifications[0].isRead);assert.equal(notifications.getState().unreadCount,1);assert(notifications.getState().error);

let refreshes=0;const inFlight=deferred();const refresh=coalesceRefresh(async()=>{if(++refreshes===1)await inFlight.promise;},1);
refresh.schedule();refresh.schedule();refresh.schedule();await pause(10);assert.equal(refreshes,1);
refresh.schedule();refresh.schedule();inFlight.resolve();await pause(10);assert.equal(refreshes,2);
refresh.schedule();refresh.dispose();await pause(10);assert.equal(refreshes,2);
console.log('PASS: transient auth, retry, rejected credentials, account isolation, refresh single flight, reverse replies, optimistic read rollback, event coalescing');
