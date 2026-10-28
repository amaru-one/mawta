# Mawta

## Running the UI against the server

The term-planning flow lives in `src/routes/class/[courseId]/plan/**` and is
always on: the "Plan del trimestre" row in the class panel opens it.

1. Start `mawta-api` with the worker on (`WORKER_ENABLED=true`, the
   default). "✦ Generar con Mawta" also needs a model for the agent
   (`PLANNING_AGENT_MODEL`, `CONCLUSIONS_AGENT_MODEL`; see
   `mawta-api/.env.example`); without one the generation routes answer
   `agent_unavailable` and the screens offer
   manual creation only ("Escribirlo yo"). Set `SESSION_COOKIE_SECURE=false`
   for plain `http://localhost` (Safari refuses Secure cookies there).
2. `bun install && bun run dev`. The dev server proxies `/api` to
   `API_PROXY_TARGET` (default `http://localhost:8080`).
