// Actual imported-data state transitions against the real API; no mocked React state.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const {chromium}=createRequire((process.env.PW_DIR||process.cwd())+'/')('playwright');
const [base,fixture,output]=process.argv.slice(2); fs.mkdirSync(output,{recursive:false});
const token=(await (await fetch(base+'/api/session')).json()).token;
const headers={'x-studio-token':token};
async function post(p,b){const r=await fetch(base+'/api'+p,{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(b)});if(!r.ok)throw Error(await r.text());return r.json()}
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name)):[path.join(dir,e.name)])}
const browser=await chromium.launch({executablePath:process.env.CHROME||undefined,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const results=[];
try{
for(const mode of ['colmap','colmap_masks']){
 const p=await post('/projects',{name:'가져오기 상태 전환 검증 '+mode,input_mode:mode});
 for(const f of files(fixture).filter(f=>/\.(bin|txt|png|jpe?g)$/i.test(f)&&!f.includes('/stereo/'))){const data=new FormData();data.append('file',new Blob([fs.readFileSync(f)]),'fixture/'+path.relative(fixture,f));const r=await fetch(`${base}/api/projects/${p.id}/import-files`,{method:'POST',headers,body:data});if(!r.ok)throw Error(await r.text())}
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 await page.goto(`${base}/?project=${p.id}`);await page.waitForSelector('.import-workspace');
 const result=await post(`/projects/${p.id}/commit-import`,{with_masks:mode==='colmap_masks',skip_review:true});
 await page.waitForTimeout(3500);
 const item={mode,id:p.id,committed:result.committed,grid:await page.locator('.grid').count(),editor:await page.locator('.editor-body').count(),body:(await page.locator('body').innerText()).slice(0,700),errors};
 if(!item.editor)item.recovery=await page.evaluate(()=>{const logo=document.querySelector('.recovery-screen .brand-logo')?.getBoundingClientRect();const buttons=[...document.querySelectorAll('.recovery-screen .actions a,.recovery-screen .actions button')].map(x=>x.getBoundingClientRect());return {logoWidth:logo?.width,actionsVisible:buttons.length===2&&buttons.every(b=>b.y>=0&&b.bottom<=innerHeight&&b.x>=0&&b.right<=innerWidth)}});
 item.pass=item.committed&&item.grid>0&&item.editor>0&&errors.length===0;results.push(item);
 await page.screenshot({path:output+'/'+mode+'.png'});await page.close();
}
}finally{await browser.close();fs.writeFileSync(output+'/result.json',JSON.stringify({pass:results.length===2&&results.every(x=>x.pass),results},null,2));}
console.log(JSON.stringify(results));process.exitCode=results.length===2&&results.every(x=>x.pass)?0:1;
