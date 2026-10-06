package dbtest_test

import (
	"context"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/dbtest"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

// The harness testing itself: if these fail, nothing that depends on it can be
// believed.

func TestMigrationProducedTheWholeSchema(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	var tables int
	err := env.Admin.Pool.QueryRow(ctx, `
		select count(*) from pg_class c
		  join pg_namespace n on n.oid = c.relnamespace
		 where n.nspname = 'public' and c.relkind in ('r','p') and not c.relispartition`).Scan(&tables)
	if err != nil {
		t.Fatalf("count tables: %v", err)
	}
	// 43 schema tables (events counted once, as the partitioned parent) plus
	// goose_db_version. Partitions are excluded by relispartition, so the 175
	// monthly events_* children do not inflate this. 00002 adds 10 planning
	// tables and 00005 adds agent_generations, so the count is 55.
	if tables != 55 {
		t.Errorf("top-level tables = %d, want 55", tables)
	}

	var forced int
	if err := env.Admin.Pool.QueryRow(ctx, `
		select count(*) from pg_class c
		  join pg_namespace n on n.oid = c.relnamespace
		 where n.nspname = 'public' and c.relkind in ('r','p')
		   and not c.relispartition and c.relrowsecurity and c.relforcerowsecurity`).Scan(&forced); err != nil {
		t.Fatalf("count forced-RLS tables: %v", err)
	}
	// 41 from 00001, the 10 tenant-scoped planning tables of 00002 and
	// agent_generations of 00005.
	if forced != 52 {
		t.Errorf("tables with FORCE ROW LEVEL SECURITY = %d, want 52", forced)
	}
}

// The app pool is the whole point: connecting as mawta_app is what proves the
// GRANTs in 00001 actually reached the tables. An admin pool would pass here
// even with every grant missing.
func TestAppPoolConnectsAsTheNonOwnerRole(t *testing.T) {
	env := dbtest.Setup(t)

	var user string
	if err := env.App.Pool.QueryRow(context.Background(), `select current_user`).Scan(&user); err != nil {
		t.Fatalf("select current_user: %v", err)
	}
	if user != "mawta_app" {
		t.Fatalf("app pool connected as %q, want mawta_app", user)
	}
}

func TestAppRoleCanReadAndWriteEveryFixtureTable(t *testing.T) {
	env := dbtest.Setup(t)
	tc := db.TenantCtx{TenantID: env.Fx.TenantA, ActorID: env.Fx.UserQuispe, TeacherID: env.Fx.TeacherQuispe, RequestID: "test"}

	err := env.App.WithTenantTx(context.Background(), tc, func(tx pgx.Tx) error {
		for _, table := range []string{
			"tenants", "users", "memberships", "teachers", "academic_years", "terms",
			"grade_levels", "sections", "subjects", "competencies", "capabilities",
			"evaluation_criteria", "students", "section_memberships", "courses", "classes",
			"class_teachers", "class_sessions", "grade_scales", "grade_scale_levels",
			"grading_schemes", "grading_components", "grading_scheme_versions",
			"grading_scheme_component_weights", "assessments", "assessment_criteria", "scores",
		} {
			var n int
			if err := tx.QueryRow(context.Background(), `select count(*) from `+table).Scan(&n); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("mawta_app could not read a fixture table (a missing GRANT in 00001?): %v", err)
	}
}

func TestFixtureSeededTheExpectedShape(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	tc := db.TenantCtx{TenantID: env.Fx.TenantA, ActorID: env.Fx.UserQuispe, TeacherID: env.Fx.TeacherQuispe, RequestID: "test"}

	err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		for _, tc := range []struct {
			what  string
			query string
			want  int
		}{
			{"students in 5to B", `select count(*) from students`, 5},
			{"teachers", `select count(*) from teachers`, 2},
			{"classes", `select count(*) from classes`, 1},
			{"class_teachers rows", `select count(*) from class_teachers`, 1},
			{"competencies", `select count(*) from competencies`, 2},
			{"evaluation_criteria", `select count(*) from evaluation_criteria`, 2},
			{"published assessments", `select count(*) from assessments where status = 'published'`, 2},
			{"live scores", `select count(*) from scores where superseded_at is null`, 1},
			{"ordinal scales", `select count(*) from grade_scales where kind = 'ordinal'`, 1},
			{"levels on the ordinal scale", `select count(*) from grade_scale_levels`, 4},
		} {
			var got int
			if err := tx.QueryRow(ctx, tc.query).Scan(&got); err != nil {
				return err
			}
			if got != tc.want {
				t.Errorf("%s = %d, want %d", tc.what, got, tc.want)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("query fixture: %v", err)
	}
}

// Rojas is an active teacher of the same school with no class_teachers row.
// Every authorization test leans on that, so it is asserted here once.
func TestRojasTeachesNothing(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	tc := db.TenantCtx{TenantID: env.Fx.TenantA, ActorID: env.Fx.UserRojas, TeacherID: env.Fx.TeacherRojas, RequestID: "test"}

	var assignments int
	err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`select count(*) from class_teachers where teacher_id = $1 and deleted_at is null`,
			env.Fx.TeacherRojas).Scan(&assignments)
	})
	if err != nil {
		t.Fatalf("query class_teachers: %v", err)
	}
	if assignments != 0 {
		t.Fatalf("Rojas has %d class assignments, want 0 — the authorization fixture is broken", assignments)
	}
}

// The scores trigger fills class_id and term_id from the assessment. The
// fixture never supplies them, so this proves the trigger ran.
func TestScoreDenormalisationTriggerFilledTheFixtureRow(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	tc := db.TenantCtx{TenantID: env.Fx.TenantA, ActorID: env.Fx.UserQuispe, TeacherID: env.Fx.TeacherQuispe, RequestID: "test"}

	var classID, termID uuid.UUID
	err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `select class_id, term_id from scores where id = $1`, env.Fx.ScoreOne).Scan(&classID, &termID)
	})
	if err != nil {
		t.Fatalf("read the fixture score: %v", err)
	}
	if classID != env.Fx.ClassMat5B {
		t.Errorf("class_id = %s, want %s", classID, env.Fx.ClassMat5B)
	}
	if termID != env.Fx.TermII {
		t.Errorf("term_id = %s, want %s", termID, env.Fx.TermII)
	}
}
