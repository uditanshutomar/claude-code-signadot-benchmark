import {createRequire} from 'node:module';
const require=createRequire(process.env.CTBENCH_ROOT+'/tools/package.json');
const {chromium}=require('playwright');
import {sameId, plateFrom, fareMatches, showsTotal, ETA_COUNTDOWN, historyShape} from './parse.mjs';
const knownBrowserErrors=require(process.env.CTBENCH_ROOT+'/config/known-browser-errors.json').errors;
const [task, namespace, key, mode, base, location, baselineURL, outputDir]=process.argv.slice(2);
const report={status:'FAIL',task,mode,checks:[],network:[]};
const assert=(value,message)=>{if(!value)throw new Error(message);report.checks.push(message);};
const headers={baggage:`sd-routing-key=${key}`};
class UnsupportedShape extends Error {}
const supported=(value,message)=>{if(!value)throw new UnsupportedShape(message);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function poll(fn, message, ms=45000) {
 const end=Date.now()+ms;
 while(Date.now()<end){const value=await fn();if(value)return value;await sleep(300);}
 throw new Error(message);
}
function entriesDeep(value, path=[]) {
 if(!value || typeof value!=='object')return [{path,value}];
 return Object.entries(value).flatMap(([k,v])=>entriesDeep(v,[...path,k]));
}
// A missing list or count fails the task; only a shape with several lists needs a human to review it.
function listShape(value) {
 const shape=historyShape(value);
 supported(!shape.ambiguous,'Unsupported history representation: '+shape.ambiguous+'. Review the response before scoring.');
 assert(!shape.missing,'history response has a list of rides and a total count');
 return shape;
}
const leaves=x=>entriesDeep(x).map(x=>x.value);
function changedAt(value,path,replacement) {
 const copy=structuredClone(value);let target=copy;
 for(const k of path.slice(0,-1))target=target[k];
 target[path.at(-1)]=replacement;return copy;
}
const moneyIn=(text,value)=>[...text.matchAll(/(?:^|[^\d.])(\d+(?:\.\d+)?)(?![\d.])/g)].some(m=>Math.abs(Number(m[1])-value)<0.011);
function currentTime(value) {
 const parsed=typeof value==='number'?(value<1e11?value*1000:value):Date.parse(value);
 return Number.isFinite(parsed)&&Math.abs(Date.now()-parsed)<180000;
}
let browser,context,page;
try {
 browser=await chromium.launch({headless:true,args:['--proxy-server=direct://','--proxy-bypass-list=*']});
 report.browserVersion=browser.version();
 report.playwrightVersion=require('playwright/package.json').version;
 context=await browser.newContext({viewport:{width:1440,height:1000},extraHTTPHeaders:{}});
 await context.route('**/*',async route=>{
  if(!route.request().url().startsWith(base+'/'))return route.continue();
  const h=route.request().headers();h.baggage=[h.baggage?.replace(/(?:^|,)\s*sd-routing-key=[^,]*/g,''),`sd-routing-key=${key}`].filter(Boolean).join(',');
  await route.continue({headers:h});
 });
 const api=await require('playwright').request.newContext({extraHTTPHeaders:headers});
 const locResp=await api.get(location+'/locations',{timeout:15000});
 assert(locResp.ok(),'location endpoint responds');
 const locs=await locResp.json();
 assert(Array.isArray(locs)&&locs.length===5,'five seeded locations returned');
 if(task==='t1') {
  assert(locs.every(l=>typeof l.locID==='string'&&/^\d+$/.test(l.locID)&&typeof l.id==='string'&&!('name' in l)),'location contract uses digit-string locID and name in id');
  assert(JSON.stringify(Object.fromEntries(locs.map(l=>[l.locID,l.id])))===JSON.stringify({'1':'My Home','123':"Rachel's Floral Designs",'392':'Trom Chocolatier','567':'Amazing Coffee Roasters','731':'Japanese Desserts'}),'all location names retain their meaning');
 }
 page=await context.newPage();const notes=[],writes=[],errors=[];
 report.browserErrors=errors;
 page.on('pageerror',e=>errors.push({message:e.message,stack:e.stack}));
 page.on('requestfailed',r=>report.network.push({url:r.url(),failure:r.failure()}));
 page.on('response',async res=>{
  const path=new URL(res.url()).pathname;
  if(path!=='/notifications')report.network.push({path,status:res.status()});
  if(path==='/notifications') {try{const d=await res.json();notes.push(...(d.notifications||[]));}catch{}}
  if(path==='/ride-history' && ['POST','PATCH'].includes(res.request().method())) {
   try {writes.push({method:res.request().method(),status:res.status(),url:res.url(),body:res.request().postDataJSON()});}catch(e){writes.push({method:res.request().method(),status:res.status(),parseError:String(e)});}
  }
 });
 if(task==='t2') {
  const direct=await api.get(location+'/ride-history');
  assert(direct.ok(),'location GET ride-history is implemented');
  const proxy=await api.get(base+'/ride-history');
  if(!proxy.ok())report.httpFailure={url:proxy.url(),status:proxy.status(),body:(await proxy.text()).slice(0,4000)};
  assert(proxy.ok(),'frontend GET ride-history proxy is implemented');
  const before=listShape(await proxy.json());
  report.historyBefore=before.total;
 }
 await page.goto(base,{waitUntil:'domcontentloaded',timeout:60000});
 await page.getByRole('combobox').nth(0).selectOption({label:'My Home'},{timeout:15000});
 await page.getByRole('combobox').nth(1).selectOption({label:"Rachel's Floral Designs"});
 await page.getByRole('button',{name:'Request Ride',exact:true}).click();
 const assigned=await poll(()=>notes.find(n=>n.context?.baselineWorkload==='driver'&&/arriv/i.test(n.body)), 'No driver assignment notification reached the browser');
 report.driverNotification=assigned;
 const plate=plateFrom(assigned.body);
 assert(!!plate,'driver notification includes a plate');
 assert(sameId(assigned.context.request.pickupLocationID,1)&&sameId(assigned.context.request.dropoffLocationID,123),'dispatch preserves the selected location identities');
 assert(assigned.context.routingKey===key&&assigned.context.sandboxName?.startsWith('ctg-'),'assignment came from the graded driver fork');
 const duration=assigned.body.match(/arriv\w*\s+in\s+((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?)/i)?.[1];
 assert(!!duration,'driver notification includes the route ETA');
 const seconds=[...duration.matchAll(/([\d.]+)(h|m|s)/g)].reduce((n,m)=>n+Number(m[1])*({h:3600,m:60,s:1}[m[2]]),0);
 report.etaSeconds=seconds;
 // FAST_ROUTE is a repository-supported fixture. The normal case uses actual random route ETAs.
 assert(mode==='fast'?seconds===1:seconds>=180,'ETA exercises the intended fare branch');
 if(task==='t1' || mode==='fast') {
  await page.getByText(/arrived/i).first().waitFor({state:'visible',timeout:15000});
  report.checks.push('UI reports driver arrival');
 } else {
  await page.getByText(ETA_COUNTDOWN).first().waitFor({state:'visible',timeout:15000});
  report.checks.push('UI displays the live ETA');
 }
 if(task==='t2') {
  const amount=assigned.body.match(/(?:fare\s*[:=]?\s*\$?|\$)(\d+(?:\.\d+)?)/i)?.[1];
  assert(amount!==undefined,'driver notification includes a parseable fare');
  const fare=Number(amount);
  assert(fareMatches(fare,seconds),'fare matches max(3.50, 1.50 times ETA minutes)');
  report.fare=fare;
  const patch=await poll(()=>writes.find(x=>x.method==='PATCH'&&x.status>=200&&x.status<300),'UI did not successfully PATCH ride history');
  const post=writes.find(x=>x.method==='POST'&&x.status>=200&&x.status<300);
  assert(!!post,'UI creates a history entry after dispatch');
  assert(leaves(post.body).includes('My Home')&&leaves(post.body).includes("Rachel's Floral Designs"),'created history contains pickup and dropoff names');
  assert(leaves(patch.body).includes(plate)&&leaves(patch.body).some(v=>Math.abs(Number(v)-fare)<0.011),'UI PATCH carries assigned plate and fare');
  const history=await poll(async()=>{
   const r=await api.get(location+'/ride-history');if(!r.ok())return null;
   const h=historyShape(await r.json());if(h.missing||h.ambiguous)return null;
   return h&&h.rows.some(row=>leaves(row).includes(plate))?h:null;
  },'location API did not persist assigned ride');
  assert(history.total===report.historyBefore+1,'history total increments exactly once per ride');
  const row=history.rows.find(row=>leaves(row).includes(plate));
  assert(leaves(row).includes('My Home')&&leaves(row).includes("Rachel's Floral Designs"),'stored history preserves location names');
  assert(leaves(row).some(currentTime),'history contains the current request timestamp');
  assert(leaves(row).some(v=>Math.abs(Number(v)-fare)<0.011),'stored history preserves assigned fare');
  await page.getByText('Ride History',{exact:true}).waitFor({state:'visible'});
  const uiRow=page.getByRole('row').filter({hasText:plate});
  await uiRow.waitFor({state:'visible',timeout:10000});
  assert(moneyIn(await uiRow.innerText(),fare),'history table displays assigned fare');
  const body=await page.locator('body').innerText();
  assert(showsTotal(body,history.total),'UI displays total ride count');
  assert((await uiRow.innerText()).includes('My Home')&&(await uiRow.innerText()).includes("Rachel's Floral Designs"),'history table displays pickup and dropoff names');
  assert(await uiRow.getByRole('cell').count()>=5,'history table includes the five requested columns');
  const historyBox=await page.getByText('Ride History',{exact:true}).boundingBox();
  const formButtonBox=await page.getByRole('button',{name:'Request Ride',exact:true}).boundingBox();
  assert(historyBox&&formButtonBox&&historyBox.y>formButtonBox.y,'history card appears below the ride form');
  // The prompt puts the fare in the ETA countdown, which is only on screen while a normal-length ride counts down.
  if(mode==='normal') {
   const etaText=await page.getByText(ETA_COUNTDOWN).first().innerText();
   assert(moneyIn(etaText,fare),'fare is visible in the ETA countdown');
  }
  // Replay the UI's PATCH shape directly against location, then GET through frontend.
  const platePath=entriesDeep(patch.body).find(x=>x.value===plate)?.path;
  const farePath=entriesDeep(patch.body).find(x=>/fare|amount|price/i.test(x.path.at(-1)||'')&&Math.abs(Number(x.value)-fare)<0.011)?.path;
  supported(platePath&&farePath,'Unsupported PATCH representation: cannot derive plate/fare fields. Review before scoring.');
  const replay=changedAt(changedAt(patch.body,platePath,'CTCHECK123'),farePath,7.25);
  const patchPath=new URL(patch.url).pathname+new URL(patch.url).search;
  const pr=await api.patch(location+patchPath,{data:replay});assert(pr.ok(),'location PATCH works directly');
  const proxied=listShape(await (await api.get(base+'/ride-history')).json());
  assert(proxied.rows.some(x=>leaves(x).includes('CTCHECK123')&&leaves(x).some(v=>Number(v)===7.25)),'frontend GET reflects direct location PATCH');
  // Restore values before reload, then verify persistence through a new document.
  assert((await api.patch(location+patchPath,{data:patch.body})).ok(),'history update can be restored');
  await page.reload();await page.getByRole('row').filter({hasText:plate}).waitFor({state:'visible',timeout:15000});
  report.checks.push('history survives browser reload');
  const createdDirect=await api.post(location+'/ride-history',{data:post.body});
  assert(createdDirect.ok(),'location POST works directly with UI payload');
  const afterDirect=listShape(await (await api.get(base+'/ride-history')).json());
  assert(afterDirect.total===history.total+1,'direct POST increments count visible through frontend');
  report.observedWrites=writes;
 }
 report.knownBaselineBrowserErrors=errors.filter(e=>knownBrowserErrors.some(k=>e.message===k.message&&e.stack.includes(k.stack_contains)));
 assert(errors.length===report.knownBaselineBrowserErrors.length,'no new uncaught browser errors');
 report.status='PASS';
} catch(e) {
 if(e instanceof UnsupportedShape)report.status='HARNESS_ERROR';
 report.error=e.message;report.stack=e.stack;
 if(browser && /Timeout|ECONN|net::|ENOTFOUND|socket hang up/i.test(e.message)) {
  // A failed baseline page load in a separate, un-routed context is an infrastructure failure.
  const control=await browser.newContext();
  try {
   const p=await control.newPage();
   const response=await p.goto(baselineURL,{waitUntil:'domcontentloaded',timeout:20000});
   report.baselineProbe={status:response.status()};
   if(!response.ok())report.status='HARNESS_ERROR';
  } catch(error) {report.baselineProbe={error:error.message};report.status='HARNESS_ERROR';}
  finally {await control.close();}
 }
} finally {if(page)try{await page.screenshot({path:`${outputDir}/ui-${mode}.png`,fullPage:true,timeout:5000});}catch{} if(browser)await browser.close();}
process.stdout.write(JSON.stringify(report,null,2)+'\n');
process.exitCode=report.status==='PASS'?0:1;
