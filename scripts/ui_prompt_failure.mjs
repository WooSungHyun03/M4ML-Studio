// Run only against the explicit allocator-quota fault-test server, not normal users' projects.
import {createRequire} from 'node:module';import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';
const {chromium}=createRequire((process.env.PW_DIR||process.cwd())+'/')('playwright');
const [url,out]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:1366,height:768}});const errors=[];
page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>m.type()==='error'&&errors.push(m.text()));const result={};
try{
 await page.goto(url);await page.locator('.nav button',{hasText:'마스크 생성'}).click();const canvas=page.locator('canvas.edit');
 await page.waitForFunction(()=>Number(document.querySelector('canvas.edit')?.getAttribute('width'))>100);
 const box=await canvas.boundingBox();const firstRequest=page.waitForRequest(r=>r.method()==='POST'&&/\/prompt$/.test(r.url()));
 await canvas.click({position:{x:box.width*.38,y:box.height*.46}});const first=(await firstRequest).postDataJSON();
 const alert=page.getByRole('alert').filter({hasText:'GPU 메모리'});await alert.waitFor({timeout:240000});
 await page.screenshot({path:path.join(out,'gpu-oom.png')});
 const retryRequest=page.waitForRequest(r=>r.method()==='POST'&&/\/prompt$/.test(r.url()));
 await page.getByRole('button',{name:'같은 클릭으로 다시 계산',exact:true}).click();const retry=(await retryRequest).postDataJSON();
 assert.deepEqual(retry.points,first.points);assert.deepEqual(retry.labels,first.labels);assert.equal(retry.session_id,first.session_id);assert.ok(retry.prompt_revision>first.prompt_revision);
 await alert.waitFor({timeout:240000});await page.screenshot({path:path.join(out,'same-input-retry.png')});result.same_points_preserved=true;result.revisions=[first.prompt_revision,retry.prompt_revision];result.status='PASS';
}catch(e){result.status='FAIL';result.error=String(e);await page.screenshot({path:path.join(out,'failure.png')});}
finally{result.console_errors=errors;if(errors.length)result.status='FAIL';fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();if(result.status!=='PASS')process.exitCode=1;}
