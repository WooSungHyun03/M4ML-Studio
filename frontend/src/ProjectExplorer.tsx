import { useMemo, useState } from "react";
import { Box, Camera, ChevronDown, ChevronRight, CircleCheck, CircleX, Cpu, Download, Image as ImageIcon, Layers, Pencil, Search, SkipForward, TriangleAlert, Circle, Save } from "lucide-react";
import type { Project, Stage } from "./api";
import type { Selection } from "./context";
import { fmt, mb } from "./context";

export interface Assets {
  checkpoints: { name: string; iteration: number; bytes: number; path: string; resumable: boolean }[];
  mesh_files: { name: string; bytes: number; path: string }[];
  project_path: string;
}

interface Row {
  key: string;
  label: string;
  icon: React.ReactNode;
  problem?: boolean;
  sel: Selection;
  stage?: Stage;
  meta?: string;
}

function maskIcon(status: string, warn: boolean) {
  if (status === "approved") return <CircleCheck size={13} className="ok" />;
  if (status === "manual") return <Pencil size={12} className="acc" />;
  if (status === "skipped") return <SkipForward size={12} className="skipc" />;
  if (status === "invalid") return <CircleX size={13} className="err" />;
  if (warn) return <TriangleAlert size={12} className="warn" />;
  return <Circle size={12} className="t4" />;
}

export function ProjectExplorer({
  project,
  assets,
  selection,
  onSelect,
  onOpen,
}: {
  project: Project;
  assets: Assets | null;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onOpen: (s: Selection, stage?: Stage) => void;
}) {
  const [query, setQuery] = useState(""),
    [problemsOnly, setProblemsOnly] = useState(false),
    [closed, setClosed] = useState<Record<string, boolean>>({ cameras: true });
  const sections = useMemo(() => {
    const report = project.colmap_report;
    const reg = new Map((report?.images || []).map((i) => [i.name, i]));
    const images: Row[] = project.images.map((i) => ({
      key: "img:" + i.name,
      label: i.source_name,
      icon: i.duplicate_of || i.advisories?.length ? <TriangleAlert size={12} className="warn" /> : <ImageIcon size={13} className="t3" />,
      problem: !!(i.duplicate_of || i.advisories?.length),
      sel: { kind: "image", name: i.name },
      stage: "import",
      meta: i.duplicate_of ? "중복" : undefined,
    }));
    const cameras: Row[] = (report?.images || []).map((i) => ({
      key: "cam:" + i.name,
      label: i.name,
      icon: i.registered ? <Camera size={13} className="ok" /> : <CircleX size={13} className="err" />,
      problem: !i.registered,
      sel: { kind: "camera", name: i.name },
      stage: "colmap",
      meta: i.registered ? undefined : "실패",
    }));
    const masks: Row[] = Object.entries(project.masks)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, m]) => ({
        key: "mask:" + name,
        label: name,
        icon: maskIcon(m.status, !!m.warnings?.length),
        problem: m.status === "invalid" || !m.valid || !!m.warnings?.length,
        sel: { kind: "mask", name },
        stage: "review",
        meta: m.coverage != null ? (m.coverage * 100).toFixed(0) + "%" : undefined,
      }));
    const training: Row[] = [];
    if (project.training)
      training.push({ key: "train", label: `학습 결과 · ${fmt(project.training.iterations)}회`, icon: <Cpu size={13} className="ok" />, sel: { kind: "training" }, stage: "train", meta: fmt(project.training.gaussians) });
    if (project.training_partial)
      training.push({ key: "partial", label: `중단된 학습 · ${fmt(project.training_partial.checkpoint)}회`, icon: <Cpu size={13} className="warn" />, sel: { kind: "training" }, stage: "train", meta: "이어서" });
    const checkpoints: Row[] = (assets?.checkpoints || []).map((c) => ({
      key: "ckpt:" + c.path,
      label: c.name,
      icon: <Save size={13} className={c.resumable ? "acc" : "t3"} />,
      sel: { kind: "checkpoint", ...c },
      stage: "train",
      meta: mb(c.bytes),
    }));
    const meshes: Row[] = (assets?.mesh_files || []).filter((f) => f.name === "fuse_post.ply").map((f) => ({
      key: "mesh:" + f.path,
      label: "3D 모델 (" + (project.mesh?.colors !== false ? "색상" : "형상") + ")",
      icon: <Box size={13} className="ok" />,
      sel: { kind: "mesh", ...f },
      stage: "mesh",
      meta: project.mesh ? fmt(project.mesh.triangles) + "△" : undefined,
    }));
    const exports: Row[] = (assets?.mesh_files || []).map((f) => ({
      key: "exp:" + f.path,
      label: f.name.endsWith(".glb") ? `GLB · ${f.name}` : `PLY · ${f.name}`,
      icon: <Download size={13} className="t3" />,
      sel: { kind: "mesh", ...f },
      stage: "mesh",
      meta: mb(f.bytes),
    }));
    return [
      { id: "images", title: "프로젝트 이미지", icon: <ImageIcon size={13} />, rows: images },
      { id: "cameras", title: "등록된 카메라", icon: <Camera size={13} />, rows: cameras, badge: report ? `${report.registered}/${report.total}` : undefined },
      { id: "masks", title: "객체 마스크", icon: <Layers size={13} />, rows: masks },
      { id: "training", title: "학습 결과", icon: <Cpu size={13} />, rows: training },
      { id: "checkpoints", title: "체크포인트", icon: <Save size={13} />, rows: checkpoints },
      { id: "mesh", title: "최종 3D 모델", icon: <Box size={13} />, rows: meshes },
      { id: "exports", title: "내보내기 파일", icon: <Download size={13} />, rows: exports },
    ];
  }, [project, assets]);
  const q = query.trim().toLowerCase();
  const same = (a: Selection, b: Selection) => !!a && !!b && JSON.stringify(a) === JSON.stringify(b);
  return (
    <div className="explorer" aria-label="프로젝트 탐색기">
      <div className="dock-h">
        <b>프로젝트 탐색기</b>
      </div>
      <div className="explorer-tools">
        <label className="search">
          <Search size={13} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="이름 검색" aria-label="프로젝트 항목 검색" />
        </label>
        <button className={"btn s ghost" + (problemsOnly ? " on" : "")} aria-pressed={problemsOnly} title="문제가 있는 항목만 보기" onClick={() => setProblemsOnly((v) => !v)}>
          <TriangleAlert size={12} />
        </button>
      </div>
      <div className="explorer-tree" role="tree">
        {sections.map((s) => {
          const rows = s.rows.filter((r) => (!q || r.label.toLowerCase().includes(q)) && (!problemsOnly || r.problem));
          const isClosed = closed[s.id] && !q;
          return (
            <div key={s.id} role="group">
              <button className="tree-sec" aria-expanded={!isClosed} onClick={() => setClosed((c) => ({ ...c, [s.id]: !c[s.id] }))}>
                {isClosed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                {s.icon}
                <span className="grow ellip">{s.title}</span>
                <span className="count">{s.badge || s.rows.length}</span>
              </button>
              {!isClosed &&
                rows.slice(0, 500).map((r) => (
                  <button
                    key={r.key}
                    role="treeitem"
                    aria-selected={same(selection, r.sel)}
                    className="tree-row"
                    onClick={() => onSelect(r.sel)}
                    onDoubleClick={() => onOpen(r.sel, r.stage)}
                    title={r.label + " — 두 번 클릭하면 해당 작업 화면으로 이동합니다"}
                  >
                    {r.icon}
                    <span className="grow ellip">{r.label}</span>
                    {r.meta && <span className="meta">{r.meta}</span>}
                  </button>
                ))}
              {!isClosed && rows.length > 500 && <div className="tree-more">외 {rows.length - 500}개 · 검색으로 좁혀 보세요</div>}
              {!isClosed && !rows.length && <div className="tree-more">{s.rows.length ? "조건에 맞는 항목 없음" : "아직 없음"}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
