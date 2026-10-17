import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "./api";

export type DialogKind = "guide" | "manual" | "troubleshooting" | "shortcuts" | "about" | "update" | "saveas" | null;

/** Minimal, safe Markdown → React (headings, paragraphs, lists, code, tables, bold). */
function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  const inline = (s: string, k: string) =>
    s.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("`") ? <code key={k + i}>{part.slice(1, -1)}</code> : part.startsWith("**") ? <b key={k + i}>{part.slice(2, -2)}</b> : part,
    );
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith("```")) {
      const code: string[] = [];
      while (++i < lines.length && !lines[i].startsWith("```")) code.push(lines[i]);
      blocks.push(<pre key={i} className="md-code">{code.join("\n")}</pre>);
    } else if (/^#{1,4} /.test(l)) {
      const level = l.match(/^#+/)![0].length;
      const H = (["h2", "h3", "h4", "h5"] as const)[level - 1];
      blocks.push(<H key={i}>{inline(l.replace(/^#+ /, ""), "h" + i)}</H>);
    } else if (/^\s*[-*] /.test(l)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*] /.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*] /, ""));
      i--;
      blocks.push(<ul key={i}>{items.map((it, k) => <li key={k}>{inline(it, `l${i}-${k}`)}</li>)}</ul>);
    } else if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[\s:-|]+\|$/.test(lines[i])) rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
        i++;
      }
      i--;
      blocks.push(
        <table key={i}>
          <thead><tr>{rows[0].map((c, k) => <th key={k}>{inline(c, "th" + k)}</th>)}</tr></thead>
          <tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c, `td${k}${j}`)}</td>)}</tr>)}</tbody>
        </table>,
      );
    } else if (l.trim()) blocks.push(<p key={i}>{inline(l, "p" + i)}</p>);
  }
  return <div className="md">{blocks}</div>;
}

export function Dialog({ kind, onClose, onSaveAs, projectName }: { kind: DialogKind; onClose: () => void; onSaveAs?: (name: string) => void; projectName?: string }) {
  const [md, setMd] = useState(""),
    [about, setAbout] = useState<Record<string, unknown> | null>(null),
    [name, setName] = useState(projectName ? projectName + " 사본" : "");
  useEffect(() => {
    const doc = kind === "guide" ? "quickstart" : kind === "manual" ? "guide" : kind === "troubleshooting" ? "troubleshooting" : kind === "shortcuts" ? "shortcuts" : null;
    if (doc) api<{ markdown: string }>("/help/" + doc).then((r) => setMd(r.markdown)).catch((e) => setMd(String(e.message)));
    if (kind === "about" || kind === "update") api<Record<string, unknown>>("/about").then(setAbout).catch(() => {});
  }, [kind]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  if (!kind) return null;
  const title = { guide: "시작 가이드", manual: "사용 설명서", troubleshooting: "오류 해결 가이드", shortcuts: "단축키", about: "M4ML Studio 정보", update: "업데이트 확인", saveas: "다른 이름으로 저장" }[kind];
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={"modal" + (kind === "about" || kind === "update" || kind === "saveas" ? " small" : "")} role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-h">
          <h2>{title}</h2>
          <span className="sp" />
          <button className="icon-btn" aria-label="닫기" onClick={onClose}><X size={15} /></button>
        </div>
        <div className="modal-body">
          {kind === "about" ? (
            <div className="col" style={{ alignItems: "flex-start", gap: 12 }}>
              <div className="plate" style={{ width: 300 }}><img src="/m4ml-logo.png" alt="Media for Machine Laboratory" /></div>
              <b style={{ fontSize: 20 }}>M4ML Studio</b>
              <div className="kv" style={{ width: "100%" }}>
                <span>버전</span><span>{String(about?.version ?? "—")}</span>
                <span>배포 형태</span><span>{about?.channel === "internal-research" ? "내부 연구용 빌드" : about?.channel ? "비상업적 연구·평가용 릴리스" : "소스 실행 (개발)"}</span>
                <span>소스</span><span className="mono">{String(about?.source_commit ?? about?.release ?? "—")}</span>
                <span>실행 방식</span><span>{about?.desktop ? "데스크톱 앱" : "브라우저 개발 모드"}</span>
                <span>데이터 폴더</span><span className="mono">{String(about?.data ?? "—")}</span>
              </div>
              <p className="hint">Media for Machine Laboratory. 연구·평가용 소프트웨어이며 포함된 재구성 기술의 비상업적 이용 조건이 적용됩니다. 엔진 이름과 라이선스는 설정 › 고급 정보 / 라이선스에서 확인할 수 있습니다.</p>
            </div>
          ) : kind === "update" ? (
            <div className="col">
              <p>현재 버전: <b>{String(about?.version ?? "—")}</b></p>
              <p className="hint">M4ML Studio는 인터넷 연결 없이 동작하며 자동으로 외부 서버에 접속하지 않습니다. 새 버전은 설치 패키지로 배포되며, 새 패키지에서 <code>./scripts/install.sh</code>를 실행하면 기존 프로젝트와 설정을 보존한 채 나란히 설치됩니다.</p>
            </div>
          ) : kind === "saveas" ? (
            <form className="col" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSaveAs?.(name.trim()); }}>
              <p className="hint">현재 프로젝트의 모든 파일과 진행 상태를 새 이름의 프로젝트로 복사합니다. 원래 프로젝트는 그대로 남습니다.</p>
              <label className="field">새 프로젝트 이름<input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
              <div className="row"><button className="btn primary" disabled={!name.trim()}>복사해서 저장</button><button type="button" className="btn ghost" onClick={onClose}>취소</button></div>
            </form>
          ) : md ? (
            <Markdown text={md} />
          ) : (
            <span className="spinner" />
          )}
        </div>
      </div>
    </div>
  );
}
