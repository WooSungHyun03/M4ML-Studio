import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {buildSync} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const root = fileURLToPath(new URL('..', import.meta.url));

async function load(entry, name) {
  const dir = fs.mkdtempSync(path.join(root, '.platform-test-'));
  const file = path.join(dir, name + '.mjs');
  buildSync({entryPoints: [path.join(root, entry)], outfile: file, bundle: true, platform: 'node',
    mainFields: ['module', 'main'], format: 'esm', jsx: 'automatic', external: ['react', 'react/*']});
  try { return await import(pathToFileURL(file)); } finally { fs.rmSync(dir, {recursive: true, force: true}); }
}
function shell(kind) {
  const meta = kind === 'web' ? {getAttribute: (k) => (k === 'content' ? 'web' : null)} : null;
  globalThis.window = {__M4ML_DESKTOP__: kind === 'desktop', addEventListener() {}, removeEventListener() {}};
  globalThis.document = {cookie: 'other=1; __Host-m4ml_csrf=abc%2Bdef', querySelector: (q) => (q.includes('m4ml-platform') ? meta : null)};
}

test('platform detection and web capabilities', async () => {
  const {platform, capabilities, csrfToken} = await load('src/platform.ts', 'platform');
  shell('desktop'); assert.equal(platform(), 'desktop');
  shell('dev'); assert.equal(platform(), 'dev');
  shell('web'); assert.equal(platform(), 'web');
  const web = capabilities('web');
  for (const [key, value] of Object.entries(web)) assert.equal(value, false, key);
  assert.equal(capabilities('desktop').openPaths, true);
  assert.equal(capabilities('dev').serverFolders, true);
  assert.equal(csrfToken(), 'abc+def');
  assert.equal(csrfToken('x=1'), '');
});

test('web requests never ask for the backend token', async () => {
  const {writeHeaders, api} = await load('src/api.ts', 'api');
  shell('web');
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url, headers: new Headers(options.headers)});
    return new Response('{}', {status: 200, headers: {'Content-Type': 'application/json'}});
  };
  assert.deepEqual(await writeHeaders(), {'x-csrf-token': 'abc+def'});
  await api('/projects', {method: 'POST', body: '{}'});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/projects');
  assert.equal(calls[0].headers.get('x-csrf-token'), 'abc+def');
  assert.equal(calls[0].headers.get('x-studio-token'), null);
  assert.ok(!calls.some((c) => c.url === '/api/session'));
});

test('hidden menu items leave no dangling separators', async () => {
  const {visibleItems} = await load('src/MenuBar.tsx', 'menubar');
  const items = visibleItems([{separator: true}, {label: 'a'}, {separator: true}, {label: 'b', hidden: true},
    {separator: true}, {label: 'c'}, {separator: true}, {label: 'd', hidden: true}]);
  assert.deepEqual(items.map((i) => i.label || '-'), ['a', '-', 'c']);
});

test('web start screen offers uploads, not server folders', async () => {
  shell('web');
  const {Welcome} = await load('src/Welcome.tsx', 'welcome-web');
  const html = renderToStaticMarkup(React.createElement(Welcome, {health: null, projects: [], onOpen() {}, setError() {}}));
  assert.match(html, /사진 파일이나 사진 폴더를 올려/);
  assert.doesNotMatch(html, /기존 프로젝트 열기|브라우저 개발 모드|폴더를 선택하면/);
  shell('dev');
  const dev = renderToStaticMarkup(React.createElement(Welcome, {health: null, projects: [], onOpen() {}, setError() {}}));
  assert.match(dev, /기존 프로젝트 열기/);
});
