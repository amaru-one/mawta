## Purpose
SvelteKit SPA (Svelte 5, adapter-static, Bun, TypeScript) implementing the Yanai app's screens against the Go API. Mobile-first, autosave everywhere, Spanish UI text.

## Contents
- `src/` — application code (see its SPEC.md and children).
- `static/` — files served verbatim (see its SPEC.md).
- `package.json` / `bun.lock` — scripts: `dev`, `build`, `preview`, `check` (svelte-check), lint via `bun eslint .`. Dev-deps only; no runtime deps.
- `vite.config.ts` — Vite + SvelteKit; dev proxy routes `/api/*` (and `/healthz`) to the Go server so the app is same-origin in dev and prod.
- `tsconfig.json`, `eslint.config.js`, `.eslintrc.json`, `.prettierrc`, `.prettierignore`, `.npmrc` — toolchain config. `.prettierrc` loads `prettier-plugin-svelte` and maps `*.svelte` to the `svelte` parser; `.prettierignore` excludes `SPEC.md` — see Conventions.
- `.env.example` / `.env.local` — `PUBLIC_API_BASE_URL` (empty = same origin), `PUBLIC_TENANT_ID`, `PUBLIC_ACTOR_ID` (dev-auth headers baked into every request).
- `README.md` — SvelteKit boilerplate readme.
- `.claude/` — project skills (format, verify) and settings; `.vscode/`, `.svelte-kit/` — tool/generated, no specs.

## Inputs / Outputs
Consumes the yanai-server API under `/api/v1` with `X-Tenant-ID`/`X-Actor-ID` from the PUBLIC_ env vars. Produces a static build in `build/`, deployed under Caddy at `/srv/ui`.

## Conventions & Constraints
- Static SPA: no server-side code; adapter-static with SPA fallback (Caddy `try_files … /index.html`).
- CI gate: `bun run check`, `bun eslint .`, `bun run build` must pass. Prettier is **not** a gate — `bun prettier --check` has never been clean here, so treat it as a formatter you run on what you touched, not a verdict on the tree.
- **Prettier can format `.svelte` files, but most of them have never been formatted.** Before `prettier-plugin-svelte` was installed, every `.svelte` file failed with "No parser could be inferred" and was silently skipped; now they parse, and 13 of the 26 come back dirty. That is pre-existing drift, not a regression. Format the files your change touches and leave the rest — `bun prettier --write .` would rewrite half the components as noise around an unrelated diff, which is the same trap `.prettierignore` already had to close for `SPEC.md`.
- **Prettier never touches `SPEC.md`.** Its markdown printer inserts a blank line after every heading, which is not how the per-folder specs are written, so a `bun prettier --write .` rewrote every spec in the tree and buried the actual change in whitespace. The specs are prose under a protocol (`CLAUDE.md`), not code, and nothing gains from machine-formatting them.
- No real auth — tenant/actor are build-time constants; never point a build with real data at this.

## Change Log
- 2026-09-01: Added `prettier-plugin-svelte` (dev-dep) and wired it in `.prettierrc` with a `*.svelte` → `svelte` parser override. Until now Prettier could not parse a single `.svelte` file in this project — the `format` skill's `bun prettier --write .` errored on each one and formatted only the `.ts`/`.css`/`.json` around them, so the components had gone unformatted since the repo was created. 13 of 26 `.svelte` files are dirty as a result; they are deliberately left alone (see Conventions). No change to the gates: `bun run check` and `bun eslint .` still pass.
- 2026-08-29: `.prettierignore` now excludes `SPEC.md`. The `format` skill runs `bun prettier --write .`, which reformatted all 13 specs under `src/` as a side effect of an unrelated change; the noise had to be undone by hand. Two files, `src/lib/toast.ts` and `src/lib/notifications.ts`, are still flagged by `prettier --check` and were already flagged before this change — left alone rather than reformatted inside someone else's diff.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
