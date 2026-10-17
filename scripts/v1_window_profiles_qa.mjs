import fs from 'node:fs';
import {connectQt} from './qt_cdp.mjs';
const [debug,project,out,commands]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const q=await connectQt(debug),report={checks:[]};
const check=(name,ok,detail)=>{report.checks.push({name,ok:!!ok,detail});if(!ok)throw Error(name)};
async function resize(width,height){const sequence=Date.now();fs.writeFileSync(commands,JSON.stringify({size:[width,height],sequence}));await q.sleep(800);const a=JSON.parse(fs.readFileSync(commands.replace(/\.[^.]+$/,'')+'.ack.json'));check('actual native '+width+'x'+height,a.request.sequence===sequence&&a.size[0]===width&&a.size[1]===height,a)}
try{
 await q.navigate('/?project='+project,'.stage-tabs');await q.click('.stage-tab','3D 모델');await q.click('[aria-label="3D 표시 방식"] button','메시');await q.waitFor('Number(document.querySelector(".three-host")?.dataset.colorMeshes)>0');
 for(const [w,h]of [[1366,768],[1920,1080]]){
  await resize(w,h);await q.sleep(300);
  const d=await q.evaluate(`(()=>{const f=document.querySelector('.mesh-frame').getBoundingClientRect(),t=document.querySelector('.tool-col').getBoundingClientRect();return {viewport:[innerWidth,innerHeight],body:[document.body.scrollWidth,document.body.clientWidth],frame:[f.top,f.bottom],tools:[t.top,t.bottom],colorMeshes:document.querySelector('.three-host').dataset.colorMeshes}})()`);
  check('bounded color mesh workspace '+w,d.body[0]<=d.viewport[0]&&d.tools[0]>=d.frame[0]&&d.tools[1]<=d.frame[1]+1&&+d.colorMeshes>0,d);
  const s=await q.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(out+'/'+w+'x'+h+'.png',Buffer.from(s.data,'base64'));
 }
 check('no native JS exceptions',q.errors.length===0,q.errors);report.passed=true;
}catch(e){report.error=String(e)}finally{q.close();fs.writeFileSync(out+'/result.json',JSON.stringify(report,null,2))}
console.log(JSON.stringify(report,null,2));process.exitCode=report.passed?0:1;
