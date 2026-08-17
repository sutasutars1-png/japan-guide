// Thin client for the AI-OS API. The UI works with embedded fake data even
// when the API is unreachable (Phase 1 guarantee); these helpers upgrade it to
// live data + live execution when the backend is up (Phase 2 seam).

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export async function fetchJSON<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback; // API down → keep the beautiful fake-data UI alive
  }
}

export type LogLine = { t: string; s: string };

// Shared WebSocket opener: connects to `path`, sends `payload`, streams log
// lines to onLine, and calls onDone once (on "stream closed" / error / close).
// Returns a cleanup function.
function openStream(
  path: string,
  payload: Record<string, unknown>,
  onLine: (line: LogLine) => void,
  onDone: () => void,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  const done = () => {
    if (!closed) {
      closed = true;
      onDone();
    }
  };
  try {
    const url = API_BASE.replace(/^http/, "ws") + path;
    ws = new WebSocket(url);
    ws.onopen = () => ws?.send(JSON.stringify(payload));
    ws.onmessage = (ev) => {
      try {
        const line = JSON.parse(ev.data) as LogLine;
        if (line.s === "stream closed") done();
        else onLine(line);
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onerror = () => done();
    ws.onclose = () => done();
  } catch {
    done();
  }
  return () => {
    closed = true;
    ws?.close();
  };
}

// Phase 2: run one command in the sandbox. approved=true means the human OK'd it.
export function streamExecution(
  onLine: (line: LogLine) => void,
  onDone: () => void,
  command?: string,
  approved = false,
): () => void {
  return openStream("/execution/stream", command ? { command, approved } : {}, onLine, onDone);
}

// Phase 4: give a goal and watch the PLAN→EXECUTE→OBSERVE loop drive.
export function streamAgent(
  onLine: (line: LogLine) => void,
  onDone: () => void,
  goal: string,
  maxIterations = 8,
  allowDomains?: string[],
): () => void {
  const payload: Record<string, unknown> = { goal, max_iterations: maxIterations };
  if (allowDomains && allowDomains.length) payload.allow_domains = allowDomains;
  return openStream("/agent/stream", payload, onLine, onDone);
}

// How the sandbox session is configured (persistence, file collection, materials).
export type SandboxInfo = {
  runtime: string; persistent_sandbox: boolean; collect_files: boolean;
  materials_mount: string; materials_present: boolean;
  default_allow_domains: string[]; deliverable_max_files: number; deliverable_max_bytes: number;
  web_fetch_enabled: boolean;
};
export const fetchSandboxInfo = () =>
  fetchJSON<SandboxInfo | null>("/execution/sandbox-info", null);

// ---- Connections (Phase 4): providers, keys, live-discovered models ----
export type Connection = {
  id: string; name: string; kind: "api" | "manual"; free: boolean;
  connected: boolean; key_hint: string; models: string[]; error: string | null;
};
export type ModelInfo = { model: string; provider: string; kind: string };

async function jsonReq<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { "content-type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return (await res.json()) as T;
}

export const deleteAgent = (id: string) =>
  fetch(`${API_BASE}/agents/${id}`, { method: "DELETE" }).then((r) => r.ok);

// Claude Code CLI subscription login (from the Connections card).
export type ClaudeAuth = { loggedIn: boolean; authMethod?: string; apiProvider?: string; error?: string };
export const fetchClaudeAuth = () => fetchJSON<ClaudeAuth>("/connections/claude-cli/auth", { loggedIn: false });
export const claudeLogin = () =>
  jsonReq<{ launched: boolean; hint?: string; error?: string }>("/connections/claude-cli/login", "POST");
export const claudeLogout = () =>
  jsonReq<{ ok: boolean; error?: string }>("/connections/claude-cli/logout", "POST");

export const fetchConnections = () => fetchJSON<Connection[]>("/connections", []);
export const fetchModels = () => fetchJSON<ModelInfo[]>("/models", []);
export const setConnKey = (id: string, key: string) =>
  jsonReq<Connection>(`/connections/${id}/key`, "PUT", { key });
export const refreshConn = (id: string) =>
  jsonReq<Connection>(`/connections/${id}/refresh`, "POST");
export const clearConnKey = (id: string) =>
  jsonReq<Connection>(`/connections/${id}/key`, "DELETE");
export const addManualModel = (id: string, model: string) =>
  jsonReq<Connection>(`/connections/${id}/models`, "POST", { model });
export const removeManualModel = (id: string, model: string) =>
  jsonReq<Connection>(`/connections/${id}/models`, "DELETE", { model });

// Presets (persisted): seed presets are read-only; custom ones (id "custom.*")
// can be edited/deleted and survive a restart.
export type Preset = { id: string; name: string; stage: string; skills: string[] };
export const createPreset = (name: string, stage: string, skills: string[]) =>
  jsonReq<Preset>("/presets", "POST", { name, stage, skills });
export const deletePreset = (id: string) =>
  fetch(`${API_BASE}/presets/${id}`, { method: "DELETE" }).then((r) => r.ok);
export const isCustomPreset = (id: string) => (id || "").startsWith("custom.");

// Flows (persisted): seed flows are read-only; custom ones (id "flow.custom.*")
// can be created/deleted.
export type Station = { agent: string; next: string };
export const createFlow = (name: string, stations: Station[], maxIterations = 10) =>
  jsonReq<Flow>("/flows", "POST", { name, stations, max_iterations: maxIterations });
export const deleteFlow = (id: string) =>
  fetch(`${API_BASE}/flows/${id}`, { method: "DELETE" }).then((r) => r.ok);
export const isCustomFlow = (id: string) => (id || "").startsWith("flow.custom.");
export const fetchFlows = () => fetchJSON<Flow[]>("/flows", []);

// Manual bridge: prompts waiting for a human to paste in/out of an API-less AI.
export type ManualPending = { id: string; title: string; prompt: string; created: number };
export const fetchManualPending = () => fetchJSON<ManualPending[]>("/manual/pending", []);
export const submitManual = (id: string, reply: string) =>
  jsonReq<{ ok: boolean }>("/manual/submit", "POST", { id, reply });

export type Flow = {
  id: string;
  name: string;
  max_iterations: number;
  stations: { agent: string; next: string }[];
};

// Phase 4 · stage 3c: run a goal through a multi-agent flow (Planner→Builder→…),
// each station handing its DONE report to the next. flowId picks the pipeline.
export function streamFlow(
  onLine: (line: LogLine) => void,
  onDone: () => void,
  goal: string,
  flowId = "flow.default",
): () => void {
  return openStream("/flow/stream", { goal, flow_id: flowId }, onLine, onDone);
}

// Phase 4: hand the goal to the orchestrator (統括AI) — it plans, then the
// workers are dispatched automatically. A pre-approved/edited `steps` plan skips
// the planning step.
export type PlanStep = { agent: string; task: string };
export function streamOrchestrate(
  onLine: (line: LogLine) => void,
  onDone: () => void,
  goal: string,
  orchestrator = "Planner",
  steps?: PlanStep[],
): () => void {
  const payload: Record<string, unknown> = { goal, orchestrator };
  if (steps && steps.length) payload.steps = steps;
  return openStream("/orchestrate/stream", payload, onLine, onDone);
}

// Ask the orchestrator for a plan without running it (for an editable checklist).
export const fetchPlan = (goal: string, orchestrator = "Planner") =>
  jsonReq<{ text: string; plan: PlanStep[] }>("/orchestrate/plan", "POST", { goal, orchestrator });

// ---- Deliverables (成果物): save a run's output, list, download -------------
export type Artifact = { agent: string; task: string; content: string };
export type DeliverableMeta = {
  id: string; title: string; goal: string; source: string;
  orchestrator: string | null; status: string; created: number; artifact_count: number;
};
export type Deliverable = DeliverableMeta & { artifacts: Artifact[] };

export const fetchDeliverables = () => fetchJSON<DeliverableMeta[]>("/deliverables", []);
export const fetchDeliverable = (id: string) =>
  jsonReq<Deliverable>(`/deliverables/${id}`, "GET");
export const deleteDeliverable = (id: string) =>
  fetch(`${API_BASE}/deliverables/${id}`, { method: "DELETE" }).then((r) => r.ok);

// Save a deliverable — either explicit artifacts, or raw log lines the store
// reconstructs into per-step artifacts (used to save agent/flow runs).
export const saveDeliverable = (body: {
  goal?: string; title?: string; source?: string; orchestrator?: string;
  artifacts?: Artifact[]; lines?: LogLine[];
}) => jsonReq<Deliverable>("/deliverables", "POST", body);

export type DeliverableFormat = "md" | "txt" | "json" | "zip";

// The download URL — a plain link the browser can fetch.
export const deliverableDownloadUrl = (id: string, format: DeliverableFormat = "md") =>
  `${API_BASE}/deliverables/${id}/download?format=${format}`;

// Fetch a URL and trigger a browser download, honoring the server's filename.
async function downloadFrom(url: string, fallbackName: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(res.statusText);
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="([^"]+)"/.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(objUrl);
}

// Download a whole deliverable (md | txt | json | zip).
export const downloadDeliverable = (id: string, format: DeliverableFormat = "md") =>
  downloadFrom(deliverableDownloadUrl(id, format), `${id}.${format}`);

// Download a single artifact (file or report) of a deliverable.
export const downloadArtifact = (id: string, index: number, format: "raw" | "txt" = "raw") =>
  downloadFrom(`${API_BASE}/deliverables/${id}/artifacts/${index}/download?format=${format}`,
    `${id}-${index}`);
