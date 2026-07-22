# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**yanay-ui** — A teacher's in-class lesson companion for tracking attendance, participation, and voice observations. Built with SvelteKit 5 + TypeScript (strict mode), IndexedDB persistence, no backend.

## Build & Development

```bash
npm run dev      # Start Vite dev server (http://localhost:5173)
npm run build    # Production build
npm run check    # Run svelte-check + TypeScript compilation
npm run check:watch  # Watch mode for type checking
```

Type checking must pass before committing. Use `npm run check:watch` during development.

## Code Style

- **TypeScript**: strict mode enforced (`noImplicitAny`, `strict: true`)
- **Imports**: Use `$lib/` alias for imports from `src/lib/` (configured in SvelteKit)
- **Formatting**: Prettier (configured in `.prettierrc`); runs automatically on edits
- **Linting**: ESLint for TypeScript/Svelte; runs before commits

## Git Workflow

**Commit style:**
- Descriptive, present-tense commit messages (e.g., "add voice note playback")
- **Do NOT include `Co-Authored-By: Claude` footer** — commits are by you, not Claude
- Pre-commit hook runs linting and type check; commit will fail if either fails

**Branch naming:** Use descriptive names (e.g., `feature/voice-tags`, `fix/attendance-sync`)

## SvelteKit Conventions

- **Routes**: File-based routing in `src/routes/`
- **Layout nesting**: Use `+layout.svelte` for nested layouts
- **Server logic**: Move backend logic to `+page.server.ts` or `+layout.server.ts` (though this project has no backend)
- **Stores**: Svelte stores in `src/lib/stores.ts` for shared state (currentSession, students, entries, notes, assessments)
- **Components**: Colocate in `src/lib/components/`
- **Types**: Centralize in `src/lib/types.ts` (Course, Student, Session, Block, Assessment, Entry, Note)

## IndexedDB & Persistence

- All data stored in IndexedDB (`src/lib/db.ts`)
- No async/await errors are shown to users; failures retry silently
- Mutations go through `src/lib/lesson.ts` orchestration layer
- Use typed store subscriptions; avoid direct DB access outside `db.ts`

## Testing

No test framework configured yet. When adding tests, run them with a clear command in this file.

## Performance Targets

- First paint: < 800ms cold start
- Full attendance pass (28 students): 60 seconds
- Tap response: instant (no lag)

## Non-Goals

- No scoring or grades on this screen
- No authentication
- No dark mode, settings, or onboarding
- No export or reporting

Refer to README.md for detailed feature list and architecture.
