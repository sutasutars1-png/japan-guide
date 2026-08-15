# Run modes — where the `api` process runs (the UI is identical either way)

The web UI experience is the same in both modes: open http://localhost:3000, type
a goal into the 🧭 command bar, watch the orchestrator + workers run. The only
difference is **where the `api` process runs**, which decides whether the local
`claude` CLI is reachable.

## Mode A — all in Docker (default): `START-AI-OS.bat`
`docker compose up --build` runs db + api + web in containers.
- ✅ Simplest; workers via **Gemini** (register the key in Connections) work fully.
- ⛔ **`claude-cli` shows "未検出"** — the api container (Linux) has no `claude`
  binary and no login. Use Gemini for the orchestrator, or `claude-web` (manual
  copy-paste) for Claude.

## Mode B — api on the host: `START-AI-OS-CLAUDE.bat`
db + web run in Docker; **`api` runs on your PC** with `uvicorn`.
- Requires **Docker**, the **`claude`** CLI (logged in), and **Python 3.11+** on
  the host.
- The api shells out to **your own logged-in `claude`** → automatic Claude
  orchestrator, **subscription (no API charge), no token injection** (this is the
  decided #5 path; mounting `~/.claude` into a container was rejected as
  ToS-grey).
- Set **Planner → Model = `claude-cli`** in Agents; workers stay `gemini-*`.
- The browser still talks to `http://localhost:8000` (now the host api), so the
  UI is unchanged.

### Notes for Mode B
- Keys you save in Connections persist to the host `ai-os/.env` and are reloaded
  on restart (`load_env_file` at boot). The Gemini key you set while in Mode A
  lived in the container and is gone — set it once more here.
- Stop with `STOP-AI-OS.bat` (db/web) + close the api window (Ctrl+C).
- `claude-cli` billing safety is unchanged: `ANTHROPIC_API_KEY` is stripped from
  the CLI's env so it uses the subscription, never metered API.
