package onboarding

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"golang.org/x/crypto/bcrypt"

	"mawta-server/curriculum"
	"mawta-server/internal/auth"
	"mawta-server/internal/db"
	"mawta-server/internal/dbtest"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

var errRollback = errors.New("rollback")

// TestLoadExample commits the San Felipe example into this package's own
// throwaway database, then reads it back the way the app does: as mawta_app,
// scoped to the tenant by RLS.
func TestLoadExample(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	cat := catalog(t)
	s := example(t)

	var sum *Summary
	if err := env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
		var err error
		sum, err = Load(ctx, tx, s, cat, bcrypt.MinCost)
		return err
	}); err != nil {
		t.Fatalf("load: %v", err)
	}

	tenant := ID("tenant", "0723519", "")
	wantSessions := expectedSessions(t, s)
	if sum.Docentes != 2 || sum.Estudiantes != 10 || sum.Franjas != 5 || sum.Periodos != 3 ||
		sum.Sesiones != wantSessions || sum.SesionesConTema != 6 {
		t.Errorf("summary = %+v, want 2 docentes, 10 estudiantes, 5 franjas, 3 periodos, %d sesiones, 6 con tema", sum, wantSessions)
	}
	// The tree comes from the catalog: MAT (4 competencies × 4 capabilities),
	// CCSS (3+3+2 capabilities) and the two transversals (4+3).
	if sum.Competencias != 9 || sum.Capacidades != 31 || sum.Criterios != 16 {
		t.Errorf("summary = %+v, want 9 competencias, 31 capacidades y 16 criterios", sum)
	}
	// Standards: 8 levels per competency the school has.
	if sum.Estandares != 9*8 {
		t.Errorf("summary.Estandares = %d, want %d", sum.Estandares, 9*8)
	}
	// Performances: only the school's grade (1S), for the 7 area
	// competencies (the transversals have none).
	var wantPerformances int
	for _, a := range s.Areas {
		for _, cc := range cat.Area[a.Codigo].Competencias {
			for _, d := range cat.Competencias[cc.NumeroCNEB].Desempenos {
				if d.Grado == "1S" {
					wantPerformances++
				}
			}
		}
	}
	if sum.Desempenos != wantPerformances {
		t.Errorf("summary.Desempenos = %d, want %d", sum.Desempenos, wantPerformances)
	}

	// Everything below runs as the app role, so a missing grant or an RLS
	// gap in what the loader wrote would show up here.
	err := env.App.WithTenantTx(ctx, db.TenantCtx{TenantID: tenant}, func(tx pgx.Tx) error {
		counts := map[string]int{
			"select count(*) from teachers":                                               2,
			"select count(*) from students":                                               10,
			"select count(*) from section_memberships":                                    10,
			"select count(*) from capabilities":                                           31,
			"select count(*) from competencies":                                           9,
			"select count(*) from class_schedules":                                        5,
			"select count(*) from terms":                                                  3,
			"select count(*) from classes":                                                2,
			"select count(*) from class_sessions":                                         wantSessions,
			"select count(*) from class_sessions where status <> 'scheduled'":             0,
			"select count(*) from grading_scheme_versions where published_at is not null": 2,
			"select count(*) from evaluation_criteria":                                    16,
			"select count(*) from learning_standards":                                     9 * 8,
			"select count(*) from grade_level_performances":                               wantPerformances,
			"select count(*) from standard_level_mappings":                                1,
			"select count(*) from grade_levels where cycle = 'ciclo_vi'":                  1,
		}
		for q, want := range counts {
			var got int
			if err := tx.QueryRow(ctx, q).Scan(&got); err != nil {
				return err
			}
			if got != want {
				t.Errorf("%s = %d, want %d", q, got, want)
			}
		}

		// The tree carries the catalog's official names, verbatim.
		var name string
		if err := tx.QueryRow(ctx, `select name from competencies where code = 'MAT-C1'`).Scan(&name); err != nil {
			return err
		}
		if want := "Resuelve problemas de cantidad"; name != want {
			t.Errorf("MAT-C1 name = %q, want %q", name, want)
		}
		if err := tx.QueryRow(ctx, `select name from capabilities where code = 'MAT-C1-CAP1'`).Scan(&name); err != nil {
			return err
		}
		if want := "Traduce cantidades a expresiones numéricas"; name != want {
			t.Errorf("MAT-C1-CAP1 name = %q, want %q", name, want)
		}

		// The derived stance: 1S is the first grade of ciclo VI, so its
		// performances are "in progress towards" level 6.
		var enProceso bool
		var expected int
		if err := tx.QueryRow(ctx, `
			select en_proceso, expected_standard_level from grade_level_performances
			 where competency_id = md5('competency:0723519:MAT-C1')::uuid
			   and sort_order = 1`).Scan(&enProceso, &expected); err != nil {
			return err
		}
		if !enProceso || expected != 6 {
			t.Errorf("MAT-C1 1S #1: en_proceso = %v, expected = %d; want true, 6", enProceso, expected)
		}

		// The (modality, cycle) mapping the school's grades need.
		if err := tx.QueryRow(ctx, `
			select expected_level from standard_level_mappings
			 where modality = 'ebr' and cycle = 'ciclo_vi'`).Scan(&expected); err != nil {
			return err
		}
		if expected != 6 {
			t.Errorf("(ebr, ciclo_vi) → %d, want 6", expected)
		}

		// Each tema lands on the session of its date.
		for _, c := range s.Clases {
			for _, ses := range c.Sesiones {
				var topic string
				if err := tx.QueryRow(ctx, `
					select topic from class_sessions cs join classes c on c.id = cs.class_id
					 where c.code = $1 and cs.session_date = $2::text::date`, c.Codigo, ses.Fecha).Scan(&topic); err != nil {
					return err
				}
				if topic != ses.Tema {
					t.Errorf("%s %s topic = %q, want %q", c.Codigo, ses.Fecha, topic, ses.Tema)
				}
			}
		}

		// Sessions are placed in the school's zone: Monday 08:00 in Lima is
		// 13:00 UTC.
		var start time.Time
		if err := tx.QueryRow(ctx, `
			select scheduled_start_at from class_sessions
			 where class_id = $1 and session_date = '2026-03-02'`, ID("class", "0723519", "2026:MAT-1A")).Scan(&start); err != nil {
			return err
		}
		if want := time.Date(2026, 3, 2, 13, 0, 0, 0, time.UTC); !start.Equal(want) {
			t.Errorf("first session starts %s, want %s", start.UTC(), want)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}

	// The login path checks this hash; it must be the file's password.
	var hash string
	if err := env.Admin.Pool.QueryRow(ctx, `select password_hash from users where username = 'jeffrey'`).Scan(&hash); err != nil {
		t.Fatal(err)
	}
	if err := auth.VerifyPassword(hash, s.Docentes[0].Clave); err != nil {
		t.Error("jeffrey's password from the file does not verify against the stored hash")
	}

	// seed_demo.sql rebuilds ids in plain SQL; the formula must agree.
	var sqlID uuid.UUID
	if err := env.Admin.Pool.QueryRow(ctx, `select md5('class:0723519:2026:MAT-1A')::uuid`).Scan(&sqlID); err != nil {
		t.Fatal(err)
	}
	if sqlID != ID("class", "0723519", "2026:MAT-1A") {
		t.Errorf("Go id %s != SQL md5 id %s", ID("class", "0723519", "2026:MAT-1A"), sqlID)
	}

	// Loading the same school again refuses before writing anything.
	err = env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
		_, err := Load(ctx, tx, example(t), cat, bcrypt.MinCost)
		return err
	})
	if err == nil || !strings.Contains(err.Error(), "ya existe") {
		t.Fatalf("a second load must refuse with 'ya existe', got %v", err)
	}
}

// A dry run is a load whose transaction is rolled back: nothing may remain.
func TestDryRunLeavesNothing(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	cat := catalog(t)
	s := example(t)
	s.Colegio.CodigoModular = "0999999"
	for i := range s.Docentes {
		s.Docentes[i].Usuario += "-dry"
		s.Docentes[i].Email = "dry-" + s.Docentes[i].Email
	}
	for i := range s.Aulas {
		if s.Aulas[i].Tutor != "" {
			s.Aulas[i].Tutor += "-dry"
		}
	}
	for i := range s.Clases {
		s.Clases[i].Docente += "-dry"
	}

	err := env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
		if _, err := Load(ctx, tx, s, cat, bcrypt.MinCost); err != nil {
			return err
		}
		return errRollback
	})
	if !errors.Is(err, errRollback) {
		t.Fatalf("load inside the dry run: %v", err)
	}
	var n int
	if err := env.Admin.Pool.QueryRow(ctx, `select count(*) from tenants where modular_code = '0999999'`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 0 {
		t.Fatal("a rolled-back load left the tenant behind")
	}
}

// TestSyncCurriculum proves the three properties the sync must have: it
// inserts what is missing, it reports a renamed capability without changing
// it, and a second run changes nothing.
func TestSyncCurriculum(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	cat := catalog(t)

	// A school loaded the old way: competencies and capabilities by code,
	// but no standards, performances, mappings or grade cycles. That is the
	// shape an existing school has today.
	tenant := loadLegacySchool(t, env, ctx, cat, legacyModular, "-legacy")

	// One capability was renamed by the school; the sync must report it and
	// leave it alone.
	const renamed = "Traduce datos y condiciones a expresiones algebraicas y gráficas"
	if _, err := env.Admin.Pool.Exec(ctx, `
		update capabilities set name = $3
		 where tenant_id = $1 and code = $2`,
		tenant, "MAT-C2-CAP1", renamed); err != nil {
		t.Fatal(err)
	}

	var report *SyncReport
	var err error
	run := func() {
		err = env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
			var e error
			report, e = SyncCurriculum(ctx, tx, cat, legacyModular, map[string]string{"1S": "1S"})
			return e
		})
		if err != nil {
			t.Fatalf("sync: %v", err)
		}
	}
	run()

	if report.Estandares != 9*8 {
		t.Errorf("first sync inserted %d standards, want %d", report.Estandares, 9*8)
	}
	if report.NivelesEsperados != 1 {
		t.Errorf("first sync inserted %d mappings, want 1", report.NivelesEsperados)
	}
	if report.Capacidades != 0 {
		t.Errorf("first sync inserted %d capabilities, want 0 (the legacy school has them all)", report.Capacidades)
	}
	if len(report.Renamed) != 1 || !strings.Contains(report.Renamed[0], "MAT-C2-CAP1") {
		t.Errorf("renamed = %v, want one line naming MAT-C2-CAP1", report.Renamed)
	}

	// The renamed capability was reported, not overwritten.
	var name string
	if err := env.Admin.Pool.QueryRow(ctx, `
		select name from capabilities where tenant_id = $1 and code = 'MAT-C2-CAP1'`, tenant).Scan(&name); err != nil {
		t.Fatal(err)
	}
	if name != renamed {
		t.Errorf("MAT-C2-CAP1 name = %q, want the school's %q (the sync must not overwrite)", name, renamed)
	}

	// The grade got its cycle from the explicit map, not from a guess.
	var cycle string
	if err := env.Admin.Pool.QueryRow(ctx, `
		select cycle from grade_levels where tenant_id = $1 and code = '1S'`, tenant).Scan(&cycle); err != nil {
		t.Fatal(err)
	}
	if cycle != "ciclo_vi" {
		t.Errorf("grade 1S cycle = %q, want ciclo_vi", cycle)
	}

	// Idempotency: a second run inserts nothing and reports the same
	// difference (the school's name is still not the catalog's).
	before := counts(t, env, ctx, tenant)
	run()
	if report.Estandares != 0 || report.Desempenos != 0 || report.NivelesEsperados != 0 || report.Capacidades != 0 {
		t.Errorf("second sync inserted %+v, want nothing", report)
	}
	if len(report.Renamed) != 1 {
		t.Errorf("second sync renamed = %v, want the same one difference", report.Renamed)
	}
	after := counts(t, env, ctx, tenant)
	if before != after {
		t.Errorf("second sync changed the school: before %+v, after %+v", before, after)
	}
}

// TestSyncMatchesRowsByCode reproduces production: a school installed by an
// earlier loader whose rows do not carry the md5-derived ids a fresh load
// would produce. Changing the modular code after loading has the same effect
// (every derived id now differs from the stored one), so the sync must find
// competencies and capabilities by code and use their own ids.
func TestSyncMatchesRowsByCode(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	cat := catalog(t)

	tenant := loadLegacySchool(t, env, ctx, cat, "0777777", "-renumbered")
	if _, err := env.Admin.Pool.Exec(ctx,
		`update tenants set modular_code = '0777778' where id = $1`, tenant); err != nil {
		t.Fatal(err)
	}

	var report *SyncReport
	if err := env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
		var e error
		report, e = SyncCurriculum(ctx, tx, cat, "0777778", map[string]string{"1S": "1S"})
		return e
	}); err != nil {
		t.Fatalf("sync: %v", err)
	}
	if report.Capacidades != 0 {
		t.Errorf("sync inserted %d capabilities, want 0 (all exist under other ids)", report.Capacidades)
	}
	if report.Estandares != 9*8 || report.Desempenos == 0 {
		t.Errorf("sync inserted %d standards and %d performances, want %d and some", report.Estandares, report.Desempenos, 9*8)
	}
	var orphans int
	if err := env.Admin.Pool.QueryRow(ctx, `
		select count(*) from learning_standards ls
		 where ls.tenant_id = $1
		   and not exists (select 1 from competencies c where c.tenant_id = ls.tenant_id and c.id = ls.competency_id)`,
		tenant).Scan(&orphans); err != nil {
		t.Fatal(err)
	}
	if orphans != 0 {
		t.Errorf("%d standards point at no existing competency", orphans)
	}
}

type tableCounts struct {
	capabilities, standards, performances, mappings int
}

func counts(t *testing.T, env *dbtest.Env, ctx context.Context, tenant uuid.UUID) tableCounts {
	t.Helper()
	var c tableCounts
	one := func(q string) int {
		var n int
		if err := env.Admin.Pool.QueryRow(ctx, q, tenant).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n
	}
	c.capabilities = one(`select count(*) from capabilities where tenant_id = $1`)
	c.standards = one(`select count(*) from learning_standards where tenant_id = $1`)
	c.performances = one(`select count(*) from grade_level_performances where tenant_id = $1`)
	c.mappings = one(`select count(*) from standard_level_mappings where tenant_id = $1`)
	return c
}

// loadLegacySchool installs a school whose curriculum predates the catalog:
// competencies and capabilities exist (matched by code), but nothing else.
// It reuses the real loader and then deletes what the catalog added, which
// is exactly the state an existing school is in.
const legacyModular = "0888888"

func loadLegacySchool(t *testing.T, env *dbtest.Env, ctx context.Context, cat *curriculum.Catalog, modular, suffix string) uuid.UUID {
	t.Helper()
	// Its own modular code and users: TestLoadExample commits San Felipe
	// into the same package database, and the tests run shuffled.
	s := example(t)
	s.Colegio.CodigoModular = modular
	for i := range s.Docentes {
		s.Docentes[i].Clave = "clave-de-prueba-" + s.Docentes[i].Usuario
		s.Docentes[i].Usuario += suffix
		s.Docentes[i].Email = suffix + "-" + s.Docentes[i].Email
	}
	for i := range s.Aulas {
		if s.Aulas[i].Tutor != "" {
			s.Aulas[i].Tutor += suffix
		}
	}
	for i := range s.Clases {
		s.Clases[i].Docente += suffix
	}
	if err := env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
		_, err := Load(ctx, tx, s, cat, 4)
		return err
	}); err != nil {
		t.Fatalf("load the school: %v", err)
	}
	tenant := ID("tenant", modular, "")
	for _, q := range []string{
		`delete from grade_level_performances where tenant_id = $1`,
		`delete from learning_standards where tenant_id = $1`,
		`delete from standard_level_mappings where tenant_id = $1`,
		`update grade_levels set cycle = null where tenant_id = $1`,
	} {
		if _, err := env.Admin.Pool.Exec(ctx, q, tenant); err != nil {
			t.Fatalf("strip the catalog rows: %v", err)
		}
	}
	return tenant
}

// expectedSessions counts, independently of the loader, the dates on which
// each franja falls inside a periodo.
func expectedSessions(t *testing.T, s *Spec) int {
	t.Helper()
	n := 0
	for _, c := range s.Clases {
		for _, f := range c.Horario {
			dia, _ := parseWeekday(f.Dia)
			for _, p := range s.AnioEscolar.Periodos {
				from, _ := parseDate(p.Inicio)
				to, _ := parseDate(p.Fin)
				for d := from; !d.After(to); d = d.AddDate(0, 0, 1) {
					if isoWeekday(d) == dia {
						n++
					}
				}
			}
		}
	}
	return n
}
