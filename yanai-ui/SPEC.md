## Purpose
SvelteKit SPA (Svelte 5, adapter-static, Bun, TypeScript) implementing the six Yanai screens against the Go API. Mobile-first, autosave everywhere, Spanish UI text.

## Contents
- `src/` — application code (see its SPEC.md and children).
- `static/` — files served verbatim (see its SPEC.md).
- `package.json` / `bun.lock` — scripts: `dev`, `build`, `preview`, `check` (svelte-check), lint via `bun eslint .`. Dev-deps only; no runtime deps.
- `vite.config.ts` — Vite + SvelteKit; dev proxy routes `/api/*` (and `/healthz`) to the Go server so the app is same-origin in dev and prod.
- `tsconfig.json`, `eslint.config.js`, `.eslintrc.json`, `.prettierrc`, `.prettierignore`, `.npmrc` — toolchain config.
- `.env.example` / `.env.local` — `PUBLIC_API_BASE_URL` (empty = same origin), `PUBLIC_TENANT_ID`, `PUBLIC_ACTOR_ID` (dev-auth headers baked into every request).
- `CLAUDE.md` — currently just a title placeholder.
- `README.md` — SvelteKit boilerplate readme.
- `.claude/` — project skills (format, verify) and settings; `.vscode/`, `.svelte-kit/` — tool/generated, no specs.

## Inputs / Outputs
Consumes the yanai-server API under `/api/v1` with `X-Tenant-ID`/`X-Actor-ID` from the PUBLIC_ env vars. Produces a static build in `build/`, deployed under Caddy at `/srv/ui`.

## Conventions & Constraints
- Static SPA: no server-side code; adapter-static with SPA fallback (Caddy `try_files … /index.html`).
- CI gate: `bun run check`, `bun eslint .`, `bun run build` must pass.
- No real auth — tenant/actor are build-time constants; never point a build with real data at this.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- Should `CLAUDE.md` here get real content or be removed?
