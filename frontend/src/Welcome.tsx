import { useState } from "react";
import { ArrowRight, Box, CircleCheck, FolderOpen, Images, Layers, TriangleAlert, CircleX, Camera, Orbit, Eye } from "lucide-react";
import { api, post, stages, titles } from "./api";
import type { Health, Project } from "./api";

const MODES = [
  ["images", "A", "처음부터 시작", "사진만 있어요. 카메라 정합부터 3D 모델까지 모든 단계를 진행합니다.", ["여러 시점에서 찍은 사진 30장 이상", "JPG · PNG · TIFF"], 0],
  ["colmap", "B", "카메라 정합 결과 가져오기", "카메라 위치 추정을 이미 끝냈어요. 마스크 생성부터 시작합니다.", ["원본 이미지 폴더", "카메라 정합 결과 폴더 (COLMAP 형식 sparse 모델)"], 2],
  ["colmap_masks", "C", "정합 결과 + 마스크 가져오기", "객체 마스크까지 준비됐어요. 데이터를 검사한 뒤 바로 학습합니다.", ["원본 이미지 · 카메라 정합 결과", "이진 마스크 폴더 (사진과 같은 파일 이름)"], 4],
] as const;
const FLOW = ["이미지", "정합", "마스크", "검토", "재구성", "모델"];

function stageLabel(p: Project) {
  if (p.input_mode === "mesh") return ["3D 모델 보기", "ok"];
  const next = stages.find((s) => p.stages[s] !== "completed");
  if (!next) return ["완료", "ok"];
  const state = p.stages[next];
  if (state === "failed") return [`${titles[next]} 실패`, "err"];
  if (state === "running") return [`${titles[next]} 진행 중`, "acc"];
  if (state === "cancelled") return [`${titles[next]} 중단됨`, "warn"];
  return [`${titles[next]} 대기`, "t3"];
}

export function Welcome({
  health,
  projects,
  onOpen,
  setError,
}: {
  health: Health | null;
  projects: Project[];
  onOpen: (p: Project) => void;
  setError: (e: string) => void;
}) {
  const [mode, setMode] = useState("images"),
    [name, setName] = useState(""),
    [busy, setBusy] = useState(false),
    [archived, setArchived] = useState(false);
  const gpu = health?.gpus[0];
  async function create() {
    setBusy(true);
    try {
      onOpen(await post<Project>("/projects", { name, input_mode: mode }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openMesh(f: File) {
    setBusy(true);
    try {
      const p = await post<Project>("/projects", { name: f.name, input_mode: "mesh" });
      const data = new FormData();
      data.append("file", f);
      onOpen(await api<Project>(`/projects/${p.id}/mesh-file`, { method: "POST", body: data }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const check = (ok: boolean | undefined, warn = false) =>
    ok ? <CircleCheck size={15} className="ok" /> : warn ? <TriangleAlert size={15} className="warn" /> : <CircleX size={15} className="err" />;
  const list = projects.filter((p) => !!p.archived === archived);
  return (
    <div className="welcome">
      <aside className="side">
        <div className="plate"><img src="/m4ml-logo.png" alt="Media for Machine Laboratory" /></div>
        <div className="pname">M4ML Studio</div>
        <div className="ptag">멀티뷰 사진에서 원하는 객체만 컬러 3D 모델로</div>
        <div className="ver">v{health?.version || "—"} · 로컬 GPU 처리</div>
        <div className="col" style={{ marginTop: 20 }}>
          <button className="btn primary l" style={{ justifyContent: "flex-start" }} onClick={() => document.getElementById("project-name")?.focus()}>
            <Images size={16} />새 프로젝트
          </button>
          <label className="btn l" style={{ justifyContent: "flex-start" }} aria-disabled={busy}>
            <FolderOpen size={16} />완성된 3D 모델 열기 (PLY · GLB)
            <input type="file" accept=".ply,.glb" hidden disabled={busy} onChange={(e) => e.target.files?.[0] && void openMesh(e.target.files[0])} />
          </label>
        </div>
        <div className="syscheck">
          <div className="h"><span className="grow">실행 환경 점검</span>{health && (gpu && health.runtime_status?.available ? <span className="badge ok">사용 가능</span> : <span className="badge warn">확인 필요</span>)}</div>
          <div className="sc">{check(!!gpu)}<span className="k">처리 장치</span><span>{gpu ? gpu.name : "NVIDIA GPU 없음"}<span className="n">{gpu ? `GPU 메모리 ${(gpu.total_mb / 1024).toFixed(0)} GB · 드라이버 ${gpu.driver || "—"}` : "3D 모델 보기만 사용할 수 있습니다"}</span></span></div>
          <div className="sc">{check(health?.runtime_status?.available)}<span className="k">재구성 엔진</span><span>{health?.runtime_status?.available ? "준비됨" : "확인 필요"}<span className="n">{health?.runtime_status?.available ? "GPU 처리 런타임 확인" : health?.runtime_status?.error || "설정 › 처리 장치 확인"}</span></span></div>
          <div className="sc">{check(health?.checkpoint_exists)}<span className="k">객체 선택</span><span>{health?.checkpoint_exists ? "모델 파일 확인됨" : "모델 파일 필요"}<span className="n">{health?.checkpoint_exists ? "첫 클릭 때 불러옵니다" : "설정 › 고급 정보에서 경로를 지정하세요"}</span></span></div>
          <div className="sc">{check(health?.colmap?.available && health?.colmap?.gpu, health?.colmap?.available)}<span className="k">카메라 정합</span><span>{health?.colmap?.available ? (health.colmap.gpu ? "GPU 가속 사용 가능" : "CPU만 사용 가능") : "엔진 없음"}<span className="n">{health?.colmap?.gpu ? "특징점 추출·매칭을 GPU로 처리" : "./scripts/build_colmap.sh 로 GPU 엔진 설치"}</span></span></div>
          <div className="sc">{check(!!health && health.disk_free > 10 * 1024 ** 3, true)}<span className="k">저장 공간</span><span>{health ? `${Math.floor(health.disk_free / 1024 ** 3)} GB 여유` : "확인 중"}</span></div>
        </div>
        <p className="license">연구·평가용 소프트웨어입니다. 포함된 재구성 기술의 비상업적 이용 조건이 적용됩니다. 자세한 내용은 설정 › 라이선스를 확인하세요.</p>
      </aside>
      <section className="content">
        <h2>새 프로젝트 시작</h2>
        <div className="lead">가지고 있는 데이터에 맞는 시작 방식을 고르세요. 각 방식은 필요한 단계만 진행합니다.</div>
        <div className="modes" role="group" aria-label="프로젝트 시작 방식">
          {MODES.map(([key, letter, title, desc, need, start]) => (
            <button key={key} className="mode" aria-pressed={mode === key} onClick={() => setMode(key)}>
              <div className="top"><span className="letter">{letter}</span><h3>{title}</h3></div>
              <p>{desc}</p>
              <div className="need col" style={{ gap: 4 }}>{need.map((n) => <span key={n}>· {n}</span>)}</div>
              <div className="flow">{FLOW.map((f, i) => <i key={f} className={i < start ? "skip" : i === start ? "start" : ""}>{f}</i>)}</div>
            </button>
          ))}
        </div>
        <form className="create-form" onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <label className="field">
            프로젝트 이름
            <input id="project-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 도자기 화병 재구성" maxLength={120} required />
          </label>
          <button className="btn primary l" disabled={busy || !name.trim()}>프로젝트 만들기<ArrowRight size={15} /></button>
        </form>
        <div className="recent-h">
          <h3>{archived ? "보관한 프로젝트" : "최근 프로젝트"}</h3><span className="count">{list.length}</span><span className="sp" />
          <button className="btn ghost s" onClick={() => setArchived((v) => !v)}>{archived ? "최근 프로젝트 보기" : "보관함 보기"}</button>
        </div>
        {list.length ? (
          <div className="tbl">
            <div className="tr th"><span>이름</span><span>진행 상태</span><span>마지막 작업</span><span /></div>
            {list.map((p) => {
              const [label, cls] = stageLabel(p);
              return (
                <button className="tr" key={p.id} onClick={() => onOpen(p)}>
                  <span><div className="nm ellip">{p.name}</div><div className="sub">{p.images?.length ? `${p.images.length}장 · ` : ""}{p.input_mode === "colmap" ? "정합 결과 가져옴" : p.input_mode === "colmap_masks" ? "정합+마스크 가져옴" : p.input_mode === "mesh" ? "3D 모델" : "처음부터"}</div></span>
                  <span className={cls}>{label}</span>
                  <span className="t2">{new Date(p.updated || p.created).toLocaleDateString("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                  <ArrowRight size={15} className="t3" />
                </button>
              );
            })}
          </div>
        ) : (
          <div className="empty" style={{ padding: 24 }}>
            <Box size={36} className="ill" />
            <h2>{archived ? "보관한 프로젝트가 없습니다" : "아직 프로젝트가 없습니다"}</h2>
            <p>사진으로 새 프로젝트를 만들거나, 이미 만든 카메라 정합·마스크 결과를 가져와 시작하세요.</p>
          </div>
        )}
        <div className="tbl" style={{ marginTop: 22, display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
          {[
            [Orbit, "객체 주위를 두 높이로 한 바퀴씩", "60–120장 정도, 비슷한 거리에서 촬영하면 정합이 안정적입니다."],
            [Layers, "이웃 사진과 60% 이상 겹치게", "시점 간격이 크면 카메라 정합과 마스크 전파가 실패하기 쉽습니다."],
            [Eye, "흐림과 강한 반사 줄이기", "셔터 속도를 확보하고, 광택 표면은 확산광에서 찍어 주세요."],
          ].map(([Icon, t, d], i) => {
            const I = Icon as typeof Camera;
            return (
              <div key={i} style={{ padding: "14px 16px", borderLeft: i ? "1px solid var(--line)" : 0, display: "grid", gridTemplateColumns: "22px 1fr", gap: "3px 10px" }}>
                <I size={17} className="t2" /><b style={{ fontSize: 12.5 }}>{t as string}</b><span className="hint" style={{ gridColumn: 2 }}>{d as string}</span>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
