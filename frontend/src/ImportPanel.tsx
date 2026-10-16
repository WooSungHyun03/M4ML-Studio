import { useState } from "react";
import { api, post } from "./api";
import type { Project } from "./api";
interface Audit {
  components: { path: string; registered?: number; error?: string }[];
  selected_sparse?: string;
  registered?: number;
  undistortion_state?: string;
  paths?: { images: string; masks: string | null };
  blocking_errors: string[];
  warnings: string[];
  excluded?: string[];
  mask_errors?: { name: string; error: string }[];
  images: { name: string; valid: boolean; error?: string }[];
}
export function ImportPanel({
  project,
  onComplete,
}: {
  project: Project;
  onComplete: (p: Project) => void;
}) {
  const [withMasks, setWithMasks] = useState(
      project.input_mode === "colmap_masks",
    ),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(""),
    [error, setError] = useState(""),
    [audit, setAudit] = useState<Audit | null>(null);
  const [sparse, setSparse] = useState(""),
    [images, setImages] = useState(""),
    [masks, setMasks] = useState(""),
    [foreground, setForeground] = useState("white"),
    [channel, setChannel] = useState("gray"),
    [normalize, setNormalize] = useState(false),
    [skip, setSkip] = useState(false);
  const base = `/projects/${project.id}`;
  const options = () => ({
    with_masks: withMasks,
    sparse: sparse || null,
    images: images || null,
    masks: masks || null,
    foreground,
    mask_channel: channel,
    normalize_masks: normalize,
    skip_review: skip,
  });
  async function upload(files: FileList | null) {
    if (!files) return;
    setBusy(true);
    setError("");
    let count = 0;
    try {
      const usable = Array.from(files).filter((f) =>
        /\.(bin|txt|png|jpe?g|tiff?)$/i.test(f.name),
      );
      if (usable.length > 20000)
        throw Error("가져올 파일 수가2만 개를 초과합니다.");
      for (const f of usable) {
        setProgress(
          `프로젝트에 복사 중 ${++count} / ${usable.length} · ${f.name}`,
        );
        const data = new FormData();
        data.append("file", f, f.webkitRelativePath || f.name);
        await api(base + "/import-files", { method: "POST", body: data });
      }
      await inspect();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }
  async function inspect() {
    setError("");
    setProgress("실제 카메라·사진·마스크를 검사하고 있습니다.");
    const result = await post<Audit>(base + "/inspect-import", options());
    setAudit(result);
    if (!sparse && result.selected_sparse) setSparse(result.selected_sparse);
  }
  async function commit() {
    setBusy(true);
    setError("");
    setProgress(
      "검증된 데이터를 복사하고 있습니다. 필요한 경우에만 왜곡을 보정합니다.",
    );
    try {
      const result = await post<{
        committed: boolean;
        audit: Audit;
        project?: Project;
      }>(base + "/commit-import", options());
      setAudit(result.audit);
      if (result.project) onComplete(result.project);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }
  return (
    <section className="import-workspace">
      <h2>{withMasks ? "카메라 정합 결과 + 마스크 가져오기" : "카메라 정합 결과 가져오기"}</h2>
      <p>
        이미지와 카메라 정합 결과(COLMAP 형식 sparse 모델: cameras · images ·
        points3D, .bin 또는 .txt)가 들어 있는 폴더를 선택하세요. 파일은 프로젝트로
        복사되며 원본은 수정하지 않습니다. 검사를 통과하면 카메라 정합을 다시
        실행하지 않습니다.
      </p>
      <div className="actions">
        <label className="btn primary">
          데이터 폴더 선택
          <input
            aria-label="가져올 데이터 폴더"
            type="file"
            multiple
            {...{ webkitdirectory: "" }}
            hidden
            disabled={busy}
            onChange={(e) => void upload(e.target.files)}
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={withMasks}
            disabled={busy}
            onChange={(e) => {
              setWithMasks(e.target.checked);
              setAudit(null);
            }}
          />
          기존 마스크 함께 사용
        </label>
      </div>
      <details>
        <summary>폴더 직접 매핑·마스크 복구 옵션</summary>
        <p>선택 폴더 내부의 상대 경로입니다. 비워 두면 자동 감지합니다.</p>
        <label className="field">
          이미지 폴더
          <input
            value={images}
            onChange={(e) => {
              setImages(e.target.value);
              setAudit(null);
            }}
            placeholder="데이터/images"
          />
        </label>
        <label className="field">
          마스크 폴더
          <input
            value={masks}
            onChange={(e) => {
              setMasks(e.target.value);
              setAudit(null);
            }}
            placeholder="데이터/mask"
          />
        </label>
        <label className="field">
          카메라 정합 결과 폴더 (sparse)
          <input
            value={sparse}
            onChange={(e) => {
              setSparse(e.target.value);
              setAudit(null);
            }}
            placeholder="데이터/sparse/0"
          />
        </label>
        {withMasks && (
          <>
            <label className="field">
              대상 전경
              <select
                value={foreground}
                onChange={(e) => {
                  setForeground(e.target.value);
                  setAudit(null);
                }}
              >
                <option value="white">흰색255가 대상</option>
                <option value="black">검정0이 대상 · 반전 적용</option>
              </select>
            </label>
            <label className="field">
              마스크 채널
              <select
                value={channel}
                onChange={(e) => {
                  setChannel(e.target.value);
                  setAudit(null);
                }}
              >
                <option value="gray">흑백 픽셀</option>
                <option value="alpha">PNG 알파 채널</option>
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={normalize}
                onChange={(e) => {
                  setNormalize(e.target.checked);
                  setAudit(null);
                }}
              />
              명시적0/255 정규화 · 임계값127 · 원본 보존
            </label>
          </>
        )}
      </details>
      <button
        className="btn"
        style={{ alignSelf: "flex-start" }}
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void inspect()
            .catch((e) => setError(e.message))
            .finally(() => {
              setBusy(false);
              setProgress("");
            });
        }}
      >
        입력 데이터 다시 검사
      </button>
      {busy && <p role="status">{progress}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {audit && (
        <div className="import-audit">
          <h3>검사 결과 · 등록 {audit.registered || 0}장</h3>
          {audit.components.length > 1 && (
            <label className="field">
              사용할 재구성 그룹
              <select
                value={sparse}
                onChange={(e) => {
                  setSparse(e.target.value);
                  setAudit(null);
                }}
              >
                {audit.components.map((c) => (
                  <option key={c.path} value={c.path} disabled={!!c.error}>
                    {c.path} · {c.registered ?? "오류"}장
                  </option>
                ))}
              </select>
            </label>
          )}
          <p>
            {audit.undistortion_state === "required"
              ? "렌즈 왜곡 보정만 실행합니다 (특징점 추출·매칭·카메라 등록은 다시 하지 않음)."
              : "이미 왜곡 보정된 사진과 카메라를 그대로 사용합니다."}
          </p>
          <p>
            이미지: {audit.paths?.images || "찾지 못함"} / 마스크:{" "}
            {audit.paths?.masks || "없음"}
          </p>
          {audit.warnings.map((x) => (
            <p className="advisory" key={x}>
              {x}
            </p>
          ))}
          {audit.blocking_errors.map((x) => (
            <p className="error" key={x}>
              {x}
            </p>
          ))}
          {audit.mask_errors?.map((x) => (
            <p className="error" key={x.name}>
              {x.error}
            </p>
          ))}
          {!!audit.excluded?.length && (
            <details>
              <summary>미등록 사진 {audit.excluded.length}장 제외</summary>
              {audit.excluded.map((x) => (
                <p key={x}>{x}</p>
              ))}
            </details>
          )}
          {withMasks && (
            <label className="import-consent">
              <input
                type="checkbox"
                checked={skip}
                onChange={(e) => setSkip(e.target.checked)}
              />
              검증된 가져온 마스크의 수동 검토를 생략합니다. 학습은 별도로
              승인합니다.
            </label>
          )}
          <button
            className="btn primary l"
            style={{ alignSelf: "flex-start" }}
            disabled={
              busy ||
              !!audit.blocking_errors.length ||
              !!audit.mask_errors?.length
            }
            onClick={() => void commit()}
          >
            {withMasks
              ? skip
                ? "검증된 데이터 사용 · 3D 재구성 준비"
                : "데이터 사용 · 마스크 검토로"
              : "검증된 데이터 사용 · 마스크 생성으로"}
          </button>
          {!!audit.mask_errors?.length && (
            <button
              className="btn"
              onClick={() => {
                setWithMasks(false);
                setAudit(null);
              }}
            >
              카메라만 사용하고 마스크 다시 생성
            </button>
          )}
        </div>
      )}
    </section>
  );
}
