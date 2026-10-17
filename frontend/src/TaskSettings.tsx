import { useEffect, useRef, useState } from "react";
import { X, RotateCcw } from "lucide-react";
import { api } from "./api";
export type Values = Record<string, string | number | boolean>;
export interface Definition {
  section?: string;
  id: string;
  label: string;
  description: string;
  type: string;
  default: string | number | boolean;
  min: number;
  max: number;
  options?: string[];
  advanced: boolean;
  source: string;
}
export interface SettingGroup {
  last_execution?: { provider: string; values: Values; parameters: Values };
  group: string;
  provider: string;
  version: number;
  fields: Definition[];
  values: Values;
  presets: Record<string, Values>;
  policy: string;
}
export type SettingsBundle = Record<string, SettingGroup>;
export const GROUP_LABELS: Record<string, string> = {
  camera: "카메라 정합",
  segmentation: "객체 선택",
  review: "마스크 검토",
  training: "3D 재구성",
  mesh: "3D 모델 생성",
  view: "표시",
};
export function useTaskSettings(base: string, key: string) {
  const [settings, setSettings] = useState<SettingsBundle>({});
  const [error, setError] = useState(""),
    [attempt, retry] = useState(0);
  useEffect(() => {
    let live = true;
    setError("");
    if (base)
      void api<SettingsBundle>(base + "/task-settings")
        .then((v) => {
          if (live) setSettings(v);
        })
        .catch((e) => {
          if (live) {
            setSettings({});
            setError((e as Error).message);
          }
        });
    return () => {
      live = false;
    };
  }, [base, key, attempt]);
  return { settings, error, reload: () => retry((v) => v + 1) };
}
export function setting<T extends string | number | boolean>(
  settings: SettingsBundle | undefined,
  group: string,
  id: string,
  fallback: T,
): T {
  return (settings?.[group]?.values[id] ?? fallback) as T;
}
export function TaskSettingsPanel({
  base,
  settings,
  initial,
  active,
  onClose,
  onSaved,
  onDirty,
  loadError,
  onReload,
  lockMessage,
}: {
  lockMessage?: string;
  loadError?: string;
  onReload?: () => void;
  onDirty?: (v: boolean) => void;
  base: string;
  settings: SettingsBundle;
  initial: string;
  active: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [group, setGroup] = useState(initial),
    [draft, setDraft] = useState<Values>({ ...settings[initial]?.values }),
    [baseline, setBaseline] = useState<Values>({
      ...settings[initial]?.values,
    }),
    [error, setError] = useState(""),
    [saving, setSaving] = useState(false),
    [notice, setNotice] = useState("");
  const panel = useRef<HTMLElement>(null),
    previousFocus = useRef(document.activeElement as HTMLElement | null);
  const s = settings[group];
  const loadedSchema = useRef(
    settings[initial]?.provider
      ? initial + ":" + settings[initial].provider
      : "",
  );
  const dirty = !!s && JSON.stringify(draft) !== JSON.stringify(baseline);
  const locked = active && !["view", "review"].includes(group);
  useEffect(() => {
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const previous = previousFocus.current;
    return () => previous?.focus();
  }, []);
  useEffect(() => {
    if (s && loadedSchema.current !== group + ":" + s.provider) {
      loadedSchema.current = group + ":" + s.provider;
      setDraft({ ...s.values });
      setBaseline({ ...s.values });
    }
  }, [group, s?.provider, !!s]);
  useEffect(() => {
    onDirty?.(dirty);
    const unload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", unload);
    return () => {
      onDirty?.(false);
      window.removeEventListener("beforeunload", unload);
    };
  }, [dirty, onDirty]);
  if (!s)
    return (
      <aside className="task-settings" role="dialog" aria-label="세부 설정">
        <button onClick={onClose}>닫기</button>
        <p role="status">{loadError || "설정을 불러오고 있습니다."}</p>
        {loadError && (
          <button className="btn" onClick={onReload}>
            다시 시도
          </button>
        )}
      </aside>
    );
  function close() {
    if (saving) return;
    if (!dirty || window.confirm("저장하지 않은 설정을 버릴까요?")) onClose();
  }
  function changeGroup(g: string) {
    if (saving) return;
    if (dirty && !window.confirm("저장하지 않은 설정을 버릴까요?")) return;
    setGroup(g);
    setDraft({ ...settings[g].values });
    setBaseline({ ...settings[g].values });
    setError("");
    setNotice("");
  }
  async function save() {
    if (locked || saving) return;
    const form = panel.current?.querySelector("form");
    if (!form?.reportValidity()) return;
    setSaving(true);
    setError("");
    try {
      const saved = await api<SettingGroup>(base + "/task-settings/" + group, {
        method: "PATCH",
        body: JSON.stringify({ values: draft }),
      });
      setDraft({ ...saved.values });
      setBaseline({ ...saved.values });
      await onSaved();
      setNotice("저장했습니다.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const render = (f: Definition) => (
    <label className="field setting-field" key={f.id} title={f.description}>
      <span className="row">
        <b>{f.label}</b>
        {draft[f.id] !== baseline[f.id] && <span className="acc">변경</span>}
        <span className="sp" />
        <button
          type="button"
          className="icon-btn"
          aria-label={f.label + " 기본값 복원"}
          title="이 항목 기본값 복원"
          disabled={locked || saving}
          onClick={() => setDraft({ ...draft, [f.id]: f.default })}
        >
          <RotateCcw size={12} />
        </button>
      </span>
      {f.type === "boolean" ? (
        <span>
          <input
            type="checkbox"
            checked={!!draft[f.id]}
            disabled={locked || saving}
            onChange={(e) => setDraft({ ...draft, [f.id]: e.target.checked })}
          />{" "}
          사용
        </span>
      ) : f.type === "choice" ? (
        <select
          value={String(draft[f.id])}
          disabled={locked || saving}
          onChange={(e) => setDraft({ ...draft, [f.id]: e.target.value })}
        >
          {f.options?.map((v) => (
            <option key={v} value={v}>
              {(
                {
                  all: "전체 사진",
                  unreviewed: "미검토 사진",
                  warnings: "경고가 있는 사진",
                  reviewed: "검토한 사진",
                  exhaustive: "전체 비교",
                  sequential: "인접 비교",
                  color: "색상 메시",
                  vertex: "정점 색상",
                  shaded: "셰이딩",
                  wire: "와이어프레임",
                  normals: "법선",
                  points: "포인트 클라우드",
                  rgb: "색상",
                  alpha: "불투명도",
                  depth: "깊이",
                  normal: "법선",
                  objectmark: "객체 점수",
                } as Record<string, string>
              )[v] || v}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={f.type === "color" ? "color" : "number"}
          value={String(draft[f.id] ?? "")}
          min={f.min}
          max={f.max}
          step={f.type === "integer" ? 1 : "any"}
          required
          disabled={locked || saving}
          onChange={(e) =>
            setDraft({
              ...draft,
              [f.id]:
                f.type === "color"
                  ? e.target.value
                  : e.target.value === ""
                    ? ""
                    : Number(e.target.value),
            })
          }
        />
      )}
      <small>
        기본값{" "}
        {typeof f.default === "boolean"
          ? f.default
            ? "사용"
            : "사용 안 함"
          : String(f.default)}
        {["number", "integer"].includes(f.type)
          ? ` · 범위 ${f.min}–${f.max}`
          : ""}
      </small>
      {f.description && <small>{f.description}</small>}
    </label>
  );
  const grouped = (fields: Definition[]) =>
    Object.entries(
      fields.reduce<Record<string, Definition[]>>((all, f) => {
        (all[f.section || "설정"] ??= []).push(f);
        return all;
      }, {}),
    ).map(([title, fields]) => (
      <section key={title}>
        <h3 className="t3" style={{ fontSize: 12, marginTop: 16 }}>
          {title}
        </h3>
        {fields.map(render)}
      </section>
    ));
  return (
    <aside
      className="task-settings"
      role="dialog"
      aria-modal="false"
      aria-label={group === "view" ? "표시 설정" : "세부 설정"}
      ref={panel}
      onKeyDown={(e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
          e.preventDefault();
          e.stopPropagation();
          void save();
        }
        if (e.key === "Escape") {
          e.stopPropagation();
          close();
        }
      }}
    >
      <header className="row">
        <b>{group === "view" ? "표시 설정" : "세부 설정"}</b>
        <span className="sp" />
        <button
          className="icon-btn"
          aria-label="세부 설정 닫기"
          disabled={saving}
          onClick={close}
        >
          <X size={16} />
        </button>
      </header>
      <nav className="row">
        {Object.keys(settings).map((g) => (
          <button
            key={g}
            className={"btn small" + (group === g ? " active" : "")}
            aria-pressed={group === g}
            onClick={() => changeGroup(g)}
          >
            {GROUP_LABELS[g]}
          </button>
        ))}
      </nav>
      <p className="hint">{s.policy}</p>
      {locked && (
        <p className="callout warn">
          {lockMessage || "실행이 끝난 뒤 변경할 수 있습니다."}
        </p>
      )}
      {s.last_execution && (
        <details>
          <summary>마지막 학습 실행 설정</summary>
          <pre style={{ fontSize: 11, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(s.last_execution.parameters, null, 2)}
          </pre>
          <button
            type="button"
            className="btn"
            disabled={locked || s.last_execution.provider !== s.provider}
            onClick={() => {
              setDraft({ ...s.last_execution!.values });
              setNotice("이전 실행의 설정을 불러왔습니다. 검토 후 저장하세요.");
            }}
          >
            실행 설정 불러오기
          </button>
        </details>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        {!!Object.keys(s.presets).length && (
          <label className="field">
            품질
            <select
              value="custom"
              disabled={locked}
              onChange={(e) => {
                const preset = s.presets[e.target.value];
                if (preset) setDraft({ ...draft, ...preset });
              }}
            >
              <option value="custom">사용자 지정</option>
              {Object.keys(s.presets).map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
            <small>
              프리셋은 아래 설정값을 변경합니다. 저장 전 검토할 수 있습니다.
            </small>
          </label>
        )}
        {grouped(s.fields.filter((f) => !f.advanced))}
        <details>
          <summary>고급</summary>
          {grouped(s.fields.filter((f) => f.advanced))}
        </details>
        <footer>
          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={locked || saving}
              onClick={() => {
                setDraft(
                  Object.fromEntries(s.fields.map((f) => [f.id, f.default])),
                );
                setNotice(
                  "현재 그룹의 기본값을 미리 보고 있습니다. 저장 또는 취소하세요.",
                );
              }}
            >
              현재 그룹 기본값 복원
            </button>
            <span className="sp" />
            <button type="button" className="btn" onClick={close}>
              취소
            </button>
            <button
              className="btn primary"
              disabled={locked || saving || !dirty}
            >
              {saving ? "저장 중…" : "저장"}
            </button>
          </div>
          <p role="status" className={error ? "err" : "hint"}>
            {error ||
              notice ||
              (dirty
                ? "저장하지 않은 변경 사항이 있습니다."
                : "저장된 설정입니다.")}
          </p>
        </footer>
      </form>
    </aside>
  );
}

/** Serialize small viewport/review changes and flush on workspace exit. */
export function useSettingSaver(
  base: string,
  group: string,
  onSaved: () => Promise<void>,
  onError: (s: string) => void,
) {
  const pending = useRef<Values>({}),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null),
    queue = useRef(Promise.resolve());
  const callbacks = useRef({ onSaved, onError });
  callbacks.current = { onSaved, onError };
  function flush() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const batch = pending.current;
    pending.current = {};
    if (!Object.keys(batch).length) return;
    queue.current = queue.current
      .catch(() => {})
      .then(async () => {
        const current = await api<SettingsBundle>(base + "/task-settings");
        await api(base + "/task-settings/" + group, {
          method: "PATCH",
          body: JSON.stringify({
            values: { ...current[group].values, ...batch },
          }),
        });
        await callbacks.current.onSaved();
      })
      .catch((e) => callbacks.current.onError((e as Error).message));
  }
  useEffect(() => () => flush(), [base, group]);
  return (values: Values) => {
    pending.current = { ...pending.current, ...values };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, 200);
  };
}
