// Which shell runs the UI, and what it may offer. One build serves all three:
//   desktop — PySide6 window (studio/desktop/app.py) injects window.__M4ML_DESKTOP__
//   web     — the web gateway (studio_web) serves index.html with <meta name="m4ml-platform" content="web">
//   dev     — a developer opening the local backend in a browser
// Hiding a control here is presentation only; the gateway and the web-mode backend refuse
// the same operations independently.
export type Platform = "desktop" | "web" | "dev";

export function platform(): Platform {
  if (typeof window !== "undefined" && window.__M4ML_DESKTOP__) return "desktop";
  if (
    typeof document !== "undefined" &&
    document.querySelector('meta[name="m4ml-platform"]')?.getAttribute("content") === "web"
  )
    return "web";
  return "dev";
}

export interface Capabilities {
  /** Choose a folder on this computer and analyse it in place. */
  serverFolders: boolean;
  /** Open a folder of the computer running the backend (logs, project folder). */
  openPaths: boolean;
  /** Show absolute paths of the backend computer. */
  serverPaths: boolean;
  /** Import COLMAP results, masks or meshes (not in the web MVP). */
  importExisting: boolean;
  /** Quit the application from the menu. */
  quit: boolean;
  /** Set the segmentation model file path. */
  modelPath: boolean;
}

export function capabilities(p: Platform = platform()): Capabilities {
  const local = p !== "web";
  return {
    serverFolders: local,
    openPaths: p === "desktop",
    serverPaths: local,
    importExisting: local,
    quit: p === "desktop",
    modelPath: local,
  };
}

/** Double-submit CSRF token the web gateway sets as a readable cookie. */
export function csrfToken(cookie: string = typeof document !== "undefined" ? document.cookie : ""): string {
  for (const part of cookie.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === "__Host-m4ml_csrf") return decodeURIComponent(value.join("="));
  }
  return "";
}

/** Turnstile site key the gateway publishes when new sessions need a bot check. */
export function turnstileSiteKey(): string | null {
  if (typeof document === "undefined") return null;
  return document.querySelector('meta[name="m4ml-turnstile"]')?.getAttribute("content") || null;
}
