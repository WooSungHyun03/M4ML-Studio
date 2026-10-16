import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight } from "lucide-react";

export interface MenuItem {
  label?: string;
  shortcut?: string;
  action?: () => void;
  disabled?: boolean;
  checked?: boolean;
  hint?: string;
  submenu?: MenuItem[];
  separator?: boolean;
}
export interface Menu {
  label: string;
  items: MenuItem[];
}

function Items({ items, close }: { items: MenuItem[]; close: () => void }) {
  const [sub, setSub] = useState<number | null>(null);
  return (
    <div className="menu-pop" role="menu">
      {items.map((it, i) =>
        it.separator ? (
          <div key={i} className="menu-sep" role="separator" />
        ) : (
          <div key={i} className="menu-row" onMouseEnter={() => setSub(it.submenu ? i : null)}>
            <button
              role="menuitem"
              className="menu-item"
              disabled={it.disabled || (!it.action && !it.submenu)}
              title={it.hint}
              aria-haspopup={it.submenu ? "menu" : undefined}
              onClick={() => {
                if (it.submenu) return setSub(sub === i ? null : i);
                close();
                it.action?.();
              }}
            >
              <span className="mi-check">{it.checked && <Check size={13} />}</span>
              <span className="mi-label">{it.label}</span>
              <span className="mi-short">{it.shortcut}</span>
              {it.submenu && <ChevronRight size={13} className="t3" />}
            </button>
            {it.submenu && sub === i && <div className="menu-sub"><Items items={it.submenu} close={close} /></div>}
          </div>
        ),
      )}
    </div>
  );
}

/** Application menu bar (파일 · 편집 · 보기 · 작업 · 창 · 도움말). Every enabled item runs a real action. */
export function MenuBar({ menus }: { menus: Menu[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open == null) return;
    const away = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(null);
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
      if (e.key === "ArrowRight") setOpen((o) => ((o ?? 0) + 1) % menus.length);
      if (e.key === "ArrowLeft") setOpen((o) => ((o ?? 0) + menus.length - 1) % menus.length);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const buttons = [...(root.current?.querySelectorAll<HTMLButtonElement>(".menu-pop > .menu-row > .menu-item:not(:disabled)") || [])];
        if (!buttons.length) return;
        e.preventDefault();
        const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
        buttons[(at + (e.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length].focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open, menus.length]);
  return (
    <div className="menubar" ref={root} role="menubar">
      {menus.map((m, i) => (
        <div key={m.label} className="menu-root">
          <button
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={open === i}
            className={"menu-top" + (open === i ? " open" : "")}
            onClick={() => setOpen(open === i ? null : i)}
            onMouseEnter={() => open != null && setOpen(i)}
          >
            {m.label}
          </button>
          {open === i && <Items items={m.items} close={() => setOpen(null)} />}
        </div>
      ))}
    </div>
  );
}
