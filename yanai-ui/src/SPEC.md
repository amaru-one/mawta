## Purpose
SvelteKit app root: global styles, HTML shell, ambient types, plus the `lib/` and `routes/` trees.

## Contents
- `app.html` — HTML shell.
- `app.css` — global stylesheet: design tokens (colors, spacing, typography) and base styles for the whole app, including the `button` and `a` element resets (every link here is a nav row or card with its own styling, so none want the browser's blue underline).
- `app.d.ts` — SvelteKit ambient type declarations.
- `lib/` — stores, API layer, components, screen logic (see its SPEC.md).
- `routes/` — the app's screens (see its SPEC.md).

## Inputs / Outputs
Compiled by Vite/SvelteKit into the static build.

## Conventions & Constraints
- Styling is plain CSS in `app.css` + component `<style>` blocks; no CSS framework.

## Change Log
- 2026-09-08: **The palette lost its greys and its black.** The whole neutral ladder moved onto the aurora's hue (indigo ~272°, chroma falling as lightness rises): `--surface-1` `#e2e2e2` → `#e8eaf7`, `--border` → `#e4e6f4`, `--border-strong` `#4a4a4a` → `#b2b7d2`, `--text-secondary` `#4a4a4a` → `#545a9c`, `--text-muted`/`--text-faint` from `rgba(74,74,74,…)` to `#6f74a4`/`#a3a8c8`, the `--fill-*` blacks to the new `--ink-deep` (`#2c3178`), and every `rgba(20,20,20,…)` shadow to `rgba(35,40,90,…)`. Only the page white is untinted. **`--text-primary` is now `--aurora-deep` itself (`#4a5fd6`)**, which inverts how the type hierarchy works: the ink is no longer the darkest tone — `--text-secondary` is (6.4:1 against the ink's 5.4:1) — and reads as louder because it is *more saturated*, not because it is deeper. Darkening the primary to "fix" that would break the system; the comment in `app.css` says so. Three tokens are new: `--ink-deep` (the darkest tone the app owns, for a filled surface with white text), `--hair` (the rule inside a tinted card and under the top bar, where `--border` disappears) and the `--gradient-action` / `--gradient-tile` / `--shadow-action` trio, declared once because a dozen places draw them. Primitives changed with the tokens: `.topbar` is a 64px band closed by `--hair`, `.eyebrow` is mono 10/700/0.1em uppercase, `.pill-dark`/`.btn-dark`/`.btn-block.btn-primary` carry the action gradient, `.pill-light`/`.btn-block` the tint, `.icon-tile` the tile gradient, `.lvl` became a disc, `.body`'s gutter went 16 → 20px, and `.screen-title`/`.screen-sub`/`.context-card`/`.grow` were added. `.grow` in particular was a documented convention that had never been defined globally, so four screens rendered their trailing chevron hugging the text instead of at the row's edge. Source of truth: the design canvas «Yanai en estilo burbuja». Cascade: `lib/components/`, every route.
- 2026-09-04: `app.css` gained the **AI aurora** group — `--aurora-1` (`#7c9bff`), `--aurora-2` (`#7cf7d9`), `--aurora-3` (`#9b7cff`), `--aurora-deep` (`#4a5fd6`) and `--aurora-tint` (`#f2f2fb`). They are the accent's neighbouring hues either side of `--fill-accent`, so the lesson screen's Siri-like recording orb reads as the same voice as the AI accent rather than as a second brand colour. `--aurora-deep` exists because `--text-accent` is not legible on `--aurora-tint`. **Scope is deliberately narrow**: `RecordBubble` and the lesson screen's context card and "Ir a …" button are the only consumers, and nothing else should reach for them — a colour that appears outside the recording stage stops signalling the recording stage. Cascade from `lib/components/RecordBubble.svelte` and `routes/class/[courseId]/lesson/[sessionId]/`.
- 2026-09-04: `app.css` gained one token, `--text-faint` (`rgba(74, 74, 74, 0.35)`). It is one step past `--text-muted` and exists for the *unset* member of a set whose other members are already muted — an unpicked level in `ScoreRuler`'s tick row, a competencia with no nivel in `CompetencyIndex`. Reusing `--text-muted` there could not distinguish "present but not chosen" from "chosen but secondary", and dropping to `disabled` opacity would have said the control was dead. Cascade from `lib/components/`.
- 2026-09-02: `app.css` lost `.chip`, `.chip-ok` and `.chip-bad`. Their only consumer anywhere in the app was the class dashboard's "Clases anteriores" cards, whose chips were removed — one of them (`24/26 presente`) had been reporting a number nothing has written since attendance capture left the app. The `--bg-success` / `--bg-danger` tokens they read stay: other screens still use them. Cascade from `routes/class/[courseId]/`.
- 2026-09-02: `app.css` lost `.circ` and `@keyframes record-pulse`, whose sole consumer was the deleted `MicButton.svelte`, and `@keyframes ripple`, which was **already orphaned before this change** — nothing had referenced it for some time; it went out with the pass that made it visible. Cascade from `lib/components/`.
- 2026-08-29: Dropped `.part` / `.part span` (the lesson roster's participation dots) and `@keyframes pulse-scale`, its only animation, from `app.css` — the control they styled is gone. Cascade from `lib/components/`.
- 2026-08-27: Added the missing `a` reset to `app.css`. Anchors had been rendering with the browser default blue underline wherever a route styled the row but not the link colour — visible on the class dashboard's nav rows. `button` already had the equivalent reset; `a` had simply been overlooked.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
