// Focused real-browser regression: invalid mask fallback -> genuine re-prompt -> save/confirm.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire((process.env.PW_DIR||process.cwd())+'/')('playwright');
const [url,out='evidence/mask-recovery']=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1366,height:768}});
const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>m.type()==='error'&&errors.push(m.text()));
const result={};
try{
 await page.goto(url);await page.locator('.nav button',{hasText:'마스크 검토'}).click();
 const invalid=page.locator('.film-row .cell').filter({has:page.locator('.err')}).first();
 await invalid.waitFor();const frame=await invalid.getAttribute('title');await invalid.click();
 const photo=page.getByRole('img',{name:'선택한 등록 사진',exact:true});await photo.waitFor();
 await page.waitForTimeout(1500);await page.screenshot({path:path.join(out,'invalid-photo-visible.png')});
 assert.equal(errors.length,0,'Known-invalid mask must not trigger a nonexistent resource request');
 await page.getByRole('button',{name:'포함 클릭 (1)',exact:true}).click();
 const canvas=page.locator('canvas.edit'), box=await canvas.boundingBox();
 await canvas.click({position:{x:box.width*.3,y:box.height*.6}});
 await page.getByText('최신 클릭 반영됨',{exact:true}).waitFor({timeout:300000});
 const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/masks/'));
 await page.getByRole('button',{name:/^수정 저장/}).click();
 const p=await(await saved).json();assert.equal(p.masks[frame].status,'manual');assert.ok(p.masks[frame].valid);result.saved={frame,sha256:p.masks[frame].sha256,area:p.masks[frame].area};
 await page.waitForTimeout(1000);
 const confirmed=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/masks/'));
 await page.getByRole('button',{name:/확인 · 다음|수정 완료 · 다음/}).click();
 const q=await(await confirmed).json();assert.equal(q.masks[frame].status,'manual');assert.equal(q.masks[frame].sha256,p.masks[frame].sha256);
 result.manual_status_preserved=true;await page.waitForTimeout(1000);await page.screenshot({path:path.join(out,'corrected-next-photo.png')});result.status='PASS';
}catch(e){result.status='FAIL';result.error=String(e);await page.screenshot({path:path.join(out,'failure.png')});}
finally{result.console_errors=errors;if(errors.length){result.status='FAIL';result.error||='Browser console errors';}fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();if(result.status!=='PASS')process.exitCode=1;}
