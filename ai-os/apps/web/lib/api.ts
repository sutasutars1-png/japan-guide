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
): () => void {
  return openStream("/agent/stream", { goal, max_iterations: maxIterations }, onLine, onDone);
}

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
