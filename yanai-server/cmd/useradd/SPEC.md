## Purpose
Creates (or resets the password of) one account — a `users` row, a `memberships` row, and for `role=teacher` a `teachers` row. The only way to create the first account now that `yanai-server/seed/` is gone: no SQL file can hash a password, so this has to be Go.

## Contents
- `main.go` — one file, no subcommands. Flags:
  - `-tenant <uuid>` — required for account creation; the tenant must already exist (this tool does not create one). Not required with `-reset-password`, which addresses an existing account by `-username` alone.
  - `-username`, `-email`, `-given-name`, `-family-name` — required for account creation.
  - `-password <string>` — omit to be prompted (hidden, via `golang.org/x/term`); `-generate-password` mints one with `auth.NewSessionToken` and prints it once instead.
  - `-display-name` — defaults to `"given family"`.
  - `-role teacher|student|supervisor|admin` — default `teacher`.
  - `-title`, `-hired-on` (`YYYY-MM-DD`), `-employee-code` — `teachers` row fields.
  - `-no-teacher-profile` — skip the `teachers` row even for `role=teacher`.
  - `-reset-password` — update an existing `-username`'s password instead of creating anything; also revokes every live session for that user (`revoked_reason = 'password_change'`), the same policy `internal/repo/auth.go` documents for a self-service change.

## Inputs / Outputs
Input: flags, `DATABASE_URL` (via `internal/config`), a password from stdin or a flag. Output: the created `user_id`/`membership_id`/`teacher_id` printed to stdout, or `password reset` on `-reset-password`; a friendly message (not a raw Postgres error) on a duplicate username/email or a second membership for a user who already has one.

## Conventions & Constraints
- Runs as `db.WithSystemTx` (the pool's own connection role, not `WithAuthTx`) — this is provisioning tooling run by an operator, not a request-handling path, so it is exempt from the "never for request data" rule in `internal/db/SPEC.md`.
- **Insert order is forced by `users`' own RLS policy comment** (`migrations/00001_initial_schema.sql`): a membership must exist before the `users` row it names can be read back, but a membership references the user it belongs to — so this tool inserts `users` → `memberships` → `teachers`, all inside one transaction, exactly in that order.
- Creates **only the account.** It does not create a tenant, an academic year, terms, competencias, or classes — see Open Questions. A freshly created teacher can log in; the app will render an empty school until academic data is loaded some other way.
- Password errors from `internal/auth.ValidatePassword` (length) surface as-is; Postgres constraint violations are translated to a plain sentence for the three that are expected to happen in practice: `users_username_key`, `users_email_key`, `memberships_one_school_per_user`.

## Change Log
- 2026-09-11: Verified end-to-end against a throwaway Postgres: account creation, duplicate-username/email/one-school rejections, and `-reset-password`. Found and fixed two bugs in that pass — `-tenant` was unconditionally required even for `-reset-password`, which addresses an account by `-username` alone; and `memberships` needed its own `login_lookup` RLS policy alongside `users`' (see `migrations/SPEC.md` and `internal/db/SPEC.md`) because `ResolveMembership` reads it before a tenant is known, same as `FindLoginCandidate` reads `users`.
- 2026-09-11: Created for real authentication (`migrations/00002_auth.sql`), replacing the deleted `yanai-server/seed/`'s role of creating the first account. See `internal/httpapi/SPEC.md`, `internal/repo/SPEC.md`, `internal/auth/SPEC.md`.

## Open Questions
- **This tool creates an account, not a usable school.** The deleted seed also created the tenant itself, an academic year, terms, grade levels, subjects, competencias, sections, courses and class schedules — none of that is recreated here, by decision (see root `SPEC.md`). After `useradd`, the app has a teacher who can log in and an empty roster. Loading academic data is out of scope for this tool as it stands.
