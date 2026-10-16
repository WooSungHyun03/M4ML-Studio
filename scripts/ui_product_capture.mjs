// Capture actual completed project stages; contains no mock UI or invented metrics.
import {createRequire} from 'node:module';
import fs from 'node:fs';import path from 'node:path';
const {chromium}=createRequire((process.env.PW_DIR||process.cwd())+'/')('playwright');
const [url,out]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>m.type()==='error'&&errors.push(m.text()));
const captures=[];
try{
 for(const [w,h] of [[1366,768],[1920,1080]]){
  await page.setViewportSize({width:w,height:h});await page.goto(url);await page.locator('.nav').waitFor({timeout:60000});
  for(const [name,label] of [['images','이미지'],['camera','카메라 정합'],['mask','마스크 생성'],['review','마스크 검토'],['train','3D 재구성'],['mesh','3D 모델 보기']]){
   await page.locator('.nav button',{hasText:label}).click();await page.waitForTimeout(name==='mesh'?2000:1000);
   const file=`${name}-${w}.png`;await page.screenshot({path:path.join(out,file)});captures.push(file);
  }
  await page.getByRole('button',{name:'설정',exact:true}).click();await page.getByRole('button',{name:'밝은 테마',exact:true}).click();await page.getByRole('button',{name:'닫기',exact:true}).click();
  await page.screenshot({path:path.join(out,`mesh-light-${w}.png`)});
  await page.getByRole('button',{name:'설정',exact:true}).click();await page.getByRole('button',{name:'어두운 테마',exact:true}).click();await page.getByRole('button',{name:'닫기',exact:true}).click();
 }
 await page.goto(new URL('/',url).href);await page.getByText('새 프로젝트 시작',{exact:true}).waitFor();await page.screenshot({path:path.join(out,'home-1920.png')});
 await page.setViewportSize({width:1366,height:768});await page.waitForTimeout(500);await page.screenshot({path:path.join(out,'home-1366.png')});
}finally{await browser.close();fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({captures,console_errors:errors,status:errors.length?'FAIL':'PASS'},null,2));if(errors.length)process.exitCode=1;}
