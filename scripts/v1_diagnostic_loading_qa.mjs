// Delay the real health request; never fabricate a GPU response.
import fs from 'node:fs';
import {connectQt} from './qt_cdp.mjs';
const [debug,out]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const q=await connectQt(debug),paused=[],report={checks:[],scope:'actual Qt UI, temporarily paused real health request; real response resumed'};
const check=(name,ok,detail)=>{report.checks.push({name,ok:!!ok,detail});if(!ok)throw Error(name)};
async function shot(name){const r=await q.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(out+'/'+name+'.png',Buffer.from(r.data,'base64'))}
q.onEvent(e=>{if(e.method==='Fetch.requestPaused')paused.push(e.params.requestId)});
try{
 await q.send('Fetch.enable',{patterns:[{urlPattern:'*/api/health',requestStage:'Request'}]});
 await q.navigate('/','.syscheck');
 await q.waitFor('document.querySelector(".syscheck").innerText.includes("NVIDIA GPU 확인 중")');
 const pending=await q.evaluate('document.querySelector(".syscheck").innerText');
 check('pending diagnosis never claims missing GPU/engine/model',!pending.includes('GPU 없음')&&!pending.includes('엔진 없음')&&!pending.includes('모델 파일 필요'),pending);
 check('real health request paused',paused.length>0);await shot('pending-real-diagnosis');
 for(const requestId of paused){try{await q.send('Fetch.continueRequest',{requestId})}catch(error){if(!String(error).includes('Invalid InterceptionId'))throw error;report.cancelledOldDocumentRequests=(report.cancelledOldDocumentRequests||0)+1}}await q.send('Fetch.disable');
 await q.waitFor('document.querySelector(".syscheck").innerText.includes("RTX 4080") && document.querySelector(".syscheck").innerText.includes("사용 가능")',60000);
 check('actual NVIDIA response replaces pending state',true,await q.evaluate('document.querySelector(".syscheck").innerText'));await shot('actual-hardware-diagnosed');
 check('no native JS exceptions',q.errors.length===0,q.errors);report.passed=true;
}catch(e){report.error=String(e)}finally{await q.send('Fetch.disable').catch(()=>{});q.close();fs.writeFileSync(out+'/result.json',JSON.stringify(report,null,2))}
console.log(JSON.stringify(report,null,2));process.exitCode=report.passed?0:1;
