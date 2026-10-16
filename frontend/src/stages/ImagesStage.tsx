import { useState } from "react";
import { CircleCheck, FolderPlus, ImagePlus, Info, Play, TriangleAlert, Upload, CircleX } from "lucide-react";
import { api, asset, post } from "../api";
import type { StageCtx } from "../context";
import { ImportPanel } from "../ImportPanel";

export function ImagesStage({ ctx, toolbar }: { ctx: StageCtx; toolbar: (node: React.ReactNode) => React.ReactNode }) {
  const { project, base, blocked } = ctx;
  const [uploading, setUploading] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [filter, setFilter] = useState<"all" | "warn" | "err">("all"),
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

  const shown = project.images.filter((i) =>
    filter === "warn" ? i.advisories?.length || i.duplicate_of : filter === "err" ? false : true,
  );
  const current = project.images.find((i) => i.name === selected) || project.images[0];
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
            <h2>이미지를 불러오세요</h2>
            <p>객체 주위를 여러 방향에서 찍은 사진이 30장 이상 필요합니다. JPG · PNG · TIFF를 지원합니다.</p>
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
              </div>
              <span className="sp" />
              {uploading && <span className="acc row"><span className="spinner" />{uploading}</span>}
              <span>사용 가능 <b className="t2 num">{usable}</b>장{project.images.length - usable ? ` · 중복 제외 ${project.images.length - usable}장` : ""}</span>
            </div>
            <div
              className="grid"
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
                    <button className="cell" key={i.name} aria-pressed={current?.name === i.name} onClick={() => setSelected(i.name)}>
                      <div className="thumb">
                        <img src={asset(project.id, i.thumbnail)} alt={i.source_name} loading="lazy" />
                        <span className="idx">{n + 1}</span>
                        {(i.advisories?.length || i.duplicate_of) && <span className="flag warn"><TriangleAlert size={12} /></span>}
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
            <aside className="panel insp" style={{ width: 400, flex: "none" }}>
              <div className="sec">
                <div className="preview-box">
                  <img src={asset(project.id, current.path || current.thumbnail)} alt={current.source_name} />
                </div>
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
                </div>
                {current.advisories?.map((a) => (
                  <div className="callout warn" key={a} style={{ marginTop: 10 }}><TriangleAlert size={14} />{a}</div>
                ))}
              </div>
              <div className="sec">
                <div className="callout"><Info size={15} /><span>지원 형식: <b>JPG · PNG · TIFF</b>. EXIF 방향을 바로잡아 저장하며, 원본 파일은 수정하지 않습니다.</span></div>
              </div>
            </aside>
          )}
        </div>
      )}
    </>
  );
}
