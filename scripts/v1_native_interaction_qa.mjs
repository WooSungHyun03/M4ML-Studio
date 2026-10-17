// Actual native menus, Save As, positive/negative inference and brush save.
// Operates only on a newly copied test project; source mask bytes are audited.
import fs from 'node:fs';
import {connectQt} from './qt_cdp.mjs';
const [debug,source,out]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const q=await connectQt(debug),report={checks:[],source};
const check=(name,ok,detail)=>{report.checks.push({name,ok:!!ok,detail});if(!ok)throw Error(name)};
const get=id=>q.evaluate(`fetch('/api/projects/'+${JSON.stringify(id)}).then(r=>r.json())`);
async function shot(name){const s=await q.send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(out+'/'+name+'.png',Buffer.from(s.data,'base64'))}
async function clickPixel(x,y){const b=await q.evaluate(`(()=>{const e=document.querySelector('.image-sheet'),i=e.querySelector('img'),r=e.getBoundingClientRect();return {x:r.x+r.width*${x}/i.naturalWidth,y:r.y+r.height*${y}/i.naturalHeight}})()`);
 for(const type of ['mousePressed','mouseReleased'])await q.send('Input.dispatchMouseEvent',{type,...b,button:'left',buttons:type==='mousePressed'?1:0,clickCount:1});}
async function fill(selector,text){await q.click(selector);await q.send('Input.dispatchKeyEvent',{type:'keyDown',key:'a',code:'KeyA',modifiers:2,windowsVirtualKeyCode:65});await q.send('Input.dispatchKeyEvent',{type:'keyUp',key:'a',code:'KeyA',modifiers:2,windowsVirtualKeyCode:65});await q.send('Input.insertText',{text})}
try{
 await q.waitFor('!!window.m4mlReady');await q.navigate('/?project='+source,'.stage-tabs');
 for(const name of ['시작 가이드','사용 설명서','단축키 목록','오류 해결 가이드','업데이트 확인','M4ML Studio 정보']){
   await q.click('.menubar button','도움말');await q.click('.menu-pop .menu-item',name);await q.waitFor('!!document.querySelector(".modal")');await q.sleep(500);
   check('native help action '+name,await q.evaluate('document.querySelector(".modal-body").innerText.length>40'));
   await shot('help-'+name);await q.click('.modal [aria-label="닫기"]');
 }
 const original=await get(source);const signature=JSON.stringify(original.masks);
 await q.click('.menubar button','파일');await q.click('.menu-pop .menu-item','다른 이름으로 저장');await q.waitFor('!!document.querySelector(".modal input")');
 await fill('.modal input','v1 실제 마스크 클릭 검증');await q.click('.modal button','복사해서 저장');
 await q.waitFor(`new URLSearchParams(location.search).get('project')!==${JSON.stringify(source)} && !document.querySelector('.modal')`,120000);
 const copy=await q.evaluate('new URLSearchParams(location.search).get("project")');report.copy=copy;check('Save As creates another real project',!!copy&&copy!==source);
 await q.click('.stage-tab','마스크 검토');await q.waitFor('document.querySelector(".image-sheet img")?.naturalWidth>0 && !document.querySelector("[aria-label=지우개]").disabled',60000);
 const before=(await get(copy)).live_prompt?.prompt_revision||0;
 await q.click('[aria-label="마스크 편집 도구"] button','');await clickPixel(380,349);
 await q.waitFor(`fetch('/api/projects/${copy}').then(r=>r.json()).then(p=>p.live_prompt?.status==='ready' && p.preview?.prompt_revision>${before})`,180000);
 let current=await get(copy);const positive=current.preview.prompt_revision;check('positive click automatically infers real mask',current.preview.project_id===copy,current.preview);
 await q.click('[aria-label^="제외 클릭"]');await clickPixel(868,300);
 await q.waitFor(`fetch('/api/projects/${copy}').then(r=>r.json()).then(p=>p.live_prompt?.status==='ready' && p.preview?.prompt_revision>${positive})`,120000);
 current=await get(copy);check('negative click automatically re-infers latest revision',current.live_prompt.labels.at(-1)===0,current.preview);
 const ref=current.preview.reference;const originalHash=original.masks[ref].sha256;
 await q.waitFor(`!document.querySelector('[aria-label="지우개"]').disabled`);await q.click('[aria-label="지우개"]');await clickPixel(380,349);
 await q.click('[aria-label="마스크 편집 도구"] [aria-label="실행 취소"]');await q.click('[aria-label="마스크 편집 도구"] [aria-label="다시 실행"]');
 await q.click('.mask-editor button','수정 저장');await q.waitFor(`fetch('/api/projects/${copy}').then(r=>r.json()).then(p=>p.masks[${JSON.stringify(ref)}]?.status==='manual' && p.masks[${JSON.stringify(ref)}]?.sha256!==${JSON.stringify(originalHash)})`);
 const edited=await get(copy);check('native erase/undo/redo/manual save changes binary mask',edited.masks[ref].sha256!==originalHash && edited.masks[ref].area<current.preview.area,edited.masks[ref]);
 check('source project masks preserved',JSON.stringify((await get(source)).masks)===signature);
 const actual=await q.evaluate(`(async()=>{const p=await(await fetch('/api/projects/${source}')).json(),r=await fetch('/api/projects/${source}/files/'+p.masks[${JSON.stringify(ref)}].path),b=await r.arrayBuffer();return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b))).map(v=>v.toString(16).padStart(2,'0')).join('')})()`);
 check('source original mask bytes unchanged',actual===originalHash);await shot('native-manual-save');
 const first=await q.evaluate('document.querySelector(".image-sheet img").src');await q.click('.action-bar button','다음');await q.waitFor(`document.querySelector('.image-sheet img').src!==${JSON.stringify(first)}`);await q.click('.action-bar button','이전');await q.waitFor(`document.querySelector('.image-sheet img').src===${JSON.stringify(first)}`);check('native previous/next review controls change and restore actual image',true);
 check('no native JS exceptions',q.errors.length===0,q.errors);report.passed=true;
}catch(e){report.error=String(e);await shot('failure').catch(()=>{})}
finally{q.close();fs.writeFileSync(out+'/result.json',JSON.stringify(report,null,2))}
console.log(JSON.stringify(report,null,2));process.exitCode=report.passed?0:1;
