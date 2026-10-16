import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  Box,
  Check,
  ChevronRight,
  FolderPlus,
  HardDrive,
  LoaderCircle,
  Monitor,
  Play,
  RefreshCw,
  Square,
  Upload,
  TriangleAlert,
} from "lucide-react";
import { api, post, asset, stages, titles, states } from "./api";
import type { Health, Point, Project, Stage } from "./api";
import { MaskEditor } from "./MaskEditor";
const MeshViewer = lazy(() => import("./MeshViewer"));
const maskStatus: Record<string, string> = {
  generated: "자동 생성 · 검토 전",
  approved: "수동 승인",
  manual: "직접 수정·승인",
  skipped: "검토 생략(자동 마스크)",
  invalid: "수정 필요",
};

export default function App() {
  const [showArchived, setShowArchived] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]),
    [id, setId] = useState<string | null>(
      new URLSearchParams(location.search).get("project"),
    ),
    [project, setProject] = useState<Project | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [stage, setStage] = useState<Stage>("import"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [name, setName] = useState(""),
    [selected, setSelected] = useState(""),
    [points, setPoints] = useState<Point[]>([]),
    [matching, setMatching] = useState("exhaustive"),
    [gpu, setGpu] = useState(0),
    [iterations, setIterations] = useState(30000),
    [resolution, setResolution] = useState(-1),
    [meshRes, setMeshRes] = useState(1024),
    [log, setLog] = useState(""),
    [uploading, setUploading] = useState(""),
    [preflight, setPreflight] = useState<{
      valid: boolean;
      images: number;
      failures: { name: string; reason: string }[];
    } | null>(null);
  const initialStage = useRef<string | null>(null);
  const dirty = useRef(false),
    currentID = useRef(id);
  currentID.current = id;
  const changeDirty = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);
  const refresh = useCallback(async () => {
    try {
      const listing = await api<Project[]>("/projects");
      setProjects(listing);
      if (currentID.current) {
        const p = await api<Project>("/projects/" + currentID.current);
        if (p.id === currentID.current) setProject(p);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 1500);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    let alive = true;
    const fetchHealth = () =>
      api<Health>("/health")
        .then((h) => alive && setHealth(h))
        .catch((e) => alive && setError(e.message));
    void fetchHealth();
    const timer = setInterval(() => void fetchHealth(), 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (id) {
      const events = new EventSource("/api/projects/" + id + "/events");
      events.onmessage = () => void refresh();
      return () => events.close();
    }
  }, [id, refresh]);
  useEffect(() => {
    if (project && initialStage.current !== project.id) {
      initialStage.current = project.id;
      setStage(stages.find((s) => project.stages[s] !== "completed") || "mesh");
    }
  }, [project?.id]);
  const active = project?.jobs?.find((j) => j.state === "running");
  const lastJob = active || project?.jobs?.[0];
  useEffect(() => {
    if (!id || !lastJob) {
      setLog("작업을 시작하면 실제 실행 기록이 여기에 표시됩니다.");
      return;
    }
    let alive = true;
    const fetchLog = () =>
      api<{ text: string }>(`/projects/${id}/logs/${lastJob.id}`)
        .then((r) => alive && setLog(r.text))
        .catch(() => {});
    void fetchLog();
    const timer = setInterval(() => void fetchLog(), 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id, lastJob?.id]);
  useEffect(() => {
    if (!project || project.stages.colmap !== "completed") return;
    const rows =
      project.colmap_report?.images.filter((i) => i.registered) || [];
    if (!selected || !rows.find((i) => i.name === selected)) {
      setSelected(rows[0]?.name || "");
      setPoints([]);
    }
  }, [project?.colmap_report, selected]);
  useEffect(() => {
    if (!id || stage !== "train") return;
    api<{
      valid: boolean;
      images: number;
      failures: { name: string; reason: string }[];
    }>(`/projects/${id}/preflight`)
      .then(setPreflight)
      .catch(() => setPreflight(null));
  }, [id, stage, project?.revision]);
  async function action(fn: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function guard() {
    return (
      !dirty.current ||
      window.confirm(
        "저장하지 않은 마스크 수정이 있습니다. 저장하지 않고 이동할까요?",
      )
    );
  }
  function open(p: Project) {
    if (!guard()) return;
    dirty.current = false;
    setId(p.id);
    setProject(p);
    setSelected("");
    setPoints([]);
    setError("");
    history.replaceState(null, "", "?project=" + p.id);
    const next = stages.find((s) => p.stages[s] !== "completed");
    setStage(next || "mesh");
  }
  function select(name: string) {
    if (!guard()) return;
    dirty.current = false;
    setSelected(name);
    setPoints([]);
  }
  const base = "/projects/" + id;
  async function create() {
    const p = await post<Project>("/projects", { name });
    setName("");
    open(p);
  }
  async function upload(files: FileList | File[] | null) {
    if (!files || !id) return;
    setBusy(true);
    setError("");
    const failures: string[] = [];
    try {
      const list = Array.from(files);
      for (let i = 0; i < list.length; i++) {
        setUploading(`사진을 불러오는 중 ${i + 1}/${list.length}`);
        const data = new FormData();
        data.append(
          "file",
          list[i],
          list[i].webkitRelativePath || list[i].name,
        );
        try {
          await api(base + "/images", { method: "POST", body: data });
        } catch (e) {
          failures.push(list[i].name + ": " + (e as Error).message);
        }
      }
      await refresh();
      if (failures.length) setError(failures.join("\n"));
    } finally {
      setBusy(false);
      setUploading("");
    }
  }
  async function job(which: string, confirmed = false, radius?: number) {
    await post(base + "/jobs/" + which, {
      gpu,
      reference: selected,
      points: points.map((p) => [p.x, p.y]),
      labels: points.map((p) => p.label),
      confirmed,
      iterations,
      mesh_res: meshRes,
      matching,
      resolution,
      radius,
    });
  }
  const rows = project?.colmap_report?.images.filter((i) => i.registered) || [];
  const index = rows.findIndex((i) => i.name === selected);
  function move(delta: number) {
    const next = rows[Math.max(0, Math.min(rows.length - 1, index + delta))];
    if (next) select(next.name);
  }
  const promptFingerprint = JSON.stringify(project?.prompt);
  useEffect(() => {
    if (project?.prompt?.reference === selected) {
      setPoints(
        project.prompt.points.map((point, i) => ({
          x: point[0],
          y: point[1],
          label: project.prompt!.labels[i],
        })),
      );
    }
  }, [selected, promptFingerprint]);
  const preview =
    project?.preview?.reference === selected ? project.preview.path : undefined;
  const mask = project?.masks[selected];
  const blocked = busy || !!active;
  const usable = project?.images.filter((i) => !i.duplicate_of).length || 0;
  return (
    <div className="studio-shell">
      <a className="skip-link" href="#main-content">
        작업 영역으로 건너뛰기
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            if (guard()) {
              setId(null);
              setProject(null);
              history.replaceState(null, "", "/");
            }
          }}
        >
          <Box size={29} />
          <span>
            Object-Aware<small>재구성 스튜디오</small>
          </span>
        </a>
        <button
          className="new-project"
          onClick={() => {
            if (guard()) {
              setId(null);
              setProject(null);
              history.replaceState(null, "", "/");
            }
          }}
        >
          <FolderPlus size={18} />새 프로젝트
        </button>
        <div className="sidebar-label">
          {showArchived ? "보관한 작업" : "최근 작업"}{" "}
          <button className="tiny" onClick={() => setShowArchived((v) => !v)}>
            {showArchived ? "최근 작업" : "보관함"}
          </button>
        </div>
        <div className="project-list">
          {projects
            .filter((p) => !!p.archived === showArchived)
            .map((p) => (
              <button
                className={id === p.id ? "chosen" : ""}
                key={p.id}
                onClick={() => open(p)}
              >
                <span>{p.name}</span>
                <ChevronRight size={15} />
              </button>
            ))}
        </div>
        {project && (
          <nav className="workflow" aria-label="재구성 단계">
            {stages.map((s, i) => (
              <button
                key={s}
                className={stage === s ? "selected" : ""}
                onClick={() => {
                  if (guard()) {
                    setStage(s);
                    dirty.current = false;
                  }
                }}
                aria-current={stage === s ? "step" : undefined}
              >
                <span className={"step-index " + project.stages[s]}>
                  {project.stages[s] === "completed" ? (
                    <Check size={15} />
                  ) : (
                    i + 1
                  )}
                </span>
                <span>
                  {titles[s]}
                  <small>{states[project.stages[s]]}</small>
                </span>
              </button>
            ))}
          </nav>
        )}
        <div className="machine">
          <Monitor size={16} />
          <div>
            {health?.gpus[0]?.name || "GPU 상태 확인 필요"}
            <small>이 컴퓨터에서 처리</small>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header>
          <div>
            <span className="breadcrumbs">
              내 작업 {project && <> / {project.name}</>}
            </span>
            <h1>{project ? titles[stage] : "사진에서 시작하는 객체 재구성"}</h1>
          </div>
          <div className="header-actions">
            {project && (
              <button
                disabled={blocked}
                onClick={() =>
                  void action(async () => {
                    await api(base + (project.archived ? "/restore" : ""), {
                      method: project.archived ? "POST" : "DELETE",
                    });
                  })
                }
              >
                {project.archived ? "작업 복원" : "프로젝트 보관"}
              </button>
            )}
            <span>
              <HardDrive size={15} />
              {health
                ? Math.floor(health.disk_free / 1024 ** 3) + " GB 여유"
                : "환경 확인 중"}
            </span>
            <button
              aria-label="환경 및 작업 새로고침"
              onClick={() =>
                void action(async () => {
                  setHealth(await api("/health"));
                  await refresh();
                })
              }
            >
              <RefreshCw size={17} />
            </button>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <TriangleAlert size={20} />
            <span>{error}</span>
            <button onClick={() => setError("")}>닫기</button>
          </div>
        )}
        <main id="main-content" tabIndex={-1}>
          {!project ? (
            <div className="welcome">
              <div className="welcome-mark">
                <Box size={52} />
              </div>
              <h2>하나의 대상, 여러 시점.</h2>
              <p>
                사진 불러오기부터 카메라 등록, 마스크 확인, 학습, 메시 추출까지
                <br />
                작업과 결과를 이 컴퓨터에 보관합니다.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void action(create);
                }}
              >
                <label htmlFor="project-name">프로젝트 이름</label>
                <div className="inline">
                  <input
                    id="project-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="예: 작업실의 작은 조각상"
                    maxLength={120}
                    required
                  />
                  <button className="primary" disabled={busy || !name.trim()}>
                    <FolderPlus size={17} />
                    프로젝트 만들기
                  </button>
                </div>
              </form>
              <div className="environment">
                <h3>시작 전 환경</h3>
                <p>
                  {health?.colmap
                    ? "COLMAP 사용 가능"
                    : "COLMAP 설치를 확인하세요."}
                </p>
                <p>
                  {health?.checkpoint_exists
                    ? "SAM 3.1 로컬 체크포인트 확인"
                    : "SAM 3.1 체크포인트가 필요합니다."}
                </p>
                <p>
                  {health?.gpus.length
                    ? "NVIDIA GPU " + health.gpus[0].name
                    : "NVIDIA GPU를 확인할 수 없습니다."}
                </p>
                <p className="muted">
                  환경 파일 확인과 실제 추론 검증은 별개입니다. 설치 검증은
                  scripts/doctor.sh로 다시 실행할 수 있습니다.
                </p>
              </div>
              <p className="license">
                연구·평가용 소프트웨어입니다. 원본 Gaussian-Splatting의 비상업적
                이용 조건과 SAM 라이선스가 적용됩니다.
              </p>
            </div>
          ) : (
            <>
              <div className="stage-summary">
                <span className={"status " + project.stages[stage]}>
                  {states[project.stages[stage]]}
                </span>
                <p>
                  {stage === "import"
                    ? "서로 충분히 겹치는 시점의 사진을 3장 이상 선택하세요."
                    : stage === "colmap"
                      ? "특징점 매칭과 카메라 등록은 각각 확인합니다. 등록된 한 그룹만 다음 단계로 보냅니다."
                      : stage === "sam"
                        ? "등록 사진에서 대상을 클릭하고 미리보기를 확인한 뒤 전파하세요."
                        : stage === "review"
                          ? "자동 마스크를 확인하고 필요한 부분을 수정하세요."
                          : stage === "train"
                            ? "마스크 검증 결과와 GPU를 확인한 뒤 학습을 시작하세요."
                            : "학습 결과에서 추출한 실제 삼각형 메시를 확인합니다."}
                </p>
              </div>
              {stage === "import" && (
                <>
                  <section
                    className="dropzone"
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (!blocked) void upload(e.dataTransfer.files);
                    }}
                  >
                    <Upload size={36} />
                    <h2>사진을 여기에 놓으세요</h2>
                    <p>
                      JPG · PNG · TIFF / 원본을 보존하고 방향을 바로잡습니다.
                    </p>
                    <div className="inline">
                      <label className="button primary">
                        사진 선택
                        <input
                          type="file"
                          multiple
                          accept="image/jpeg,image/png,image/tiff"
                          disabled={
                            blocked || project.stages.import === "completed"
                          }
                          onChange={(e) => void upload(e.target.files)}
                          hidden
                        />
                      </label>
                      <label className="button">
                        폴더 선택
                        <input
                          type="file"
                          multiple
                          {...{ webkitdirectory: "" }}
                          disabled={
                            blocked || project.stages.import === "completed"
                          }
                          onChange={(e) => void upload(e.target.files)}
                          hidden
                        />
                      </label>
                    </div>
                    {uploading && <p role="status">{uploading}</p>}
                  </section>
                  <div className="section-heading">
                    <h3>
                      불러온 사진 <span>{project.images.length}장</span>
                    </h3>
                    <span>
                      사용 가능 {usable}장 · 중복{" "}
                      {project.images.length - usable}장
                    </span>
                    <button
                      className="primary"
                      disabled={
                        blocked ||
                        usable < 2 ||
                        project.stages.import === "completed"
                      }
                      onClick={() =>
                        void action(async () => {
                          await post(base + "/import-complete");
                          setStage("colmap");
                        })
                      }
                    >
                      <Play size={16} />
                      불러오기 완료·재구성 시작
                    </button>
                  </div>
                  <div className="photo-grid">
                    {project.images.map((i) => (
                      <div className="photo-tile" key={i.name}>
                        <img
                          src={asset(project.id, i.thumbnail)}
                          alt={i.source_name}
                          loading="lazy"
                        />
                        <strong>{i.source_name}</strong>
                        <span>
                          {i.size.join(" × ")}{" "}
                          {i.duplicate_of ? "· 중복(재구성 제외)" : ""}
                        </span>
                        {i.advisories?.map((advice) => (
                          <small className="photo-advisory" key={advice}>
                            {advice}
                          </small>
                        ))}
                      </div>
                    ))}
                  </div>
                  {project.import_errors.length > 0 && (
                    <details>
                      <summary>
                        불러오지 못한 파일 {project.import_errors.length}개
                      </summary>
                      {project.import_errors.map((e, i) => (
                        <p key={i}>
                          {e.name}: {e.error}
                        </p>
                      ))}
                    </details>
                  )}
                </>
              )}
              {stage === "colmap" && (
                <>
                  <div className="metrics">
                    {[
                      ["전체 사진", project.colmap_report?.total ?? usable],
                      [
                        "검증된 매칭 사진",
                        project.colmap_report?.matched ?? "—",
                      ],
                      [
                        "등록된 카메라",
                        project.colmap_report?.registered ?? "—",
                      ],
                      [
                        "기하 검증된 사진 쌍",
                        project.colmap_report?.verified_pairs ?? "—",
                      ],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <span>{label}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  {project.colmap_report && (
                    <p>
                      선택된 재구성 그룹{" "}
                      {project.colmap_report.selected_component} /{" "}
                      {Object.keys(project.colmap_report.components).length}개
                      그룹
                    </p>
                  )}
                  {project.colmap_report && (
                    <label className="field">
                      재구성 그룹 선택
                      <select
                        disabled={blocked}
                        value={project.colmap_report.selected_component}
                        onChange={(e) =>
                          void action(() =>
                            post(base + "/jobs/colmap", {
                              component: e.target.value,
                            }),
                          )
                        }
                      >
                        {Object.entries(project.colmap_report.components).map(
                          ([key, names]) => (
                            <option key={key} value={key}>
                              그룹 {key} · 등록 사진 {names.length}장
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                  )}
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>사진</th>
                          <th>특징점</th>
                          <th>검증된 매칭</th>
                          <th>카메라 등록</th>
                        </tr>
                      </thead>
                      <tbody>
                        {project.colmap_report?.images.map((i) => (
                          <tr key={i.name}>
                            <td>{i.name}</td>
                            <td>{i.feature_count.toLocaleString()}</td>
                            <td>{i.has_verified_match ? "있음" : "없음"}</td>
                            <td>{i.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <label className="field">
                    사진 매칭 방식
                    <select
                      disabled={blocked}
                      value={matching}
                      onChange={(e) => setMatching(e.target.value)}
                    >
                      <option value="exhaustive">
                        전체 비교 (순서 없는 사진)
                      </option>
                      <option value="sequential">
                        인접 사진 비교 (순서대로 촬영한 사진)
                      </option>
                    </select>
                  </label>
                  <div className="actions">
                    <button
                      disabled={
                        blocked || project.stages.import !== "completed"
                      }
                      onClick={() => void action(() => job("colmap"))}
                    >
                      재구성 다시 실행
                    </button>
                    <button
                      disabled={
                        blocked || project.stages.colmap !== "completed"
                      }
                      className="primary"
                      onClick={() => setStage("sam")}
                    >
                      대상 마스크 만들기
                      <ArrowRight size={16} />
                    </button>
                  </div>
                </>
              )}
              {(stage === "sam" || stage === "review") &&
                (project.stages.colmap !== "completed" || !selected ? (
                  <div className="empty">
                    <TriangleAlert />
                    <h2>카메라 등록을 먼저 완료하세요.</h2>
                    <p>
                      등록된 사진과 왜곡 보정 결과가 있어야 마스크를 만들 수
                      있습니다.
                    </p>
                    <button onClick={() => setStage("colmap")}>
                      재구성 단계로 이동
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="mask-layout">
                      <div
                        className="thumbnail-strip"
                        aria-label="등록 사진 선택"
                      >
                        {rows.map((i, n) => (
                          <button
                            key={i.name}
                            className={selected === i.name ? "selected" : ""}
                            onClick={() => select(i.name)}
                          >
                            <img
                              src={asset(
                                project.id,
                                project.images.find(
                                  (photo) => photo.name === i.name,
                                )?.thumbnail ||
                                  project.scene + "/images/" + i.name,
                              )}
                              alt={`${n + 1}번 등록 사진`}
                              loading="lazy"
                            />
                            <span>
                              {n + 1}.{" "}
                              {project.masks[i.name]
                                ? maskStatus[project.masks[i.name].status]
                                : "대상 선택 전"}
                            </span>
                          </button>
                        ))}
                      </div>
                      <div className="editor-column">
                        <div className="section-heading">
                          <strong>{selected}</strong>
                          <span>
                            {index + 1} / {rows.length}
                          </span>
                          {mask && (
                            <span className="status">
                              {maskStatus[mask.status]}
                            </span>
                          )}
                        </div>
                        <MaskEditor
                          key={selected}
                          image={asset(
                            project.id,
                            project.scene + "/images/" + selected,
                          )}
                          mask={
                            preview
                              ? asset(project.id, preview)
                              : mask
                                ? asset(project.id, mask.path) +
                                  "?v=" +
                                  mask.sha256
                                : undefined
                          }
                          resetMask={
                            mask
                              ? asset(
                                  project.id,
                                  mask.generated_path || mask.path,
                                )
                              : undefined
                          }
                          points={points}
                          onPoints={setPoints}
                          disabled={blocked}
                          allowSave={Boolean(mask)}
                          onDirty={changeDirty}
                          onPreview={() => void action(() => job("preview"))}
                          onPrevious={() => move(-1)}
                          onNext={() => move(1)}
                          onSave={async (png) => {
                            await api(
                              base + "/masks/" + encodeURIComponent(selected),
                              {
                                method: "PUT",
                                body: JSON.stringify({ png, approve: true }),
                              },
                            );
                            await refresh();
                          }}
                        />
                        <div className="actions">
                          <button
                            onClick={() => move(-1)}
                            disabled={index <= 0}
                          >
                            <ArrowLeft size={16} />
                            이전
                          </button>
                          <button
                            onClick={() => move(1)}
                            disabled={index >= rows.length - 1}
                          >
                            다음
                            <ArrowRight size={16} />
                          </button>
                          <button
                            disabled={blocked || !mask?.valid}
                            onClick={() =>
                              void action(async () => {
                                await api(
                                  base +
                                    "/masks/" +
                                    encodeURIComponent(selected),
                                  {
                                    method: "PUT",
                                    body: JSON.stringify({ approve: true }),
                                  },
                                );
                                move(1);
                              })
                            }
                          >
                            승인하고 다음
                          </button>
                        </div>
                      </div>
                      <aside className="inspector">
                        <h3>선택한 대상</h3>
                        <p>
                          대상 내부를 클릭하세요. 배경은 Alt 클릭 또는 오른쪽
                          클릭으로 제외합니다.
                        </p>
                        <div className="prompt-list">
                          {points.map((p, i) => (
                            <div key={i}>
                              <span>
                                {p.label ? "대상 +" : "배경 −"} (
                                {Math.round(p.x)}, {Math.round(p.y)})
                              </span>
                              <button
                                aria-label={`${i + 1}번 클릭 삭제`}
                                onClick={() =>
                                  setPoints(points.filter((_, n) => n !== i))
                                }
                              >
                                삭제
                              </button>
                            </div>
                          ))}
                        </div>
                        <button
                          disabled={!points.length || blocked}
                          onClick={() => setPoints([])}
                        >
                          클릭 초기화
                        </button>
                        <button
                          className="primary"
                          disabled={
                            blocked || !points.some((p) => p.label === 1)
                          }
                          onClick={() => void action(() => job("preview"))}
                        >
                          SAM 3.1 미리보기
                        </button>
                        <button
                          className="primary"
                          disabled={blocked || !preview || !points.length}
                          onClick={() => {
                            if (
                              window.confirm(
                                "미리보기의 대상이 맞나요? 이 대상으로 등록 사진의 마스크를 전파합니다.",
                              )
                            )
                              void action(() => job("sam", true));
                          }}
                        >
                          대상 확인·전체 전파
                        </button>
                        <button
                          disabled={
                            blocked ||
                            !preview ||
                            !points.length ||
                            !Object.values(project.masks).some(
                              (m) =>
                                !["approved", "manual", "skipped"].includes(
                                  m.status,
                                ),
                            )
                          }
                          onClick={() => {
                            if (
                              window.confirm(
                                "미리보기의 대상으로 인접한 미검토 사진만 다시 전파할까요? 현재 사진 앞뒤 최대 2장씩이며 승인된 마스크는 보존합니다.",
                              )
                            )
                              void action(() => job("sam", true, 2));
                          }}
                        >
                          주변 미검토 사진만 전파
                        </button>
                        <p className="advisory">
                          시점이 크게 달라지거나 대상이 가려진 사진은 전파가
                          실패할 수 있습니다. 결과를 확인하세요.
                        </p>
                        {mask?.warnings?.map((w) => (
                          <p className="advisory" key={w}>
                            {w}
                          </p>
                        ))}
                        {mask?.error && <p className="error">{mask.error}</p>}
                        <h3>검토</h3>
                        <p>
                          {
                            Object.values(project.masks).filter((m) =>
                              ["approved", "manual", "skipped"].includes(
                                m.status,
                              ),
                            ).length
                          }{" "}
                          / {rows.length}장 확인 또는 생략
                        </p>
                        <button
                          disabled={
                            blocked || !Object.keys(project.masks).length
                          }
                          onClick={() => {
                            if (
                              window.confirm(
                                "남은 유효한 자동 마스크의 수동 검토를 모두 생략할까요? 누락·빈 마스크는 학습을 계속 차단합니다.",
                              )
                            )
                              void action(() =>
                                post(base + "/skip-review", {
                                  confirmed: true,
                                }),
                              );
                          }}
                        >
                          남은 검토 모두 건너뛰기
                        </button>
                        <button
                          className="primary"
                          disabled={
                            blocked || project.stages.review !== "completed"
                          }
                          onClick={() => setStage("train")}
                        >
                          학습 준비 확인
                          <ArrowRight size={16} />
                        </button>
                      </aside>
                    </div>
                  </>
                ))}
              {stage === "train" && (
                <div className="training-layout">
                  <section>
                    <h2>학습을 시작할 준비</h2>
                    <p>
                      원본 Object-Aware Loss와 2DGS의 학습 설정을 사용합니다.
                    </p>
                    <div className="metrics">
                      <div>
                        <span>등록 사진</span>
                        <strong>{rows.length}장</strong>
                      </div>
                      <div>
                        <span>마스크 검증</span>
                        <strong>
                          {preflight?.valid ? "통과" : "확인 필요"}
                        </strong>
                      </div>
                    </div>
                    <label className="field">
                      학습할 GPU
                      <select
                        value={gpu}
                        onChange={(e) => setGpu(+e.target.value)}
                      >
                        {health?.gpus.map((g) => (
                          <option value={g.index} key={g.index}>
                            {g.index}: {g.name} · {g.free_mb} / {g.total_mb} MB
                            여유
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      학습 반복 횟수
                      <input
                        type="number"
                        min="100"
                        max="100000"
                        step="100"
                        value={iterations}
                        onChange={(e) => setIterations(+e.target.value)}
                      />
                      <small>
                        기본값 30,000회. 짧은 실행은 동작 확인용이며 최종 품질을
                        보장하지 않습니다.
                      </small>
                    </label>
                    <label className="field">
                      학습 사진 해상도
                      <select
                        value={resolution}
                        onChange={(e) => setResolution(+e.target.value)}
                      >
                        <option value="-1">
                          자동 (원본 기본값, 최대 가로 1600px)
                        </option>
                        <option value="1">원본 크기 유지</option>
                        <option value="800">가로 800px (메모리 절약)</option>
                      </select>
                      <small>
                        사진과 마스크를 원본 학습 로더에서 함께 조정합니다.
                      </small>
                    </label>
                    <label className="field">
                      메시 추출 해상도
                      <select
                        value={meshRes}
                        onChange={(e) => setMeshRes(+e.target.value)}
                      >
                        <option value="1024">1024 (기본)</option>
                        <option value="512">512</option>
                        <option value="128">128 (동작 확인)</option>
                      </select>
                    </label>
                    <p className="license">
                      비상업적 연구·평가용 라이선스가 적용됩니다. 대상과
                      마스크를 확인한 뒤 시작하세요. 학습 완료 후 메시 추출은
                      자동 실행됩니다.
                    </p>
                    <button
                      className="primary large"
                      disabled={
                        blocked || !preflight?.valid || !health?.gpus.length
                      }
                      onClick={() => {
                        if (
                          window.confirm(
                            `${iterations.toLocaleString()}회 학습을 GPU ${gpu}에서 시작할까요? 대상과 마스크 검증을 확인했습니다.`,
                          )
                        )
                          void action(() => job("train", true));
                      }}
                    >
                      <Play size={18} />
                      학습 시작
                    </button>
                    {preflight?.failures.map((f) => (
                      <p className="error" key={f.name}>
                        {f.name}: {f.reason}
                      </p>
                    ))}
                  </section>
                  <aside className="training-notes">
                    <h3>원본 연구 방법</h3>
                    <p>마스크 내부 L1 손실</p>
                    <p>Alpha Polarization</p>
                    <p>ObjectMark Polarization·Pruning</p>
                    <p>기존 2DGS 기하 손실</p>
                    <hr />
                    <p>
                      학습 손실과 반복 횟수는 아래 실제 실행 기록에서 확인할 수
                      있습니다.
                    </p>
                    {project.training && (
                      <p>
                        저장된 가우시안{" "}
                        {project.training.gaussians.toLocaleString()}개 /{" "}
                        {project.training.iterations.toLocaleString()}회
                      </p>
                    )}
                  </aside>
                </div>
              )}
              {stage === "mesh" &&
                (project.stages.mesh === "completed" && project.mesh ? (
                  <>
                    <div className="section-heading">
                      <h2>추출된 삼각형 메시</h2>
                      <span>
                        정점 {project.mesh.vertices.toLocaleString()} · 삼각형{" "}
                        {project.mesh.triangles.toLocaleString()}
                      </span>
                      <a
                        className="button primary"
                        download="fuse_post.ply"
                        href={asset(
                          project.id,
                          project.mesh.path + "/fuse_post.ply",
                        )}
                      >
                        원본 PLY 내보내기
                      </a>
                      <a
                        className="button"
                        download="preview.glb"
                        href={asset(
                          project.id,
                          project.mesh.path + "/preview.glb",
                        )}
                      >
                        GLB 내보내기
                      </a>
                    </div>
                    <Suspense fallback={<p>3D 뷰어를 준비하고 있습니다…</p>}>
                      <MeshViewer
                        url={asset(
                          project.id,
                          project.mesh.path + "/preview.glb",
                        )}
                      />
                    </Suspense>
                    <p className="muted">
                      GLB는 검증된 미리보기 변환본입니다. 내보내기 도구에 따라
                      색상·재질 표현이 다를 수 있습니다.
                    </p>
                  </>
                ) : (
                  <div className="empty">
                    <Box size={44} />
                    <h2>메시 추출 결과를 기다리고 있습니다.</h2>
                    <p>
                      원본 학습이 끝나면 TSDF 추출을 자동 실행합니다. 실패한
                      경우 로그를 확인하고 다시 실행하세요.
                    </p>
                    <button
                      disabled={blocked || project.stages.train !== "completed"}
                      onClick={() => void action(() => job("mesh"))}
                    >
                      메시 추출 다시 실행
                    </button>
                  </div>
                ))}
            </>
          )}
        </main>
        {project && (
          <footer className="job-dock">
            <div className="job-heading" role="status" aria-live="polite">
              <span>
                {active ? (
                  <LoaderCircle size={17} className="spin" />
                ) : (
                  <Check size={17} />
                )}{" "}
                {active
                  ? "작업 실행 중"
                  : lastJob
                    ? states[lastJob.state]
                    : "실행 대기"}
              </span>
              <strong>
                {active?.message ||
                  lastJob?.message ||
                  "사진을 불러와 작업을 시작하세요."}
              </strong>
              {active?.total && (
                <progress max={active.total} value={active.current || 0} />
              )}
              <span>
                {active?.total
                  ? `${active.current ?? 0} / ${active.total}`
                  : ""}
              </span>
              {active && (
                <button
                  className="danger"
                  onClick={() => void action(() => post(base + "/cancel"))}
                >
                  <Square size={13} />
                  작업 중지
                </button>
              )}
            </div>
            <details open={!!active}>
              <summary>실제 실행 기록 · 프로젝트 파일 보관됨</summary>
              <div className="artifact-location">
                저장 폴더:{" "}
                <code>{project.project_path || "프로젝트 정보 확인 중"}</code>{" "}
                <a
                  href={asset(project.id, "manifest.json")}
                  download="manifest.json"
                >
                  작업 목록 내려받기
                </a>
              </div>
              <pre aria-label="실제 실행 로그">
                {log.replace(/\x1b\[[0-9;]*m/g, "").slice(-9000)}
              </pre>
            </details>
          </footer>
        )}
      </div>
    </div>
  );
}
