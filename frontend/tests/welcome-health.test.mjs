import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {buildSync} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const root=fileURLToPath(new URL('..',import.meta.url));
test('welcome distinguishes unfinished hardware diagnosis from confirmed absence',async()=>{
 const previousWindow=globalThis.window;globalThis.window={__M4ML_DESKTOP__:false};
 const dir=fs.mkdtempSync(path.join(root,'.health-test-'));
 try{
  const file=path.join(dir,'welcome.mjs');
  buildSync({entryPoints:[path.join(root,'src/Welcome.tsx')],outfile:file,bundle:true,platform:'node',mainFields:['module','main'],format:'esm',jsx:'automatic',external:['react','react/*']});
  const {Welcome}=await import(pathToFileURL(file));
  const render=health=>renderToStaticMarkup(React.createElement(Welcome,{health,projects:[],onOpen(){},setError(){}}));
  const pending=render(null);
  assert.match(pending,/진단 중/);assert.match(pending,/NVIDIA GPU 확인 중/);
  assert.doesNotMatch(pending,/NVIDIA GPU 없음|엔진 없음|모델 파일 필요/);
  const absent=render({gpus:[],runtime_status:{available:false},checkpoint_exists:false,colmap:{available:false},disk_free:0,version:'1.0.0'});
  assert.match(absent,/NVIDIA GPU 없음/);assert.match(absent,/엔진 없음/);assert.match(absent,/모델 파일 필요/);
 }finally{fs.rmSync(dir,{recursive:true,force:true});if(previousWindow===undefined)delete globalThis.window;else globalThis.window=previousWindow}
});
