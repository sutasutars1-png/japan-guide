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

// Open a live execution stream. Returns a cleanup function.
// onLine is called per log line; onDone when the stream closes.
export function streamExecution(
  onLine: (line: LogLine) => void,
  onDone: () => void,
  command?: string,
  approved = false,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  try {
    const url = API_BASE.replace(/^http/, "ws") + "/execution/stream";
    ws = new WebSocket(url);
    ws.onopen = () => {
      // No command → the server replays the scripted demo live.
      // approved=true means the human OK'd this exact command in the modal.
      ws?.send(JSON.stringify(command ? { command, approved } : {}));
    };
    ws.onmessage = (ev) => {
      try {
        const line = JSON.parse(ev.data) as LogLine;
        if (line.s === "stream closed") {
          onDone();
        } else {
          onLine(line);
        }
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onerror = () => {
      if (!closed) onDone();
    };
    ws.onclose = () => {
      if (!closed) onDone();
    };
  } catch {
    onDone();
  }
  return () => {
    closed = true;
    ws?.close();
  };
}
