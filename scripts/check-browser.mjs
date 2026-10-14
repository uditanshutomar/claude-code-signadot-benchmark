// No agent or model call. Run inside the worker with its configured environment.
import {createRequire} from 'node:module';
const require=createRequire(process.env.HOME+'/ctbench-tools/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true});
try {
  for(let iteration=0;iteration<3;iteration++) {
    const context=await browser.newContext();const page=await context.newPage();
    const failed=[];page.on('requestfailed',r=>{if(new URL(r.url()).hostname.endsWith('.svc'))failed.push({url:r.url(),error:r.failure()});});
    const started=Date.now();
    await page.goto('http://frontend.ctbench-hotrod.svc:8080/',{waitUntil:'domcontentloaded',timeout:20000});
    for(let load=0;load<2;load++) {
      await page.getByRole('combobox').nth(0).selectOption({label:'My Home'},{timeout:10000});
      await page.getByRole('combobox').nth(1).selectOption({label:"Rachel's Floral Designs"});
      await page.getByRole('button',{name:'Request Ride',exact:true}).waitFor();
      if(load===0) await page.reload({waitUntil:'domcontentloaded',timeout:20000});
    }
    if(failed.length) throw Error(JSON.stringify(failed));
    console.log(JSON.stringify({iteration,browser:browser.version(),elapsedMs:Date.now()-started,internalFailures:failed}));
    if(iteration===2) {
      await page.waitForFunction(()=>[...document.querySelectorAll('.leaflet-tile')].some(i=>i.complete&&i.naturalWidth>0),{},{timeout:15000});
      await page.waitForFunction(()=>[...document.querySelectorAll('.leaflet-marker-icon')].every(i=>i.complete&&i.naturalWidth>0),{},{timeout:15000});
      await page.screenshot({path:'/tmp/ctbench-browser-check.png'});
      console.log(JSON.stringify({externalMapTilesAndMarkersLoaded:true}));
    }
    await context.close();
  }
} finally {await browser.close();}
