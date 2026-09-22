## Purpose
The Yanai web app: a SvelteKit SPA (Svelte 5 runes, adapter-static, Bun, TypeScript) implementing the app's screens against the Go API. Mobile-first, autosave throughout, Spanish UI text.

## Contents
- `src/` — application code (see its SPEC.md and children).
- `static/` — files served verbatim; currently `robots.txt`, which allows crawling.
- `package.json` / `bun.lock` — scripts `dev`, `build`, `preview`, `prepare` (`svelte-kit sync`), `check` and `check:watch` (`svelte-check` against `tsconfig.json`). Linting runs as `bun eslint .`, with no script of its own. Dev-dependencies only; the app ships no runtime dependency.
- `vite.config.ts` — Vite plus the SvelteKit plugin. It forces runes mode for everything outside `node_modules`, configures the SPA build with `adapter-static({ fallback: 'index.html' })`, sets `envPrefix: ['VITE_', 'PUBLIC_']` so `PUBLIC_*` vars reach `import.meta.env` and a missing one stays `undefined` rather than failing the build, and proxies `/api` and `/healthz` to `http://localhost:8080` in dev. There is no separate `svelte.config.js`.
- `tsconfig.json` — extends the generated `.svelte-kit/tsconfig.json`, with `strict`, `checkJs` and `moduleResolution: 'bundler'`. Path aliases come from SvelteKit's own config.
- `eslint.config.js` — the flat config in use: `@eslint/js` recommended, a TypeScript block on `@typescript-eslint/parser`, a Svelte block on `svelte-eslint-parser` with `eslint-plugin-svelte`'s recommended rules, and ignores for `node_modules/`, `dist/`, `build/`, `.svelte-kit/` and `.output/`.
- `.eslintrc.json` — the legacy config, kept alongside the flat one.
- `.prettierrc` — tabs at width 2, single quotes, semicolons, `es5` trailing commas, 100-column width. It loads `prettier-plugin-svelte` and maps `*.svelte` to the `svelte` parser. `.prettierignore` excludes the build outputs and `SPEC.md`.
- `.npmrc` — `engine-strict=true`.
- `.env.example` / `.env.local` — `PUBLIC_API_BASE_URL`, empty for same origin. The session travels as an HttpOnly cookie the server sets on login, so there is no auth-related variable here.
- `README.md` — a one-line title.
- `.claude/` — project skills (`format`, `verify`) and settings. `.vscode/` and `.svelte-kit/` are tool and generated output.

## Inputs / Outputs
Consumes the yanai-server API under `/api/v1`, authenticated by the `yanai_session` HttpOnly cookie every request carries through `credentials: 'include'`. Produces a static build in `build/`, deployed under Caddy at `/srv/ui`.

## Conventions & Constraints
- A static SPA: no server-side code, and every route falls back to `index.html` (Caddy `try_files … /index.html`).
- The CI gate is `bun run check`, `bun eslint .` and `bun run build`. Prettier is a formatter rather than a gate: `bun prettier --check` reports 13 of the 26 `.svelte` files as dirty against the current config, so the tree is formatted file by file as changes touch it.
- Prettier leaves `SPEC.md` alone, through `.prettierignore`. Its markdown printer inserts a blank line after every heading, which is not how the per-folder specs are written.
- Auth is real: `POST /auth/login` sets the session cookie, `src/routes/login/` is the unguarded route, and the root layout gates every other route on a `GET /me` probe — see `src/routes/SPEC.md` and `src/lib/SPEC.md`.

## Open Questions
- None.
