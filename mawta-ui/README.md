# Mawta

## Term planning against the real API

The term-planning flow (`src/routes/class/[courseId]/plan/**`) is hidden
unless `PUBLIC_PLANNING_ENABLED=true`: both the "Plan del trimestre" row in
the class panel and every `/plan` URL (`plan/+layout.ts` redirects to the
class panel).

To run it against the real server:

1. Start `mawta-server` with the worker on (`WORKER_ENABLED=true`, the
   default). "✦ Generar con Mawta" also needs `ANTHROPIC_API_KEY`; without it
   the generation routes answer `agent_unavailable` and the screens offer
   manual creation only ("Escribirlo yo"). Set `SESSION_COOKIE_SECURE=false`
   for plain `http://localhost` (Safari refuses Secure cookies there).
2. In `mawta-ui/.env.local`: `PUBLIC_PLANNING_ENABLED=true` and leave
   `PUBLIC_PLANNING_API` empty.
3. `bun install && bun run dev`. The dev server proxies `/api` to
   `API_PROXY_TARGET` (default `http://localhost:8080`).

`PUBLIC_PLANNING_API=mock` swaps the planning endpoints for an in-memory mock
(`src/lib/api/mock/planning.ts`) that follows the same contract, for UI work
without a server.
