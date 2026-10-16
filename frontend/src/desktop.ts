// Native desktop bridge (PySide6 shell, studio/desktop/app.py). In the developer browser
// mode the same functions fall back to browser behaviour so the UI stays usable.
interface Bridge {
  pickFolder(title: string, cb: (path: string) => void): void;
  pickFile(title: string, filters: string, cb: (path: string) => void): void;
  openPath(path: string, cb: (ok: boolean) => void): void;
  logFolder(cb: (path: string) => void): void;
  toggleFullScreen(): void;
  setTitle(title: string): void;
  quit(): void;
  info(cb: (json: string) => void): void;
}
declare global {
  interface Window {
    __M4ML_DESKTOP__?: boolean;
    m4mlReady?: Promise<Bridge>;
  }
}

export const isDesktop = () => !!window.__M4ML_DESKTOP__;
const bridge = async () => (window.m4mlReady ? await window.m4mlReady : null);

export async function pickFolder(title: string): Promise<string | null> {
  const b = await bridge();
  if (b) return new Promise((res) => b.pickFolder(title, (p) => res(p || null)));
  // Developer browser mode: no native dialog is available to web pages.
  const p = window.prompt(`${title}\n(브라우저 개발 모드: 폴더의 전체 경로를 입력하세요)`);
  return p?.trim() || null;
}

export async function openPath(path: string): Promise<boolean> {
  const b = await bridge();
  if (b) return new Promise((res) => b.openPath(path, res));
  await navigator.clipboard?.writeText(path).catch(() => {});
  window.alert(`폴더 경로를 클립보드에 복사했습니다.\n${path}`);
  return false;
}

export async function logFolder(): Promise<string | null> {
  const b = await bridge();
  return b ? new Promise((res) => b.logFolder(res)) : null;
}

export async function toggleFullScreen() {
  const b = await bridge();
  if (b) return b.toggleFullScreen();
  if (document.fullscreenElement) await document.exitFullscreen();
  else await document.documentElement.requestFullscreen();
}

export async function setTitle(title: string) {
  document.title = title ? `${title} — M4ML Studio` : "M4ML Studio";
  (await bridge())?.setTitle(title);
}

export async function quitApp(): Promise<boolean> {
  const b = await bridge();
  if (b) {
    b.quit();
    return true;
  }
  return false;
}
