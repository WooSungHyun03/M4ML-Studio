import { useEffect, useState } from "react";
import {
  ArrowRight,
  Box,
  CircleCheck,
  CircleX,
  Eye,
  FolderOpen,
  FolderPlus,
  Info,
  Layers,
  Orbit,
  TriangleAlert,
  Camera,
  Image as ImageIcon,
  Cpu,
  Search,
} from "lucide-react";
import { api, post, stages, titles } from "./api";
import type { Health, Project } from "./api";
import { fmt } from "./context";
import { isDesktop, pickFolder } from "./desktop";

export interface FolderScan {
  path: string;
  name: string;
  existing_project?: string;
  images: {
    dir: string;
    count: number;
    bytes: number;
    sample_sizes: Record<string, number[]>;
  } | null;
  image_dirs: { dir: string; count: number }[];
  sparse: {
    path: string;
    valid: boolean;
    registered?: number;
    undistorted?: boolean;
    images_dir?: string;
    error?: string;
    note?: string;
    camera_models?: string[];
  }[];
  selected_sparse: string | null;
  camera: {
    registered: number;
    undistorted: boolean;
    points: number;
    camera_models: string[];
    images_found: number;
  } | null;
  masks: {
    dir: string;
    matched: number;
    expected: number;
    complete: boolean;
    missing: string[];
    problems: string[];
  } | null;
  training: {
    path: string;
    valid: boolean;
    iterations?: number[];
    checkpoints?: number[];
    dataset_match?: string;
    gaussians?: number;
    error?: string;
  }[];
  artifacts?: {
    path: string;
    kind: string;
    valid: boolean;
    modified?: number;
    error?: string;
    note?: string;
    vertices?: number;
    triangles?: number;
  }[];
  meshes: {
    path: string;
    valid: boolean;
    triangles?: number;
    vertices?: number;
    colors?: boolean | null;
    kind?: string;
  }[];
  recommendation: {
    stage: string | null;
    label: string | null;
    reasons: string[];
  };
  problems: string[];
}

function stageLabel(p: Project) {
  if (p.input_mode === "mesh") return ["3D 모델 보기", "ok"];
  const next = stages.find((s) => p.stages[s] !== "completed");
  if (!next) return ["완료", "ok"];
  const st = p.stages[next];
  if (st === "failed") return [`${titles[next]} 실패`, "err"];
  if (st === "running") return [`${titles[next]} 진행 중`, "acc"];
  if (st === "cancelled") return [`${titles[next]} 중단됨`, "warn"];
  return [`${titles[next]} 차례`, "t3"];
}

function Row({
  icon,
  label,
  ok,
  value,
  note,
}: {
  icon: React.ReactNode;
  label: string;
  ok: boolean | null;
  value: React.ReactNode;
  note?: React.ReactNode;
}) {
  return (
    <div className="scan-row">
      <span className="scan-ic">{icon}</span>
      <span className="t3">{label}</span>
      <span className="scan-val">
        {ok === true ? (
          <CircleCheck size={14} className="ok" />
        ) : ok === false ? (
          <CircleX size={14} className="t4" />
        ) : (
          <TriangleAlert size={13} className="warn" />
        )}
        <span>{value}</span>
      </span>
      {note && <span className="scan-note">{note}</span>}
    </div>
  );
}

/** Folder analysis result → "프로젝트 열기". No technical start-mode choice is asked. */
export function FolderAnalysis({
  scan,
  onOpen,
  onCancel,
  setError,
}: {
  scan: FolderScan;
  onOpen: (p: Project, reused: string[]) => void;
  onCancel: () => void;
  setError: (e: string) => void;
}) {
  const [name, setName] = useState(scan.name),
    [busy, setBusy] = useState(false),
    [sparse, setSparse] = useState(scan.selected_sparse || ""),
    [images, setImages] = useState(""),
    [masks, setMasks] = useState("");
  const [selectedArtifacts, setSelectedArtifacts] = useState<string[]>(() => {
    const all = scan.artifacts || [];
    return ["mesh", "gaussian"]
      .map((kind) => all.find((a) => a.valid && a.kind === kind)?.path)
      .filter((p): p is string => !!p);
  });
  const rec = scan.recommendation;
  const training = scan.training.filter((t) => t.valid);
  const matched = training.filter((t) => t.dataset_match === "yes");
  const mesh = scan.meshes.find((m) => m.valid);
  async function open() {
    setBusy(true);
    setError("");
    try {
      const r = await post<{
        project: Project;
        reused: string[];
        skipped: string[];
      }>("/projects/from-folder", {
        artifacts: selectedArtifacts,
        path: scan.path,
        name: name.trim() || scan.name,
        sparse: sparse && sparse !== scan.selected_sparse ? sparse : null,
        images: images || null,
        masks: masks || null,
      });
      onOpen(r.project, r.reused);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (scan.existing_project)
    return (
      <div className="analysis">
        <h2>이미 M4ML Studio 프로젝트입니다</h2>
        <p className="lead">
          이 폴더는 기존 프로젝트입니다. 저장된 진행 상태 그대로 엽니다.
        </p>
        <div className="row" style={{ marginTop: 16 }}>
          <button
            className="btn primary l"
            onClick={() =>
              void api<Project>("/projects/" + scan.existing_project).then(
                (p) => onOpen(p, []),
              )
            }
          >
            프로젝트 열기
            <ArrowRight size={15} />
          </button>
          <button className="btn l ghost" onClick={onCancel}>
            취소
          </button>
        </div>
      </div>
    );
  return (
    <div className="analysis">
      <div className="row" style={{ alignItems: "baseline" }}>
        <h2>폴더 분석 결과</h2>
        <span
          className="mono t3 ellip"
          style={{ fontSize: 12 }}
          title={scan.path}
        >
          {scan.path}
        </span>
      </div>
      <div className="scan-table">
        <Row
          icon={<ImageIcon size={14} />}
          label="이미지"
          ok={!!scan.images}
          value={scan.images ? `${fmt(scan.images.count)}장 확인` : "찾지 못함"}
          note={
            scan.images
              ? scan.images.dir +
                " · " +
                (scan.images.bytes / 1024 ** 2).toFixed(0) +
                " MB"
              : undefined
          }
        />
        <Row
          icon={<Camera size={14} />}
          label="카메라"
          ok={!!scan.camera}
          value={
            scan.camera
              ? `${fmt(scan.camera.registered)}장 등록`
              : "카메라 정합 결과 없음"
          }
          note={
            scan.camera
              ? scan.camera.undistorted
                ? "왜곡 보정됨 · 그대로 사용"
                : "가져올 때 렌즈 왜곡 보정만 실행"
              : "사진으로 카메라 정합을 실행합니다"
          }
        />
        <Row
          icon={<Layers size={14} />}
          label="마스크"
          ok={scan.masks ? scan.masks.complete || null : false}
          value={
            scan.masks
              ? `${fmt(scan.masks.matched)} / ${fmt(scan.masks.expected)}장 확인`
              : "없음"
          }
          note={
            scan.masks
              ? scan.masks.complete
                ? "모든 등록 사진에 대응"
                : "일부만 있어 객체 선택으로 다시 만듭니다"
              : undefined
          }
        />
        <Row
          icon={<Cpu size={14} />}
          label="학습 결과"
          ok={matched.length ? true : training.length ? null : false}
          value={
            matched.length
              ? matched[0].iterations?.length
                ? `${fmt(matched[0].iterations.at(-1))}회 학습 완료`
                : `저장 지점 ${fmt(matched[0].checkpoints?.at(-1))}회`
              : training.length
                ? "다른 데이터의 결과 (사용 안 함)"
                : "없음"
          }
          note={matched.length ? matched[0].path : undefined}
        />
        <Row
          icon={<Box size={14} />}
          label="3D 모델"
          ok={mesh ? true : false}
          value={
            mesh
              ? `${mesh.kind?.toUpperCase()} · ${mesh.triangles ? fmt(mesh.triangles) + " 삼각형" : "GLB"}`
              : "없음"
          }
          note={
            mesh
              ? `${mesh.path}${mesh.colors ? " · 정점 색상 있음" : mesh.colors === false ? " · 색상 없음" : ""}`
              : undefined
          }
        />
      </div>
      {!!scan.artifacts?.length && (
        <details open className="blk" style={{ marginTop: 12 }}>
          <summary>기존 3D 결과 선택 · 독립 결과로 가져오기</summary>
          <div style={{ maxHeight: 230, overflow: "auto", padding: 12 }}>
            {scan.artifacts.map((a) => (
              <label
                key={a.path}
                className="field"
                style={{ marginBottom: 10 }}
              >
                <span className="row">
                  <input
                    type="checkbox"
                    disabled={!a.valid}
                    checked={selectedArtifacts.includes(a.path)}
                    onChange={(e) =>
                      setSelectedArtifacts((current) =>
                        e.target.checked
                          ? [...current, a.path]
                          : current.filter((p) => p !== a.path),
                      )
                    }
                  />
                  <b>
                    {a.kind === "gaussian"
                      ? "Object-Aware Gaussian"
                      : a.kind === "mesh"
                        ? "메시"
                        : a.kind === "point_cloud"
                          ? "점 구름"
                          : a.kind === "unsupported"
                            ? "미지원 형식"
                            : "손상된 파일"}
                  </b>
                  <span className={a.valid ? "ok" : "warn"}>
                    {a.valid ? "검증됨" : "사용 불가"}
                  </span>
                </span>
                <span className="mono" style={{ overflowWrap: "anywhere" }}>
                  {a.path}
                </span>
                <small>
                  {a.modified
                    ? new Date(a.modified * 1000).toLocaleString("ko-KR")
                    : ""}{" "}
                  {a.error || a.note || ""}
                </small>
              </label>
            ))}
          </div>
          <p className="hint">
            기존 결과를 열어도 현재 사진의 학습 완료 상태로 간주하지 않습니다.
          </p>
        </details>
      )}
      {rec.stage ? (
        <div className="callout ok" style={{ marginTop: 14 }}>
          <ArrowRight size={16} />
          <span>
            <b>추천 시작 단계: {rec.label}</b>
            <br />
            {rec.reasons.join(" ")}
          </span>
        </div>
      ) : null}
      {scan.problems.length > 0 && (
        <div className="callout warn" style={{ marginTop: 10 }}>
          <TriangleAlert size={15} />
          <span>
            {scan.problems.slice(0, 6).map((p) => (
              <span key={p} style={{ display: "block" }}>
                {p}
              </span>
            ))}
          </span>
        </div>
      )}
      {rec.stage && (
        <>
          <label className="field" style={{ marginTop: 16, maxWidth: 520 }}>
            프로젝트 이름
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </label>
          <details className="advanced">
            <summary>고급: 사용할 데이터 직접 지정</summary>
            <div className="col" style={{ marginTop: 10, maxWidth: 620 }}>
              {scan.sparse.length > 1 && (
                <label className="field">
                  카메라 정합 결과
                  <select
                    value={sparse}
                    onChange={(e) => setSparse(e.target.value)}
                  >
                    {scan.sparse
                      .filter((s) => s.valid)
                      .map((s) => (
                        <option key={s.path} value={s.path}>
                          {s.path} · {s.registered}장
                          {s.undistorted ? " · 왜곡 보정됨" : ""}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              {scan.image_dirs.length > 1 && (
                <label className="field">
                  사진 폴더
                  <select
                    value={images}
                    onChange={(e) => setImages(e.target.value)}
                  >
                    <option value="">자동 ({scan.images?.dir})</option>
                    {scan.image_dirs.map((d) => (
                      <option key={d.dir} value={d.dir}>
                        {d.dir} · {d.count}장
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="field">
                마스크 폴더 (폴더 안 상대 경로)
                <input value={masks} placeholder={scan.masks?.dir || "예: mask"} onChange={(e) => setMasks(e.target.value)} />
              </label>
              <p className="hint">
                원본 폴더의 파일은 수정하거나 삭제하지 않습니다. 검증을 통과한
                데이터만 프로젝트로 복사합니다.
              </p>
            </div>
          </details>
        </>
      )}
      <div className="row" style={{ marginTop: 18 }}>
        <button className="btn primary l" disabled={busy || !rec.stage} onClick={() => void open()}>
          {busy ? <span className="spinner" /> : <FolderOpen size={15} />}
          {busy ? "데이터를 검증하고 가져오는 중…" : "프로젝트 열기"}
        </button>
        <button className="btn l ghost" disabled={busy} onClick={onCancel}>
          다른 폴더 선택
        </button>
      </div>
    </div>
  );
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
  const [scan, setScan] = useState<FolderScan | null>(null),
    [scanning, setScanning] = useState(false),
    [archived, setArchived] = useState(false),
    [query, setQuery] = useState(""),
    [opened, setOpened] = useState<string[] | null>(null);
  const gpu = health?.gpus[0];
  useEffect(() => {
    // menu / shortcut requests from the shell (파일 › 새 프로젝트, 프로젝트 열기)
    const n = () => void choose(false),
      o = () => void choose(true);
    window.addEventListener("m4ml:new-project", n);
    window.addEventListener("m4ml:open-project", o);
    return () => {
      window.removeEventListener("m4ml:new-project", n);
      window.removeEventListener("m4ml:open-project", o);
    };
  });
  async function choose(existing = false) {
    const path = await pickFolder(
      existing
        ? "기존 프로젝트 또는 작업 폴더 열기"
        : "새 프로젝트: 작업할 폴더 선택",
    );
    if (!path) return;
    setScanning(true);
    setError("");
    try {
      setScan(await post<FolderScan>("/scan-folder", { path }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setScanning(false);
    }
  }
  const check = (ok: boolean | undefined, warn = false) =>
    ok ? (
      <CircleCheck size={15} className="ok" />
    ) : warn ? (
      <TriangleAlert size={15} className="warn" />
    ) : (
      <CircleX size={15} className="err" />
    );
  const list = projects.filter(
    (p) =>
      !!p.archived === archived &&
      (!query || p.name.toLowerCase().includes(query.toLowerCase())),
  );
  return (
    <div className="welcome">
      <aside className="side">
        <div className="plate">
          <img src="/m4ml-logo.png" alt="Media for Machine Laboratory" />
        </div>
        <div className="pname">M4ML Studio</div>
        <div className="ptag">사진으로 3D 모델 만들기</div>
        <div className="ver">v{health?.version || "—"} · 로컬 GPU 처리</div>
        <div className="col" style={{ marginTop: 20 }}>
          <button
            className="btn primary l"
            style={{ justifyContent: "flex-start" }}
            disabled={scanning}
            onClick={() => void choose(false)}
          >
            <FolderPlus size={16} />새 프로젝트 · 폴더 선택
            <span className="sp" />
            <span className="kbd">Ctrl+N</span>
          </button>
          <button
            className="btn l"
            style={{ justifyContent: "flex-start" }}
            disabled={scanning}
            onClick={() => void choose(true)}
          >
            <FolderOpen size={16} />
            기존 프로젝트 열기
            <span className="sp" />
            <span className="kbd">Ctrl+O</span>
          </button>
        </div>
        <div className="syscheck">
          <div className="h">
            <span className="grow">실행 환경 점검</span>
            {health &&
              (gpu && health.runtime_status?.available ? (
                <span className="badge ok">사용 가능</span>
              ) : (
                <span className="badge warn">확인 필요</span>
              ))}
          </div>
          <div className="sc">
            {check(!!gpu)}
            <span className="k">처리 장치</span>
            <span>
              {gpu ? gpu.name : "NVIDIA GPU 없음"}
              <span className="n">
                {gpu
                  ? `GPU 메모리 ${(gpu.total_mb / 1024).toFixed(0)} GB · 드라이버 ${gpu.driver || "—"}`
                  : "3D 모델 보기만 사용할 수 있습니다"}
              </span>
            </span>
          </div>
          <div className="sc">
            {check(health?.runtime_status?.available)}
            <span className="k">재구성 엔진</span>
            <span>
              {health?.runtime_status?.available ? "준비됨" : "확인 필요"}
              <span className="n">
                {health?.runtime_status?.available
                  ? "GPU 처리 런타임 확인"
                  : health?.runtime_status?.error || "설정 › 처리 장치 확인"}
              </span>
            </span>
          </div>
          <div className="sc">
            {check(health?.checkpoint_exists)}
            <span className="k">객체 선택</span>
            <span>
              {health?.checkpoint_exists
                ? "모델 파일 확인됨"
                : "모델 파일 필요"}
              <span className="n">
                {health?.checkpoint_exists
                  ? "첫 클릭 때 불러옵니다"
                  : "설정 › 모델 파일에서 경로를 지정하세요"}
              </span>
            </span>
          </div>
          <div className="sc">
            {check(
              health?.colmap?.available && health?.colmap?.gpu,
              health?.colmap?.available,
            )}
            <span className="k">카메라 정합</span>
            <span>
              {health?.colmap?.available
                ? health.colmap.gpu
                  ? "GPU 가속 사용 가능"
                  : "CPU만 사용 가능"
                : "엔진 없음"}
              <span className="n">
                {health?.colmap?.gpu
                  ? "특징점 추출·매칭을 GPU로 처리"
                  : "설치 폴더에서 ./scripts/build_colmap.sh 실행"}
              </span>
            </span>
          </div>
          <div className="sc">
            {check(!!health && health.disk_free > 10 * 1024 ** 3, true)}
            <span className="k">저장 공간</span>
            <span>
              {health
                ? `${Math.floor(health.disk_free / 1024 ** 3)} GB 여유`
                : "확인 중"}
            </span>
          </div>
        </div>
        <p className="license">
          연구·평가용 소프트웨어입니다. 포함된 재구성 기술의 비상업적 이용
          조건이 적용됩니다. 자세한 내용은 도움말 › 라이선스를 확인하세요.
        </p>
      </aside>
      <section className="content">
        {scanning ? (
          <div className="empty">
            <span className="spinner" style={{ width: 30, height: 30 }} />
            <h2>폴더를 분석하고 있습니다</h2>
            <p>
              사진, 카메라 정합 결과, 마스크, 학습 결과, 3D 모델을 찾고 각각
              검증합니다.
            </p>
          </div>
        ) : scan ? (
          <FolderAnalysis
            scan={scan}
            setError={setError}
            onCancel={() => {
              setScan(null);
              void choose(false);
            }}
            onOpen={(p, reused) => {
              setOpened(reused);
              setScan(null);
              onOpen(p);
            }}
          />
        ) : (
          <>
            <h2>시작하기</h2>
            <div className="lead">
              작업할 폴더를 선택하면 들어 있는 데이터를 자동으로 분석해 이어서
              할 단계부터 시작합니다.
            </div>
            {opened && (
              <div className="callout ok" style={{ marginTop: 12 }}>
                <CircleCheck size={15} />
                <span>{opened.join(" · ")}</span>
              </div>
            )}
            <div className="start-actions">
              <button className="start-tile" onClick={() => void choose(false)}>
                <FolderPlus size={28} className="acc" />
                <b>새 프로젝트</b>
                <span>
                  사진 폴더나 이전 작업 폴더를 선택하세요. 사진만 있으면 카메라
                  정합부터, 카메라 정합·마스크·학습 결과가 있으면 그 다음
                  단계부터 이어서 진행합니다.
                </span>
              </button>
              <button className="start-tile" onClick={() => void choose(true)}>
                <FolderOpen size={28} className="t2" />
                <b>기존 프로젝트 열기</b>
                <span>
                  최근 프로젝트는 아래 목록에서 바로 열 수 있습니다. 다른 위치의
                  프로젝트나 결과 폴더는 여기서 선택하세요.
                </span>
              </button>
            </div>
            {!isDesktop() && (
              <p className="hint" style={{ marginTop: 8 }}>
                <Info size={12} /> 브라우저 개발 모드에서는 폴더 경로를 직접
                입력합니다. 일반 실행(M4ML Studio 앱)에서는 폴더 선택 창이
                열립니다.
              </p>
            )}
            <div className="recent-h">
              <h3>{archived ? "보관한 프로젝트" : "최근 프로젝트"}</h3>
              <span className="count">{list.length}</span>
              <span className="sp" />
              <label className="search" style={{ width: 220 }}>
                <Search size={13} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="프로젝트 검색" aria-label="프로젝트 검색" />
              </label>
              <button
                className="btn ghost s"
                onClick={() => setArchived((v) => !v)}
              >
                {archived ? "최근 프로젝트" : "보관함"}
              </button>
            </div>
            {list.length ? (
              <div className="tbl">
                <div className="tr th">
                  <span>이름</span>
                  <span>진행 상태</span>
                  <span>마지막 작업</span>
                  <span />
                </div>
                {list.map((p) => {
                  const [label, cls] = stageLabel(p);
                  return (
                    <button className="tr" key={p.id} onClick={() => onOpen(p)}>
                      <span>
                        <div className="nm ellip">{p.name}</div>
                        <div className="sub">
                          {p.images?.length
                            ? `사진 ${p.images.length}장`
                            : p.input_mode === "mesh"
                              ? "3D 모델"
                              : "—"}
                        </div>
                      </span>
                      <span className={cls}>{label}</span>
                      <span className="t2">
                        {new Date(p.updated || p.created).toLocaleDateString(
                          "ko-KR",
                          {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          },
                        )}
                      </span>
                      <ArrowRight size={15} className="t3" />
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="empty" style={{ padding: 24 }}>
                <Box size={36} className="ill" />
                <h2>
                  {archived
                    ? "보관한 프로젝트가 없습니다"
                    : "아직 프로젝트가 없습니다"}
                </h2>
                <p>새 프로젝트에서 작업할 폴더를 선택하세요.</p>
              </div>
            )}
            <div
              className="tbl"
              style={{
                marginTop: 22,
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(0,1fr))",
              }}
            >
              {[
                [
                  Orbit,
                  "객체 주위를 두 높이로 한 바퀴씩",
                  "60–120장 정도, 비슷한 거리에서 촬영하면 정합이 안정적입니다.",
                ],
                [
                  Layers,
                  "이웃 사진과 60% 이상 겹치게",
                  "시점 간격이 크면 카메라 정합과 마스크 전파가 실패하기 쉽습니다.",
                ],
                [
                  Eye,
                  "흐림과 강한 반사 줄이기",
                  "셔터 속도를 확보하고, 광택 표면은 확산광에서 찍어 주세요.",
                ],
              ].map(([Icon, t, d], i) => {
                const I = Icon as typeof Camera;
                return (
                  <div
                    key={i}
                    style={{
                      padding: "14px 16px",
                      borderLeft: i ? "1px solid var(--line)" : 0,
                      display: "grid",
                      gridTemplateColumns: "22px 1fr",
                      gap: "3px 10px",
                    }}
                  >
                    <I size={17} className="t2" />
                    <b style={{ fontSize: 12.5 }}>{t as string}</b>
                    <span className="hint" style={{ gridColumn: 2 }}>
                      {d as string}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
