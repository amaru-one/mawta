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
	s := example(t)

	var sum *Summary
	if err := env.Admin.WithSystemTx(ctx, func(tx pgx.Tx) error {
		var err error
		sum, err = Load(ctx, tx, s, bcrypt.MinCost)
		return err
	}); err != nil {
		t.Fatalf("load: %v", err)
	}

	tenant := ID("tenant", "0723519", "")
	wantSessions := expectedSessions(t, s)
	if sum.Docentes != 2 || sum.Estudiantes != 10 || sum.Capacidades != 31 || sum.Criterios != 19 ||
		sum.Franjas != 5 || sum.Periodos != 3 || sum.Sesiones != wantSessions || sum.SesionesConTema != 6 {
		t.Errorf("summary = %+v, want 2 docentes, 10 estudiantes, 31 capacidades, 19 criterios, 5 franjas, 3 periodos, %d sesiones, 6 con tema", sum, wantSessions)
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
		_, err := Load(ctx, tx, example(t), bcrypt.MinCost)
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
		if _, err := Load(ctx, tx, s, bcrypt.MinCost); err != nil {
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
