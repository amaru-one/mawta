## Purpose
SvelteKit SPA (Svelte 5, adapter-static, Bun, TypeScript) implementing the Yanai app's screens against the Go API. Mobile-first, autosave everywhere, Spanish UI text.

## Contents
- `src/` — application code (see its SPEC.md and children).
- `static/` — files served verbatim (see its SPEC.md).
- `package.json` / `bun.lock` — scripts: `dev`, `build`, `preview`, `check` (svelte-check), lint via `bun eslint .`. Dev-deps only; no runtime deps.
- `vite.config.ts` — Vite + SvelteKit; dev proxy routes `/api/*` (and `/healthz`) to the Go server so the app is same-origin in dev and prod.
- `tsconfig.json`, `eslint.config.js`, `.eslintrc.json`, `.prettierrc`, `.prettierignore`, `.npmrc` — toolchain config. `.prettierrc` loads `prettier-plugin-svelte` and maps `*.svelte` to the `svelte` parser; `.prettierignore` excludes `SPEC.md` — see Conventions.
- `.env.example` / `.env.local` — `PUBLIC_API_BASE_URL` (empty = same origin). No auth-related vars any more: the session travels as an HttpOnly cookie the server sets on login, not a build-time header.
- `README.md` — SvelteKit boilerplate readme.
- `.claude/` — project skills (format, verify) and settings; `.vscode/`, `.svelte-kit/` — tool/generated, no specs.

## Inputs / Outputs
Consumes the yanai-server API under `/api/v1`, authenticated by the `yanai_session` HttpOnly cookie every request carries (`credentials: 'include'`). Produces a static build in `build/`, deployed under Caddy at `/srv/ui`.

## Conventions & Constraints
- Static SPA: no server-side code; adapter-static with SPA fallback (Caddy `try_files … /index.html`).
- CI gate: `bun run check`, `bun eslint .`, `bun run build` must pass. Prettier is **not** a gate — `bun prettier --check` has never been clean here, so treat it as a formatter you run on what you touched, not a verdict on the tree.
- **Prettier can format `.svelte` files, but most of them have never been formatted.** Before `prettier-plugin-svelte` was installed, every `.svelte` file failed with "No parser could be inferred" and was silently skipped; now they parse, and 13 of the 26 come back dirty. That is pre-existing drift, not a regression. Format the files your change touches and leave the rest — `bun prettier --write .` would rewrite half the components as noise around an unrelated diff, which is the same trap `.prettierignore` already had to close for `SPEC.md`.
- **Prettier never touches `SPEC.md`.** Its markdown printer inserts a blank line after every heading, which is not how the per-folder specs are written, so a `bun prettier --write .` rewrote every spec in the tree and buried the actual change in whitespace. The specs are prose under a protocol, not code, and nothing gains from machine-formatting them.
- Real auth: `POST /auth/login` sets the session cookie, `src/routes/login/` is the only unguarded route, and the root layout gates every other route on a `GET /me` probe — see `src/routes/SPEC.md` and `src/lib/SPEC.md`.

## Open Questions
- None.
