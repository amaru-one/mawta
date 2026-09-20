package db_test

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"yanai-server/internal/db"
	"yanai-server/internal/dbtest"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

func tenantA(env *dbtest.Env) db.TenantCtx {
	return db.TenantCtx{
		TenantID:  env.Fx.TenantA,
		ActorID:   env.Fx.UserQuispe,
		TeacherID: env.Fx.TeacherQuispe,
		RequestID: "test-request",
		Role:      "teacher",
	}
}

func tenantB(env *dbtest.Env) db.TenantCtx {
	return db.TenantCtx{
		TenantID:  env.Fx.TenantB,
		ActorID:   env.Fx.UserFlores,
		TeacherID: env.Fx.TeacherFlores,
		RequestID: "test-request",
		Role:      "teacher",
	}
}

// --------------------------------------------------------------- the GUCs --

func TestWithTenantTxSetsRoleAndGUCs(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	tc := tenantA(env)

	var role, tenant, actor, request string
	err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `
			select current_user,
			       coalesce(current_setting('app.tenant_id', true), ''),
			       coalesce(current_setting('app.actor_id', true), ''),
			       coalesce(current_setting('app.request_id', true), '')`).Scan(&role, &tenant, &actor, &request)
	})
	if err != nil {
		t.Fatalf("WithTenantTx: %v", err)
	}

	if role != "yanai_app" {
		t.Errorf("current_user = %q, want yanai_app", role)
	}
	if tenant != env.Fx.TenantA.String() {
		t.Errorf("app.tenant_id = %q, want %s", tenant, env.Fx.TenantA)
	}
	if actor != env.Fx.UserQuispe.String() {
		t.Errorf("app.actor_id = %q, want %s", actor, env.Fx.UserQuispe)
	}
	if request != "test-request" {
		t.Errorf("app.request_id = %q, want test-request", request)
	}
}

// The GUCs are SET LOCAL, so they evaporate with the transaction. If they
// leaked onto the pooled connection, the next request on it would inherit
// another tenant's scope.
func TestTenantContextDoesNotOutliveItsTransaction(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	if err := env.App.WithTenantTx(ctx, tenantA(env), func(tx pgx.Tx) error { return nil }); err != nil {
		t.Fatalf("WithTenantTx: %v", err)
	}

	// Exhaust the pool's connections so this is not merely a different one.
	for i := 0; i < 5; i++ {
		var tenant string
		if err := env.App.Pool.QueryRow(ctx, `select coalesce(current_setting('app.tenant_id', true), '')`).Scan(&tenant); err != nil {
			t.Fatalf("read app.tenant_id on the raw pool: %v", err)
		}
		if tenant != "" {
			t.Fatalf("app.tenant_id leaked out of its transaction as %q", tenant)
		}
	}
}

// Every read of a GUC here goes through coalesce(..., ''). current_setting
// with missing_ok returns NULL on a connection that has never set the setting
// and '' on one that has, so without the coalesce these assertions depend on
// which pooled connection they land on and on what ran before them — which is
// exactly the flakiness `go test -shuffle=on` exists to surface.

// A system/job actor has no user. The GUC must be empty rather than the zero
// UUID, because app.current_actor_id() does nullif(…, ”)::uuid and would
// otherwise record 00000000-… as a real actor on every audited row.
func TestZeroActorIDBecomesAnEmptyGUC(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	tc := db.TenantCtx{TenantID: env.Fx.TenantA, RequestID: "job:test"}

	var actor string
	var resolved *uuid.UUID
	err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`select coalesce(current_setting('app.actor_id', true), ''), app.current_actor_id()`).Scan(&actor, &resolved)
	})
	if err != nil {
		t.Fatalf("WithTenantTx: %v", err)
	}
	if actor != "" {
		t.Errorf("app.actor_id = %q, want empty", actor)
	}
	if resolved != nil {
		t.Errorf("app.current_actor_id() = %v, want NULL", resolved)
	}
}

func TestWithAuthTxSetsAuthLookupAndNoTenant(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	var role, lookup, tenant string
	err := env.App.WithAuthTx(ctx, "req-auth", func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `
			select current_user,
			       coalesce(current_setting('app.auth_lookup', true), ''),
			       coalesce(current_setting('app.tenant_id', true), '')`).Scan(&role, &lookup, &tenant)
	})
	if err != nil {
		t.Fatalf("WithAuthTx: %v", err)
	}
	if role != "yanai_app" {
		t.Errorf("current_user = %q, want yanai_app", role)
	}
	if lookup != "on" {
		t.Errorf("app.auth_lookup = %q, want on", lookup)
	}
	if tenant != "" {
		t.Errorf("app.tenant_id = %q, want empty — the tenant is the result of the lookup, not an input", tenant)
	}
}

// WithSystemTx changes nothing: no role drop, no GUCs. Its reach is a property
// of the connection string, not of the function. SPEC.md says so; this holds
// the code to it.
func TestWithSystemTxSetsNothing(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	var tenant, actor, lookup string
	err := env.App.WithSystemTx(ctx, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `
			select coalesce(current_setting('app.tenant_id', true), ''),
			       coalesce(current_setting('app.actor_id', true), ''),
			       coalesce(current_setting('app.auth_lookup', true), '')`).Scan(&tenant, &actor, &lookup)
	})
	if err != nil {
		t.Fatalf("WithSystemTx: %v", err)
	}
	if tenant != "" || actor != "" || lookup != "" {
		t.Errorf("WithSystemTx set GUCs (tenant=%q actor=%q lookup=%q); it must set none", tenant, actor, lookup)
	}
}

// ------------------------------------------------------------- isolation --

// The isolation failure mode that matters: an unscoped query returns zero rows
// and NO error. A test that only checked err == nil would pass against a
// completely broken tenant boundary, which is why every assertion here counts
// rows.
func TestUnscopedQueryReturnsNoRowsRatherThanFailing(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	tx, err := env.App.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	if _, err := tx.Exec(ctx, "set local role yanai_app"); err != nil {
		t.Fatalf("set role: %v", err)
	}

	for _, table := range []string{"students", "classes", "teachers", "scores", "assessments"} {
		var n int
		if err := tx.QueryRow(ctx, `select count(*) from `+table).Scan(&n); err != nil {
			t.Fatalf("count %s without a tenant: %v — expected zero rows, not an error", table, err)
		}
		if n != 0 {
			t.Errorf("%s returned %d rows with no app.tenant_id set; RLS is not isolating", table, n)
		}
	}
}

func TestTenantsCannotSeeEachOther(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	count := func(tc db.TenantCtx, query string, args ...any) int {
		t.Helper()
		var n int
		if err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
			return tx.QueryRow(ctx, query, args...).Scan(&n)
		}); err != nil {
			t.Fatalf("query: %v", err)
		}
		return n
	}

	// Each tenant sees its own rows...
	if n := count(tenantA(env), `select count(*) from students`); n != 5 {
		t.Errorf("tenant A sees %d students, want 5", n)
	}
	if n := count(tenantB(env), `select count(*) from students`); n != 1 {
		t.Errorf("tenant B sees %d students, want 1", n)
	}

	// ...and none of the other's, even asked for by primary key.
	if n := count(tenantB(env), `select count(*) from students where id = $1`, env.Fx.Students[0]); n != 0 {
		t.Error("tenant B can read a tenant A student by id")
	}
	if n := count(tenantA(env), `select count(*) from students where id = $1`, env.Fx.StudentB); n != 0 {
		t.Error("tenant A can read a tenant B student by id")
	}
	if n := count(tenantB(env), `select count(*) from classes where id = $1`, env.Fx.ClassMat5B); n != 0 {
		t.Error("tenant B can read tenant A's class by id")
	}
	if n := count(tenantB(env), `select count(*) from scores where id = $1`, env.Fx.ScoreOne); n != 0 {
		t.Error("tenant B can read a tenant A score by id")
	}
	if n := count(tenantB(env), `select count(*) from tenants where id = $1`, env.Fx.TenantA); n != 0 {
		t.Error("tenant B can read tenant A's own tenants row")
	}
}

// FORCE ROW LEVEL SECURITY applies to writes too: the with-check half of the
// policy stops one tenant planting a row in another.
func TestATenantCannotWriteIntoAnother(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	err := env.App.WithTenantTx(ctx, tenantB(env), func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`insert into students (tenant_id, student_code, given_name, paternal_surname)
			 values ($1, 'EST-SMUGGLED', 'Mal', 'Actor')`, env.Fx.TenantA)
		return err
	})
	if err == nil {
		t.Fatal("tenant B inserted a student into tenant A")
	}

	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
		t.Errorf("got %v, want an RLS policy violation (42501)", err)
	}
}

// jobs and user_sessions deliberately carry no RLS policy. That is documented
// as intentional, so it should be asserted rather than left to be rediscovered
// as a suspected hole.
func TestOnlyJobsAndUserSessionsLackAnRLSPolicy(t *testing.T) {
	env := dbtest.Setup(t)

	rows, err := env.Admin.Pool.Query(context.Background(), `
		select c.relname from pg_class c
		  join pg_namespace n on n.oid = c.relnamespace
		 where n.nspname = 'public' and c.relkind in ('r','p')
		   and not c.relispartition and not c.relrowsecurity
		 order by c.relname`)
	if err != nil {
		t.Fatalf("list tables without RLS: %v", err)
	}
	defer rows.Close()

	var got []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatalf("scan: %v", err)
		}
		got = append(got, name)
	}

	want := map[string]bool{"goose_db_version": true, "jobs": true, "user_sessions": true}
	for _, name := range got {
		if !want[name] {
			t.Errorf("%s has no RLS policy and is not one of the three that should lack one", name)
		}
		delete(want, name)
	}
	for name := range want {
		t.Errorf("%s was expected to have no RLS policy but does", name)
	}
}

// user_sessions has no policy, so its isolation is structural: the composite
// FK (tenant_id, membership_id) makes a cross-tenant session row impossible to
// insert in the first place.
func TestCrossTenantSessionRowIsRejectedByTheCompositeFK(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	// Tenant B's id against tenant A's membership: the pairing does not exist.
	var membershipA uuid.UUID
	if err := env.Admin.Pool.QueryRow(ctx,
		`select id from memberships where user_id = $1`, env.Fx.UserQuispe).Scan(&membershipA); err != nil {
		t.Fatalf("find Quispe's membership: %v", err)
	}

	_, err := env.Admin.Pool.Exec(ctx, `
		insert into user_sessions (token_hash, user_id, tenant_id, membership_id, role, expires_at)
		values ($1, $2, $3, $4, 'teacher', now() + interval '1 hour')`,
		[]byte("cross-tenant-token-hash"), env.Fx.UserQuispe, env.Fx.TenantB, membershipA)
	if err == nil {
		t.Fatal("a session row pairing tenant B with a tenant A membership was accepted")
	}

	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "23503" {
		t.Errorf("got %v, want a foreign key violation (23503)", err)
	}
}

// --------------------------------------------------------- error mapping --

func TestMapError(t *testing.T) {
	for _, tc := range []struct {
		name       string
		err        error
		wantStatus int
		wantCode   string
	}{
		{"no rows is a 404", pgx.ErrNoRows, 404, "not_found"},
		{"unique violation is a 409", &pgconn.PgError{Code: "23505"}, 409, "unique_violation"},
		{"check violation is a 422", &pgconn.PgError{Code: "23514"}, 422, "check_violation"},
		{"foreign key violation is a 422", &pgconn.PgError{Code: "23503"}, 422, "foreign_key_violation"},
		{"restrict violation is a 409", &pgconn.PgError{Code: "23001"}, 409, "restrict_violation"},
		{"exclusion violation is a 409", &pgconn.PgError{Code: "23P01"}, 409, "exclusion_violation"},
		{"an unmapped pg error is a 500", &pgconn.PgError{Code: "08006"}, 500, "database_error"},
		{"a plain error is a 500", errors.New("boom"), 500, "internal_error"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := db.MapError(tc.err)
			if got.Status != tc.wantStatus {
				t.Errorf("Status = %d, want %d", got.Status, tc.wantStatus)
			}
			if got.Code != tc.wantCode {
				t.Errorf("Code = %q, want %q", got.Code, tc.wantCode)
			}
		})
	}
}

func TestMapErrorPassesAnAppErrorThrough(t *testing.T) {
	original := db.NewAppError(400, "two_values", "a criterion score carries a mark or a level, never both")
	if got := db.MapError(original); got != original {
		t.Errorf("MapError rebuilt an existing AppError: %#v", got)
	}
}

// An RLS denial arrives as 42501, which MapError has no case for, so it lands
// in the 500 database_error bucket. SPEC.md claims RLS denials are mapped.
// They are not — this pins the real behaviour, and the SPEC is corrected to
// match in this same change.
func TestRLSDenialIsNotSpeciallyMapped(t *testing.T) {
	got := db.MapError(&pgconn.PgError{Code: "42501", Message: "new row violates row-level security policy"})
	if got.Status != 500 || got.Code != "database_error" {
		t.Errorf("RLS denial mapped to %d/%s; update this test and internal/db/SPEC.md together if that is changed deliberately",
			got.Status, got.Code)
	}
}
