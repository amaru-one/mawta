## Purpose
Gives the database-backed tests a real PostgreSQL to run against: creates a throwaway database, migrates it with the project's own goose migration, seeds deterministic fixtures, and drops the whole thing afterwards. Test-only — nothing here is imported by `cmd/` or by any non-test file.

## Contents
- `dbtest.go` — `Main(m)` (call from each test package's `TestMain`; creates and drops the database once per test binary), `Setup(t)` returning `*Env`, and `Env` carrying the two pools plus the seeded ids.
- `fixture.sql` — the deterministic seed, applied once after the migration. Ported from the demo seed deleted in `a1f3320` (`yanai-server/seed/seed_demo_tenant.sql`), trimmed to what tests need and extended to two tenants.
- `fixture.go` — the fixed UUIDs of `fixture.sql` as Go constants, so a test names a row instead of querying for it.

## Inputs / Outputs
**Input:** `YANAI_TEST_ADMIN_URL` — a superuser connection to any PostgreSQL 16. Its database is only ever connected to in order to `create database`; it is never written to and never dropped. Unset means every database test skips.

**Optional:** `YANAI_TEST_KEEP=1` retains the database after the run and prints its name, for debugging a failure.

**Output:** `*Env` with `App` (a pool connected as the non-owner `yanai_app`), `Admin` (the superuser pool, for fixture setup and for assertions that must see past RLS), and `Fx` (the fixture ids).

## Conventions & Constraints
- **Never call `internal/config.Load()`.** It runs `godotenv.Load()`, which would pull in the developer's `.env` and with it a live `DATABASE_URL`. Tests read `YANAI_TEST_ADMIN_URL` directly and nothing else.
- **Only ever drop a database this package created.** The name is generated as `yanai_test_<hex>` and checked against that shape before any `drop database`. There is no code path that drops a name this package did not mint.
- **The migration runs as the superuser, in one goose invocation, against an empty database.** `00001` does `create extension` (superuser only) and `alter default privileges`, which confers rights only on tables created afterwards by that same role. Split it across roles or connections and `yanai_app` silently ends up able to read nothing.
- **`alter role yanai_app … password` is required after migrating.** `00001` creates the role with `login` and no password. The role is cluster-wide, so this is once per cluster, not once per database.
- **Tests run against `Env.App`, not `Env.Admin`.** Connecting as `yanai_app` is what proves the `GRANT`s are right. An admin pool inside `WithTenantTx` still enforces RLS — the helper does `set local role yanai_app` — but it would not catch a missing grant, so it would pass a broken schema.
- **Skips must be loud, and CI must not rely on that.** Every skip names the missing variable, and `Main` prints a banner to stderr. But `go test` suppresses a passing package's output unless `-v`, so a bare `go test ./...` still just prints `ok` — the banner shows under `go test -v` and in CI logs. The real guarantee is therefore CI: it always sets `YANAI_TEST_ADMIN_URL`, so a run that skipped the database cannot be merged, whatever a local run happens to print.
- Fixtures are applied by the **admin** pool, which as superuser bypasses RLS. Seeding is not the thing under test; isolating it would only make the fixture harder to read.
- Teardown is dropping the database, not deleting rows. `events` carries a `forbid_mutation` trigger on DELETE, so row-wise cleanup is impossible by design.

## Open Questions
- None.
