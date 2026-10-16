import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, CircleCheck, FolderPlus, ImagePlus, Info, Maximize2, Play, Search, Trash2, TriangleAlert, Upload, CircleX, X } from "lucide-react";
import { api, asset, post } from "../api";
import type { Project } from "../api";
import type { StageCtx } from "../context";
import { InspectorPortal } from "../dock";
import { ImportPanel } from "../ImportPanel";

export function ImagesStage({ ctx, toolbar }: { ctx: StageCtx; toolbar: (node: React.ReactNode) => React.ReactNode }) {
  const { project, base, blocked } = ctx;
  const [uploading, setUploading] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [filter, setFilter] = useState<"all" | "warn" | "err" | "reg" | "unreg">("all"),
    [query, setQuery] = useState(""),
    [sort, setSort] = useState<"import" | "name" | "size">("import"),
    [picked, setPicked] = useState<Set<string>>(new Set()),
    [anchor, setAnchor] = useState<string | null>(null),
    [zoom, setZoom] = useState<string | null>(null),
    [over, setOver] = useState(false);
  const locked = project.stages.import === "completed";
  const usable = project.images.filter((i) => !i.duplicate_of).length;
  const warnings = project.images.filter((i) => i.advisories?.length || i.duplicate_of);

  async function upload(files: FileList | File[] | null) {
    if (!files || blocked || locked) return;
    const list = Array.from(files).filter((f) => /\.(jpe?g|png|tiff?)$/i.test(f.name));
    const failures: string[] = [];
    ctx.setError("");
    try {
      for (let i = 0; i < list.length; i++) {
        setUploading(`사진을 불러오는 중 ${i + 1} / ${list.length}`);
        const data = new FormData();
        data.append("file", list[i], list[i].webkitRelativePath || list[i].name);
        try {
          await api(base + "/images", { method: "POST", body: data });
        } catch (e) {
          failures.push(list[i].name + ": " + (e as Error).message);
        }
        if (i % 8 === 7) await ctx.refresh();
      }
      if (Array.from(files).length > list.length)
        failures.push(`${Array.from(files).length - list.length}개 파일은 지원하지 않는 형식이라 건너뛰었습니다 (JPG · PNG · TIFF만 가능).`);
      await ctx.refresh();
      if (failures.length) ctx.setError(failures.join("\n"));
    } finally {
      setUploading("");
    }
  }

  if (project.input_mode && project.input_mode !== "images" && project.input_mode !== "mesh" && !project.images.length)
    return (
      <>
        {toolbar(null)}
        <div className="workspace scroll">
          <ImportPanel
            project={project}
            onComplete={(p) => {
              void ctx.refresh();
              ctx.setStage(p.input_mode === "colmap" ? "sam" : p.stages.review === "completed" ? "train" : "review");
            }}
          />
        </div>
      </>
    );

  const registered = useMemo(() => {
    const r = project.colmap_report?.images;
    return r ? new Map(r.map((x) => [x.name, x.registered])) : null;
  }, [project.colmap_report]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = project.images.filter(
      (i) =>
        (!q || i.source_name.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)) &&
        (filter === "warn"
          ? i.advisories?.length || i.duplicate_of
          : filter === "reg"
            ? registered?.get(i.name) === true
            : filter === "unreg"
              ? registered?.get(i.name) !== true
              : filter !== "err"),
    );
    if (sort === "name") list.sort((a, b) => a.source_name.localeCompare(b.source_name, "ko", { numeric: true }));
    else if (sort === "size") list.sort((a, b) => b.size[0] * b.size[1] - a.size[0] * a.size[1]);
    return list;
  }, [project.images, query, filter, sort, registered]);
  const current = project.images.find((i) => i.name === selected) || project.images[0];
  const sel = ctx.selection;
  useEffect(() => {
    if (sel?.kind === "image" && sel.name !== selected) {
      setSelected(sel.name);
      setPicked(new Set([sel.name]));
    }
  }, [sel]);
  useEffect(() => {
    const all = () => setPicked(new Set(shown.map((i) => i.name)));
    window.addEventListener("m4ml:select-all", all);
    return () => window.removeEventListener("m4ml:select-all", all);
  }, [shown]);
  // Forget picks that no longer exist (removed photos).
  useEffect(() => {
    setPicked((p) => new Set([...p].filter((n) => project.images.some((i) => i.name === n))));
  }, [project.images]);

  function pick(name: string, e: React.MouseEvent) {
    if (e.shiftKey && anchor) {
      const names = shown.map((i) => i.name),
        a = names.indexOf(anchor),
        b = names.indexOf(name);
      if (a >= 0 && b >= 0) setPicked(new Set(names.slice(Math.min(a, b), Math.max(a, b) + 1)));
    } else if (e.ctrlKey || e.metaKey) {
      setPicked((p) => {
        const n = new Set(p);
        if (n.has(name)) n.delete(name);
        else n.add(name);
        return n;
      });
      setAnchor(name);
    } else {
      setPicked(new Set([name]));
      setAnchor(name);
    }
    setSelected(name);
    ctx.select({ kind: "image", name });
  }
  async function removePicked() {
    const names = [...picked];
    if (!names.length || locked || blocked) return;
    if (!window.confirm(`선택한 사진 ${names.length}장을 프로젝트 목록에서 제거할까요?\n원본 파일과 프로젝트 안의 사본은 삭제되지 않습니다.`)) return;
    await ctx.action(async () => {
      for (const n of names) await api<Project>(`${base}/images/${encodeURIComponent(n)}`, { method: "DELETE" });
      setPicked(new Set());
    });
  }
  function onGridKey(e: React.KeyboardEvent) {
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    if (e.key === "Delete" && !locked) {
      e.preventDefault();
      void removePicked();
    } else if (e.key === "Enter" || e.key === " ") {
      if (current) {
        e.preventDefault();
        setZoom(current.name);
      }
    } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const i = shown.findIndex((x) => x.name === current?.name);
      const next = shown[Math.max(0, Math.min(shown.length - 1, i + (e.key === "ArrowRight" ? 1 : -1)))];
      if (next) {
        e.preventDefault();
        setSelected(next.name);
        setPicked(new Set([next.name]));
        setAnchor(next.name);
        ctx.select({ kind: "image", name: next.name });
      }
    }
  }
  const pickers = (
    <>
      <label className="btn" aria-disabled={blocked || locked}>
        <ImagePlus size={15} />이미지 추가
        <input type="file" multiple accept="image/jpeg,image/png,image/tiff" hidden disabled={blocked || locked} onChange={(e) => void upload(e.target.files)} />
      </label>
      <label className="btn" aria-disabled={blocked || locked}>
        <FolderPlus size={15} />폴더 가져오기
        <input type="file" multiple hidden disabled={blocked || locked} {...{ webkitdirectory: "" }} onChange={(e) => void upload(e.target.files)} />
      </label>
    </>
  );
  return (
    <>
      {toolbar(
        <>
          {pickers}
          <span className="sp" />
          <button
            className="btn primary"
            disabled={blocked || usable < 2 || locked}
            onClick={() =>
              void ctx.action(async () => {
                await post(base + "/import-complete");
                ctx.setStage("colmap");
              })
            }
          >
            <Play size={14} />
            {locked ? "불러오기 완료됨" : "불러오기 완료 · 카메라 정합으로"}
          </button>
        </>,
      )}
      {!project.images.length ? (
        <div className="workspace">
          <section
            className={"dropzone grow" + (over ? " over" : "")}
            style={{ justifyContent: "center" }}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              void upload(e.dataTransfer.files);
            }}
          >
            <Upload size={40} className="t3" />
            <h2>사진을 불러오세요</h2>
            <p>객체 주위를 여러 방향에서 찍은 사진을 30장 이상 준비하는 것을 권장합니다. JPG · PNG · TIFF를 지원합니다.</p>
            <div className="row">{pickers}</div>
            <p className="hint">또는 이 영역에 파일이나 폴더를 끌어다 놓으세요. 원본 파일은 수정하지 않습니다.</p>
            {uploading && <p role="status" className="acc">{uploading}</p>}
          </section>
        </div>
      ) : (
        <div className="workspace">
          <div className="col grow" style={{ gap: 0, minWidth: 0 }}>
            <div className="subbar">
              <div className="seg" style={{ height: 26 }}>
                <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>전체 <span className="count">{project.images.length}</span></button>
                <button aria-pressed={filter === "warn"} onClick={() => setFilter("warn")}><TriangleAlert size={13} className="warn" />경고 <span className="count">{warnings.length}</span></button>
                <button aria-pressed={filter === "err"} onClick={() => setFilter("err")}><CircleX size={13} className="err" />오류 <span className="count">{project.import_errors.length}</span></button>
                {registered && (
                  <>
                    <button aria-pressed={filter === "reg"} onClick={() => setFilter("reg")}><CircleCheck size={13} className="ok" />정합됨 <span className="count">{project.images.filter((i) => registered.get(i.name) === true).length}</span></button>
                    <button aria-pressed={filter === "unreg"} onClick={() => setFilter("unreg")}>미정합 <span className="count">{project.images.filter((i) => registered.get(i.name) !== true).length}</span></button>
                  </>
                )}
              </div>
              <label className="search" style={{ flex: "0 1 220px" }}>
                <Search size={13} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="파일 이름 검색" aria-label="사진 이름 검색" />
              </label>
              <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="정렬">
                <option value="import">가져온 순서</option>
                <option value="name">이름순</option>
                <option value="size">해상도 큰 순</option>
              </select>
              {picked.size > 1 && <span className="t2">{picked.size}장 선택</span>}
              {!locked && (
                <button className="btn s danger" disabled={!picked.size || blocked} onClick={() => void removePicked()} title="선택한 사진을 목록에서 제거 (Delete) — 파일은 삭제하지 않습니다">
                  <Trash2 size={12} />제거
                </button>
              )}
              <span className="sp" />
              {uploading && <span className="acc row"><span className="spinner" />{uploading}</span>}
              <span>사용 가능 <b className="t2 num">{usable}</b>장{project.images.length - usable ? ` · 중복 제외 ${project.images.length - usable}장` : ""}</span>
            </div>
            <div
              className="grid"
              tabIndex={0}
              onKeyDown={onGridKey}
              aria-label="사진 목록 — 클릭 선택, Ctrl/Shift 다중 선택, Enter 확대, Delete 제거"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                void upload(e.dataTransfer.files);
              }}
            >
              {filter === "err"
                ? project.import_errors.map((e, i) => (
                    <div className="cell" key={i}>
                      <div className="thumb" style={{ display: "grid", placeItems: "center", background: "repeating-linear-gradient(-45deg,var(--bg-2) 0 6px,var(--bg-3) 6px 12px)", outlineColor: "rgba(239,94,82,.5)" }}>
                        <span className="col" style={{ alignItems: "center", gap: 4, padding: 8, textAlign: "center" }}>
                          <CircleX size={20} className="err" />
                          <span style={{ fontSize: 11, color: "var(--tx-2)" }}>{e.error}</span>
                        </span>
                      </div>
                      <div className="cap"><span className="ellip grow err">{e.name}</span></div>
                    </div>
                  ))
                : shown.map((i, n) => (
                    <button className="cell" key={i.name} aria-pressed={picked.has(i.name) || (!picked.size && current?.name === i.name)} onClick={(e) => pick(i.name, e)} onDoubleClick={() => setZoom(i.name)}>
                      <div className="thumb">
                        <img src={asset(project.id, i.thumbnail)} alt={i.source_name} loading="lazy" />
                        <span className="idx">{n + 1}</span>
                        {(i.advisories?.length || i.duplicate_of) && <span className="flag warn"><TriangleAlert size={12} /></span>}
                        {registered && registered.get(i.name) !== true && <span className="flag b err" title="카메라 정합 실패"><CircleX size={12} /></span>}
                      </div>
                      <div className="cap">
                        <span className="ellip grow">{i.source_name}</span>
                        {i.duplicate_of && <span className="warn" style={{ fontFamily: "var(--font-ui)" }}>중복</span>}
                      </div>
                    </button>
                  ))}
            </div>
            <div className="ready-bar">
              {usable >= 2 ? <CircleCheck size={18} className="ok" /> : <Info size={18} className="t3" />}
              <div className="col grow" style={{ gap: 1 }}>
                <b style={{ fontWeight: 600, color: "var(--tx-1)" }}>
                  {locked ? "이미지 불러오기가 완료되었습니다" : usable >= 2 ? "카메라 정합을 시작할 준비가 되었습니다" : "사진을 더 추가하세요"}
                </b>
                <span className="hint">
                  {usable}장으로 카메라 위치를 추정합니다. 흐리거나 겹침이 부족한 사진은 정합 단계에서 자동으로 제외됩니다.
                </span>
              </div>
            </div>
          </div>
          {current && (
            <InspectorPortal>
              <div className="sec">
                <button className="preview-box" style={{ cursor: "zoom-in", padding: 0, border: 0, width: "100%", position: "relative" }} onClick={() => setZoom(current.name)} title="크게 보기 (Enter)">
                  <img src={asset(project.id, current.path || current.thumbnail)} alt={current.source_name} />
                  <Maximize2 size={14} style={{ position: "absolute", right: 8, bottom: 8, color: "#fff" }} />
                </button>
                <div className="row" style={{ marginTop: 10 }}>
                  <span className="mono ellip grow" style={{ fontSize: 13 }}>{current.source_name}</span>
                  {current.duplicate_of ? <span className="badge warn">중복 · 제외</span> : <span className="badge ok">사용 가능</span>}
                </div>
              </div>
              <div className="sec">
                <div className="sec-h"><b>이미지 정보</b></div>
                <div className="kv">
                  <span>해상도</span><span className="num">{current.size.join(" × ")}</span>
                  <span>화소</span><span className="num">{((current.size[0] * current.size[1]) / 1e6).toFixed(1)} MP</span>
                  <span>저장 이름</span><span className="mono">{current.name}</span>
                  {registered && <><span>카메라 정합</span><span>{registered.get(current.name) ? <span className="ok">등록됨</span> : <span className="err">실패</span>}</span></>}
                </div>
                {current.advisories?.map((a) => (
                  <div className="callout warn" key={a} style={{ marginTop: 10 }}><TriangleAlert size={14} />{a}</div>
                ))}
              </div>
              <div className="sec">
                <div className="callout"><Info size={15} /><span>지원 형식: <b>JPG · PNG · TIFF</b>. EXIF 방향을 바로잡아 저장하며, 원본 파일은 수정하지 않습니다.</span></div>
              </div>
            </InspectorPortal>
          )}
        </div>
      )}
      {zoom && <Lightbox project={project} names={shown.map((i) => i.name)} name={zoom} onName={(n) => { setZoom(n); setSelected(n); ctx.select({ kind: "image", name: n }); }} onClose={() => setZoom(null)} />}
    </>
  );
}

/** Full-resolution photo viewer: wheel zoom around the cursor, drag to pan, ←/→ to step, Esc to close. */
function Lightbox({ project, names, name, onName, onClose }: { project: Project; names: string[]; name: string; onName: (n: string) => void; onClose: () => void }) {
  const image = project.images.find((i) => i.name === name);
  const [view, setView] = useState({ s: 1, x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const index = names.indexOf(name);
  const step = (d: number) => {
    const n = names[index + d];
    if (n) {
      onName(n);
      setView({ s: 1, x: 0, y: 0 });
    }
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "0") setView({ s: 1, x: 0, y: 0 });
      else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  });
  if (!image) return null;
  return (
    <div className="lightbox" role="dialog" aria-label={`${image.source_name} 크게 보기`}>
      <div className="lightbox-bar">
        <b className="ellip">{image.source_name}</b>
        <span className="t3 num">{image.size.join(" × ")} · {index + 1} / {names.length}</span>
        <span className="sp" />
        <span className="t3 num">{Math.round(view.s * 100)}%</span>
        <button className="btn s ghost" onClick={() => setView({ s: 1, x: 0, y: 0 })}>화면에 맞춤 (0)</button>
        <button className="icon-btn" aria-label="닫기 (Esc)" title="닫기 (Esc)" onClick={onClose}><X size={16} /></button>
      </div>
      <div
        className="lightbox-stage"
        onWheel={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const cx = e.clientX - r.left - r.width / 2,
            cy = e.clientY - r.top - r.height / 2;
          const s = Math.min(16, Math.max(1, view.s * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
          const k = s / view.s;
          setView(s === 1 ? { s: 1, x: 0, y: 0 } : { s, x: cx - (cx - view.x) * k, y: cy - (cy - view.y) * k });
        }}
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          setDrag({ x: e.clientX - view.x, y: e.clientY - view.y });
        }}
        onPointerMove={(e) => drag && view.s > 1 && setView({ ...view, x: e.clientX - drag.x, y: e.clientY - drag.y })}
        onPointerUp={() => setDrag(null)}
        onDoubleClick={() => setView(view.s > 1 ? { s: 1, x: 0, y: 0 } : { s: 2, x: 0, y: 0 })}
        style={{ cursor: view.s > 1 ? (drag ? "grabbing" : "grab") : "zoom-in" }}
      >
        <img src={asset(project.id, image.path || image.thumbnail)} alt={image.source_name} draggable={false} style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }} />
        <button className="lightbox-nav l" aria-label="이전 사진" disabled={index <= 0} onClick={(e) => { e.stopPropagation(); step(-1); }}><ChevronLeft size={22} /></button>
        <button className="lightbox-nav r" aria-label="다음 사진" disabled={index >= names.length - 1} onClick={(e) => { e.stopPropagation(); step(1); }}><ChevronRight size={22} /></button>
      </div>
      <div className="lightbox-hint">휠 확대/축소 · 드래그 이동 · 더블클릭 2배 · ←/→ 이전/다음 · Esc 닫기</div>
    </div>
  );
}
