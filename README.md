# yanay-ui — Lesson Screen

In-class teacher companion: record attendance, participation, and voice observations live during class.

Built with **SvelteKit** + **TypeScript** (strict mode), all state in **IndexedDB**. No backend, no auth. Teachers bookmark it and use it daily.

## Features

- **Lands directly on today's roster** — no splash, no modals, no loading spinners
- **Attendance tracking** — tap to toggle present ↔ absent (absent dims the row)
- **Participation cycles** — tap circles to mark none → low → good → excellent
- **Voice notes** — press-and-hold mic to record, release to save. Stores as audio blobs, plays back inline
- **Note tags** — mark notes as academic/behavior/logistics for later filtering
- **Set-all actions** — mark all students present or participated in one tap, with undo
- **Mode switching** — choose between "Just lesson" / "Lesson + quiz" / "Assessment only" without losing data
- **Full persistence** — every action autosaves to IndexedDB. Close the browser, come back — everything is exactly as left
- **Responsive** — phone (390px), tablet (768px), desktop (1200px). Touch-first.
- **No errors** — IndexedDB operations retry silently; no error UI ever shown

## Tech Stack

- **SvelteKit** (Svelte 5) + **TypeScript** strict mode
- **IndexedDB** (typed, silent retry)
- **CSS custom properties** design system (edX-inspired palette)
- **Web Audio API** for reliable audio playback (fix for MediaRecorder blob issues)
- **Responsive design** — mobile-first, 390px and up

## Run

```sh
npm install
npm run dev
```

Lands directly on Math 8B with 28 seeded students and a default 10:00–12:00 lesson.

## Design System

**Colors** — edX-inspired:
- Primary: `#0075B4` (teal, trustworthy, energetic)
- Success: `#2ECC71` (green, present/good)
- Danger: `#E74C3C` (red, absent/problems)
- Accent: `#E8713B` (warm orange, excellent)
- Neutrals: clean grays, off-white backgrounds

**Spacing** — 8px base unit scale (xs, sm, md, lg, xl)

**Interactions:**
- 44px minimum tap targets
- No spinners, no progress bars
- Immediate visual feedback on every tap (scale 0.95x)
- Toast notifications for bulk actions (undo available)
- Undo for: set-all, note deletion

## Data Model

```ts
Course | Student | Session | Block (lesson | assessment)
Assessment | Entry (one per student per session) | Note (audio blob + optional transcript + tag)
```

**Critical:** No scores on this screen. Scores belong on the grade screen.

## Architecture

```
src/lib/
  types.ts          → Course, Student, Session, Block, Assessment, Entry, Note
  db.ts             → Typed IndexedDB layer (stores: courses, students, sessions, entries, notes)
  seed.ts           → First-load seeding (Math 8B, 28 students, 2 assessments)
  stores.ts         → Svelte stores (currentSession, students, entries, notes, assessments)
  lesson.ts         → Orchestration (bootstrap, mutations, undo, mode switching)
  recorder.ts       → MediaRecorder + Web Audio (duration recovery, playback)
  transcribe.ts     → Stub hook for future Whisper API
  haptics.ts        → navigator.vibrate (tap, record, success feedback)
  toast.ts          → Toast notifications with optional undo
  components/       → LessonScreen, Header, SetAllBar, RosterRow, AttendanceControl,
                      ParticipationControl, MicButton, VoiceNotePlayer
src/app.css         → Design system (colors, spacing, shadows, animations, keyframes)
```

## Voice Notes — The Core UX

- **Record** — press-and-hold mic, visual feedback (pulsing, duration counter), release to save
- **Holds < 400ms are discarded silently** (mis-taps)
- **Play** — tap note to play audio inline (Web Audio playback, position timer)
- **Delete** — long-press (500ms) to confirm, undo via toast
- **Tag** — optional academic/behavior/logistics marking
- **Multiple per student** — common and supported (stack vertically, newest first)

## Non-Goals

- No score/grade input (different screen)
- No authentication
- No other screens (work queue, home, grades, student view)
- No risk detection or analytics
- No real transcription (stub only)
- No settings, dark mode, or onboarding
- No export or reporting

This screen owns the first 10 minutes of the teacher's workflow: arrive, record, leave.

## Performance

- **First paint:** < 800ms cold start
- **Full pass:** 28 students marked (attendance + participation) in 60 seconds
- **Tap response:** instant, no lag
- **Gestures:** press-and-hold, swipe (future: smooth scroll)

## Browser Support

- Chrome/Edge (Web Audio, MediaRecorder)
- Firefox (Web Audio, MediaRecorder)
- Safari (iOS 14+, limited MediaRecorder support but gracefully falls back)
