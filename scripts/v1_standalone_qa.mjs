import fs from 'node:fs';import {createRequire} from 'node:module';
const {chromium}=createRequire((process.env.PW_DIR||process.cwd())+'/')('playwright');
const [base,project,out]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME||undefined,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1600,height:1000}}),views=[];
const report={checks:[],errors:[]};const check=(name,ok,detail)=>{report.checks.push({name,ok:!!ok,detail});if(!ok)throw Error(name)};
page.on('request',r=>{if(r.url().endsWith('/live-render/frame'))views.push(r.postDataJSON().view)});page.on('pageerror',e=>report.errors.push(String(e)));
try{
 await page.goto(base+'/?project='+project);await page.waitForSelector('.live-frame[data-state="rendering"]',{timeout:120000});await page.waitForFunction(()=>Number(document.querySelector('.live-surface')?.dataset.frames)>0);
 check('independent source label replaces fake zero training iteration',await page.getByText('독립 파일',{exact:true}).count()>0);
 await page.getByRole('button',{name:'시점 초기화',exact:true}).click();await page.waitForTimeout(900);const initial=views.at(-1);
 const r=await page.locator('.live-surface').boundingBox();await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();await page.mouse.move(r.x+r.width/2+100,r.y+r.height/2+65,{steps:8});await page.mouse.up();await page.waitForTimeout(600);
 check('standalone native camera actually orbits',JSON.stringify(initial)!==JSON.stringify(views.at(-1)));
 await page.getByRole('button',{name:'시점 초기화',exact:true}).click();await page.waitForTimeout(900);const reset=views.at(-1);const error=Math.max(...initial.map((v,i)=>Math.abs(v-reset[i])));
 check('camera-free reset restores initial native matrix',error<1e-6,{max_error:error});
 await page.screenshot({path:out+'/standalone-reset.png'});check('no page exceptions',report.errors.length===0,report.errors);report.passed=true;
}catch(e){report.error=String(e)}finally{
 await page.evaluate(async project=>{const{token}=await(await fetch('/api/session')).json();await fetch('/api/projects/'+project+'/live-render/stop',{method:'POST',headers:{'x-studio-token':token}})},project).catch(()=>{});
 await browser.close();fs.writeFileSync(out+'/result.json',JSON.stringify(report,null,2));
}console.log(JSON.stringify(report,null,2));process.exitCode=report.passed?0:1;
