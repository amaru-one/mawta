## SPEC PROTOCOL — MANDATORY, NO EXCEPTIONS

This project uses per-folder specs. A spec file named `SPEC.md` must exist in
every folder that contains source, analysis, or content files. These rules
override convenience, speed, or your own judgment about whether a spec is
"needed." They apply to every task, every session, every file change,
regardless of how small.

### RULE 1 — A SPEC MUST EXIST BEFORE YOU WORK IN A FOLDER
Before reading, writing, or editing any file inside a folder:
1. Check whether `SPEC.md` exists in that folder.
2. If it does NOT exist, STOP. Do not write code or content first.
   Create `SPEC.md` using the template below, ask me to confirm it if
   anything is ambiguous, then proceed.
3. If it DOES exist, you MUST open and read it in full before touching any
   other file in that folder. Do not skim. Do not assume you remember it
   from an earlier turn in this session — re-read it every time you re-enter
   that folder, since it may have changed.

### RULE 2 — THE SPEC IS SOURCE OF TRUTH, NOT THE CODE
If a file's behavior conflicts with what `SPEC.md` says, the spec wins.
Either fix the file to match the spec, or stop and tell me the spec itself
needs to change — never silently let them drift apart.

### RULE 3 — EVERY CHANGE MUST UPDATE THE SPEC, IN THE SAME TURN
Any time you create, edit, delete, or rename a file inside a folder, you
MUST update that folder's `SPEC.md` in the same response — not "later,"
not "if you remember," not only when asked. This includes:
- New functions, scripts, endpoints, datasets, or documents added
- Changed behavior, parameters, formats, or conventions
- Deleted or deprecated files
- Anything a future session would need to know to avoid re-breaking it

If a change has no spec-relevant impact (e.g. a typo fix, a comment,
formatting only), state explicitly: "No spec update needed — reason: X."
Do not skip the spec silently.

### RULE 4 — NEVER CLOSE OUT A TASK WITH A STALE SPEC
Before ending your turn, do a final check: does `SPEC.md` in every folder
you touched still accurately describe what's in that folder right now?
If not, fix it before responding to me. A task is not complete until specs
match reality.

### RULE 5 — SPECS CASCADE
If a change in one folder affects another folder's behavior or assumptions
(e.g. shared data format, shared function signature, shared conventions),
update the SPEC.md in every affected folder, not just the one you edited.

---

### SPEC.md TEMPLATE (use this structure for every new spec)

## Purpose
What this folder is for, one or two sentences.

## Contents
List of files in this folder and what each one does.

## Inputs / Outputs
What this folder consumes and produces (data formats, parameters, expected
files, dependencies on other folders).

## Conventions & Constraints
Rules specific to this folder — naming, format, must/must-not behaviors.

## Change Log
- YYYY-MM-DD: what changed and why (append-only, most recent at top)

## Open Questions
Anything ambiguous or pending a decision — remove once resolved.