// Real WebGL controls, themes, layout and native exports through the visible UI.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
const {chromium}=createRequire((process.env.PW_DIR||process.cwd())+'/')('playwright');
const [url,out='evidence/viewer-regression']=process.argv.slice(2);
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1366,height:768},acceptDownloads:true});
const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>m.type()==='error'&&errors.push(m.text()));
const digest=b=>createHash('sha256').update(b).digest('hex');
const result={};
try{
 await page.goto(url);
 await page.getByText('색상 표시 중',{exact:true}).waitFor({timeout:120000});
 const canvas=page.locator('.three-host canvas');
 result.color_meshes=await page.locator('.three-host').getAttribute('data-color-meshes');
 assert.ok(Number(result.color_meshes)>0);
 const before=digest(await canvas.screenshot());
 const box=await canvas.boundingBox();
 await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.6,{steps:12});await page.mouse.up();await page.waitForTimeout(700);
 assert.notEqual(digest(await canvas.screenshot()),before,'Actual orbit must change rendered pixels');
 await page.getByRole('button',{name:'이동',exact:true}).click();
 const beforePan=digest(await canvas.screenshot());
 await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.6,box.y+box.height*.45,{steps:8});await page.mouse.up();await page.waitForTimeout(700);
 assert.notEqual(digest(await canvas.screenshot()),beforePan,'Actual pan must change rendered pixels');
 const beforeZoom=digest(await canvas.screenshot());
 await page.mouse.wheel(0,-300);await page.waitForTimeout(700);
 assert.notEqual(digest(await canvas.screenshot()),beforeZoom,'Actual zoom must change rendered pixels');
 for(const mode of ['형상','와이어프레임','색상 + 선','정점 색상','직교','원근']) await page.getByRole('button',{name:mode,exact:true}).click();
 await page.getByTitle('객체에 맞춤 (F)',{exact:true}).click();
 await page.getByTitle('카메라 초기화',{exact:true}).click();
 await page.screenshot({path:path.join(out,'viewer-1366.png')});
 result.controls=['orbit','pan','zoom','fit','reset','color','shaded','wire','colorwire','orthographic','perspective'];
 await page.getByRole('button',{name:'설정',exact:true}).click();
 await page.getByRole('button',{name:'밝은 테마',exact:true}).click();
 assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
 await page.getByRole('tab',{name:'고급 정보',exact:true}).click();
 await page.getByText('GPU 처리 런타임',{exact:true}).waitFor();
 await page.screenshot({path:path.join(out,'advanced-light.png')});
 await page.getByRole('button',{name:'닫기',exact:true}).click();
 await page.screenshot({path:path.join(out,'viewer-light-1366.png')});
 await page.setViewportSize({width:1920,height:1080});await page.waitForTimeout(500);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await page.screenshot({path:path.join(out,'viewer-1920.png')});
 result.downloads={};
 for(const ext of ['PLY','GLB']){
  const waiting=page.waitForEvent('download');await page.getByRole('link',{name:new RegExp(ext+' 내보내기')}).first().click();
  const dl=await waiting;const target=path.join(out,'export.'+ext.toLowerCase());await dl.saveAs(target);const data=fs.readFileSync(target);
  result.downloads[ext]={bytes:data.length,sha256:digest(data)};
 }
 result.status='PASS';
}catch(e){result.status='FAIL';result.error=String(e);await page.screenshot({path:path.join(out,'failure.png')});}
finally{result.console_errors=errors;if(errors.length){result.status='FAIL';result.error ||= 'Browser console errors';}fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));await browser.close();console.log(JSON.stringify(result));if(result.status!=='PASS')process.exitCode=1;}
