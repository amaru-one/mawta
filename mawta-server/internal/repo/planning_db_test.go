package repo_test

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/dbtest"
)

// Tests for the planning schema (migrations/00002_planning_schema.sql).
//
// These are constraint tests, not repository tests: there is no repo function
// for the planning flow yet (later tickets add it), so each test inserts the
// rows directly and asserts that the database accepts or rejects them. The
// point is to prove the invariants live in the schema, where no code path can
// forget them.

// insertExperience inserts a learning experience for Quispe's Matemática 5to B
// in Bimestre II (2026-05-16 .. 2026-07-31) and returns its id.
func insertExperience(t *testing.T, ctx context.Context, tx pgx.Tx,
	classID, yearID, termID uuid.UUID, startsOn, endsOn string) uuid.UUID {
	t.Helper()
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into learning_experiences
		  (tenant_id, class_id, academic_year_id, term_id, title, idea_text, starts_on, ends_on)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7)
		returning id
	`, classID, yearID, termID, "La feria matemática",
		"Quiero que armen puestos de venta y calculen cambios",
		startsOn, endsOn).Scan(&id)
	if err != nil {
		t.Fatalf("insert experience: %v", err)
	}
	return id
}

// probe runs fn inside a savepoint and reports the error it got, if any.
//
// The savepoint is not decoration. A rejected statement puts the whole
// PostgreSQL transaction into an aborted state (SQLSTATE 25P02 for everything
// that follows), so without it the first rejection in a table-driven case
// would make every later statement fail for that reason alone — and a later
// "was it rejected?" assertion would pass against a broken transaction rather
// than against a real rejection. Rolling back to the savepoint restores a
// working transaction, which is what lets one test probe several rejections.
func probe(t *testing.T, ctx context.Context, tx pgx.Tx, fn func() error) error {
	t.Helper()
	if _, err := tx.Exec(ctx, `savepoint probe`); err != nil {
		t.Fatalf("savepoint: %v", err)
	}
	err := fn()
	if err != nil {
		if _, rerr := tx.Exec(ctx, `rollback to savepoint probe`); rerr != nil {
			t.Fatalf("rollback to savepoint: %v", rerr)
		}
	}
	// RELEASE both closes the still-open savepoint and removes the mark left
	// by the ROLLBACK TO, so the next probe starts from a clean slate.
	if _, rerr := tx.Exec(ctx, `release savepoint probe`); rerr != nil {
		t.Fatalf("release savepoint: %v", rerr)
	}
	return err
}

// ------------------------------------------------- experiences: overlap --

// Two non-deleted experiences of the same class may not cover the same date.
// The exclusion constraint is what makes "the experience of this week" a
// single row, so the timeline a teacher plans against is never ambiguous.
func TestExperiencesOfAClassMayNotOverlap(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII, "2026-06-01", "2026-06-15")

		// Overlaps on both ends, in the middle, and by a single boundary day.
		for _, tc := range []struct{ name, starts, ends string }{
			{"inside", "2026-06-10", "2026-06-20"},
			{"same range", "2026-06-01", "2026-06-15"},
			{"boundary day", "2026-06-15", "2026-06-30"},
			{"contains", "2026-05-01", "2026-07-01"},
		} {
			err := probe(t, ctx, tx, func() error {
				_, err := tx.Exec(ctx, `
					insert into learning_experiences
					  (tenant_id, class_id, academic_year_id, term_id, title, idea_text, starts_on, ends_on)
					values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7)
				`, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII, "Otra", "otra idea", tc.starts, tc.ends)
				return err
			})
			if err == nil {
				t.Errorf("%s: an overlapping experience was accepted", tc.name)
			}
		}

		// A soft-deleted experience does not block a new one: deleting frees
		// the dates, which is what makes an abandoned plan replaceable.
		if _, err := tx.Exec(ctx, `
			update learning_experiences set deleted_at = now() where title = 'La feria matemática'
		`); err != nil {
			t.Fatalf("soft-delete: %v", err)
		}
		if _, err := tx.Exec(ctx, `
			insert into learning_experiences
			  (tenant_id, class_id, academic_year_id, term_id, title, idea_text, starts_on, ends_on)
			values (app.current_tenant_id(), $1, $2, $3, $4, $5, '2026-06-01', '2026-06-15')
		`, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII, "Reemplazo", "otra idea"); err != nil {
			t.Errorf("a soft-deleted experience still blocked the dates: %v", err)
		}
	})
}

// ------------------------------------------------ experiences: term dates --

// An experience must start and end inside its term. The constraint trigger is
// deferred, so the rejection surfaces at commit — which is also how the app
// will create an experience and adjust its dates in one transaction.
func TestExperienceOutsideItsTermIsRejected(t *testing.T) {
	for _, tc := range []struct{ name, starts, ends string }{
		{"starts before the term", "2026-05-01", "2026-06-15"},
		{"ends after the term", "2026-07-01", "2026-08-15"},
		{"entirely after the term", "2026-08-01", "2026-08-15"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			env := dbtest.Setup(t)
			inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
				_, err := tx.Exec(ctx, `
					insert into learning_experiences
					  (tenant_id, class_id, academic_year_id, term_id, title, idea_text, starts_on, ends_on)
					values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7)
				`, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII, "Fuera", "idea", tc.starts, tc.ends)
				if err != nil {
					t.Fatalf("insert: %v", err)
				}
				// The trigger is deferred: the INSERT succeeds and the COMMIT
				// fails. Commit here so the failure surfaces in this test
				// rather than being swallowed by the helper's rollback.
				if err := tx.Commit(ctx); err == nil {
					t.Fatal("an experience outside its term was accepted")
				}
			})
		})
	}
}

// The boundary dates of the term are inside it, not outside: a teacher who
// plans the whole bimestre is not an error. The rule is a deferred constraint
// trigger, so this has to commit — a rolled-back transaction would prove
// nothing.
func TestExperienceOnTheTermBoundariesIsAccepted(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		id := insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII, "2026-05-16", "2026-07-31")
		if err := tx.Commit(ctx); err != nil {
			t.Fatalf("an experience covering exactly its term was rejected: %v", err)
		}
		// The commit is the point of the test, so the row survives it — and
		// the suite shares one database and runs shuffled. Without this
		// cleanup the experience would sit on ClassMat5B for the whole term
		// and collide with the overlap exclusion in every later test.
		t.Cleanup(func() {
			if _, err := env.Admin.Pool.Exec(context.Background(),
				`delete from learning_experiences where id = $1`, id); err != nil {
				t.Errorf("cleanup committed experience %s: %v", id, err)
			}
		})
	})
}

// ------------------------------------------- experience competencies --

// A linked competency must belong to the class's course subject. The fixture
// gives tenant A two competencies of Matemática and no competency of another
// subject, so the wrong-subject case is built here by inserting one.
func TestExperienceCompetencyMustBelongToTheClassSubject(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		experienceID := insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII,
			"2026-06-01", "2026-06-15")

		// A competency of another subject, to have something wrong to point at.
		var otherSubjectID, otherCompetencyID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into subjects (tenant_id, code, name) values (app.current_tenant_id(), 'COM', 'Comunicación')
			returning id
		`).Scan(&otherSubjectID); err != nil {
			t.Fatalf("insert subject: %v", err)
		}
		if err := tx.QueryRow(ctx, `
			insert into competencies (tenant_id, subject_id, code, name, kind)
			values (app.current_tenant_id(), $1, 'COM-C1', 'Escribe diversos tipos de textos', 'area')
			returning id
		`, otherSubjectID).Scan(&otherCompetencyID); err != nil {
			t.Fatalf("insert competency: %v", err)
		}

		// The class's own subject is accepted.
		if _, err := tx.Exec(ctx, `
			insert into experience_competencies (tenant_id, experience_id, competency_id)
			values (app.current_tenant_id(), $1, $2)
		`, experienceID, env.Fx.CompetencyC1); err != nil {
			t.Fatalf("a competency of the class's subject was rejected: %v", err)
		}

		// Another subject's competency is not.
		err := probe(t, ctx, tx, func() error {
			_, err := tx.Exec(ctx, `
				insert into experience_competencies (tenant_id, experience_id, competency_id)
				values (app.current_tenant_id(), $1, $2)
			`, experienceID, otherCompetencyID)
			return err
		})
		if err == nil {
			t.Error("a competency of another subject was accepted")
		}
	})
}

// ------------------------------------------------ criterion capabilities --

// A criterion looks at capabilities of its own competency only. The composite
// FK (tenant_id, competency_id, capability_id) makes a cross-competency link
// structurally impossible, so this also proves the denormalised competency_id
// cannot be forged.
func TestCriterionCapabilityMustBelongToTheCriterionCompetency(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// A capability under the other competency of the same subject, to have
		// a real wrong answer that is not a cross-tenant one.
		var otherCapabilityID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into capabilities (tenant_id, competency_id, code, name)
			values (app.current_tenant_id(), $1, 'MAT-C1-CAP1', 'Matematiza situaciones')
			returning id
		`, env.Fx.CompetencyC1).Scan(&otherCapabilityID); err != nil {
			t.Fatalf("insert capability: %v", err)
		}

		link := func(competency, capability uuid.UUID) func() error {
			return func() error {
				_, err := tx.Exec(ctx, `
					insert into evaluation_criterion_capabilities
					  (tenant_id, criterion_id, competency_id, capability_id)
					values (app.current_tenant_id(), $1, $2, $3)
				`, env.Fx.CriterionOne, competency, capability)
				return err
			}
		}

		// The honest row — CriterionOne's own capability — is accepted.
		if err := probe(t, ctx, tx, link(env.Fx.CompetencyC2, env.Fx.CapabilityC2)); err != nil {
			t.Errorf("a capability of the criterion's own competency was rejected: %v", err)
		}

		for _, tc := range []struct {
			name       string
			competency uuid.UUID
			capability uuid.UUID
		}{
			{"capability of another competency", env.Fx.CompetencyC2, otherCapabilityID},
			{"forged competency_id", env.Fx.CompetencyC1, env.Fx.CapabilityC2},
		} {
			if err := probe(t, ctx, tx, link(tc.competency, tc.capability)); err == nil {
				t.Errorf("%s: accepted", tc.name)
			}
		}
	})
}

// A criterion cannot end up with zero capabilities: deleting the last link is
// rejected at commit. The criterion here is created the new way — no legacy
// capability_id, only the join table — so the join table is the only thing
// keeping it alive, and deleting its single row must fail.
func TestCriterionCannotLoseItsLastCapability(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var criterionID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into evaluation_criteria (tenant_id, competency_id, capability_id, code, description)
			values (app.current_tenant_id(), $1, null, 'CR-NUEVO', 'Modela la situación con una función')
			returning id
		`, env.Fx.CompetencyC2).Scan(&criterionID); err != nil {
			t.Fatalf("insert criterion: %v", err)
		}
		if _, err := tx.Exec(ctx, `
			insert into evaluation_criterion_capabilities
			  (tenant_id, criterion_id, competency_id, capability_id)
			values (app.current_tenant_id(), $1, $2, $3)
		`, criterionID, env.Fx.CompetencyC2, env.Fx.CapabilityC2); err != nil {
			t.Fatalf("link capability: %v", err)
		}

		// Deleting that last row must fail at commit.
		if _, err := tx.Exec(ctx, `
			delete from evaluation_criterion_capabilities where criterion_id = $1
		`, criterionID); err != nil {
			t.Fatalf("delete: %v", err)
		}
		if err := tx.Commit(ctx); err == nil {
			t.Fatal("a criterion was left with zero capabilities")
		}
	})
}

// A criterion created with no capability at all is rejected too — the
// constraint trigger on evaluation_criteria covers the insert path.
func TestCriterionWithNoCapabilityIsRejected(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// No capability in the join table and none in the legacy column.
		if _, err := tx.Exec(ctx, `
			insert into evaluation_criteria
			  (tenant_id, competency_id, capability_id, code, description)
			values (app.current_tenant_id(), $1, null, 'CR3', 'Describe el patrón de crecimiento')
		`, env.Fx.CompetencyC2); err != nil {
			t.Fatalf("insert criterion: %v", err)
		}
		if err := tx.Commit(ctx); err == nil {
			t.Fatal("a criterion with no capability was accepted")
		}
	})
}

// The legacy path still works: a criterion written with only the old
// capability_id column (what repo.CreateCriterion and onboarding do today) is
// accepted. This is the "existing data must survive" requirement.
func TestLegacyCriterionPathStillWorks(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var id uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into evaluation_criteria
			  (tenant_id, competency_id, capability_id, code, description)
			values (app.current_tenant_id(), $1, $2, 'CR3', 'Describe el patrón de crecimiento')
			returning id
		`, env.Fx.CompetencyC2, env.Fx.CapabilityC2).Scan(&id); err != nil {
			t.Fatalf("insert criterion the legacy way: %v", err)
		}
		if err := tx.Commit(ctx); err != nil {
			t.Fatalf("the legacy criterion path was rejected at commit: %v", err)
		}
		// The commit is the point of the test, so the criterion survives it.
		// Remove it again: the suite shares one database and runs shuffled,
		// and a third criterion on CompetencyC2 would change what the
		// backfill test counts.
		t.Cleanup(func() {
			if _, err := env.Admin.Pool.Exec(context.Background(),
				`delete from evaluation_criterion_capabilities where criterion_id = $1`, id); err != nil {
				t.Errorf("cleanup join rows of %s: %v", id, err)
			}
			if _, err := env.Admin.Pool.Exec(context.Background(),
				`delete from evaluation_criteria where id = $1`, id); err != nil {
				t.Errorf("cleanup committed criterion %s: %v", id, err)
			}
		})
	})
}

// ------------------------------------------------- planned evidences --

// A planned evidence observes criteria of its own experience. A criterion of
// another experience — or a global criterion with no experience — must be
// rejected: the evidence is a promise about this experience's criteria.
func TestPlannedEvidenceObservesOnlyItsOwnExperienceCriteria(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		experienceA := insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII,
			"2026-06-01", "2026-06-15")
		experienceB := insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII,
			"2026-06-16", "2026-06-30")

		// Both experiences work CompetencyC2, so a criterion of B is a real
		// wrong answer and not a subject mismatch.
		for _, experienceID := range []uuid.UUID{experienceA, experienceB} {
			if _, err := tx.Exec(ctx, `
				insert into experience_competencies (tenant_id, experience_id, competency_id)
				values (app.current_tenant_id(), $1, $2)
			`, experienceID, env.Fx.CompetencyC2); err != nil {
				t.Fatalf("link competency: %v", err)
			}
		}

		// A criterion of experience B.
		var criterionB uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into evaluation_criteria
			  (tenant_id, competency_id, capability_id, experience_id, code, description)
			values (app.current_tenant_id(), $1, $2, $3, 'CR-B', 'Modela la situación con una función')
			returning id
		`, env.Fx.CompetencyC2, env.Fx.CapabilityC2, experienceB).Scan(&criterionB); err != nil {
			t.Fatalf("insert criterion B: %v", err)
		}

		// An evidence of experience A.
		var evidenceA uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into planned_evidences (tenant_id, experience_id, name, kind)
			values (app.current_tenant_id(), $1, 'Portafolio de la feria', 'produccion')
			returning id
		`, experienceA).Scan(&evidenceA); err != nil {
			t.Fatalf("insert evidence: %v", err)
		}

		observe := func(criterion uuid.UUID) func() error {
			return func() error {
				_, err := tx.Exec(ctx, `
					insert into planned_evidence_criteria (tenant_id, evidence_id, criterion_id)
					values (app.current_tenant_id(), $1, $2)
				`, evidenceA, criterion)
				return err
			}
		}

		// A criterion of another experience is rejected.
		if err := probe(t, ctx, tx, observe(criterionB)); err == nil {
			t.Error("a criterion of another experience was accepted")
		}
		// A global criterion (no experience) is rejected too.
		if err := probe(t, ctx, tx, observe(env.Fx.CriterionOne)); err == nil {
			t.Error("a global criterion was accepted for a planned evidence")
		}
	})
}

// ------------------------------------------------- session outline entries --

// At most one entry per (experience, class date): a double block is one
// session, so the uniqueness is by date and not by schedule slot.
func TestSessionOutlineEntryIsUniquePerExperienceAndDate(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		experienceID := insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII,
			"2026-06-01", "2026-06-15")

		insertEntry := func(title string) error {
			_, err := tx.Exec(ctx, `
				insert into session_outline_entries
				  (tenant_id, experience_id, class_date, title)
				values (app.current_tenant_id(), $1, $2, $3)
			`, experienceID, "2026-06-03", title)
			return err
		}

		if err := insertEntry("Lanzamiento de la situación"); err != nil {
			t.Fatalf("first entry: %v", err)
		}
		if err := probe(t, ctx, tx, func() error { return insertEntry("Segunda franja del mismo día") }); err == nil {
			t.Error("a second entry for the same (experience, date) was accepted")
		}

		// A soft-deleted entry frees the date, like experiences do.
		if _, err := tx.Exec(ctx, `
			update session_outline_entries set deleted_at = now()
			 where experience_id = $1 and class_date = $2
		`, experienceID, "2026-06-03"); err != nil {
			t.Fatalf("soft-delete entry: %v", err)
		}
		if err := insertEntry("Reprogramado"); err != nil {
			t.Errorf("a soft-deleted entry still blocked the date: %v", err)
		}
	})
}

// The date of an entry must fall inside the experience's range.
func TestSessionEntryDateMustFallInsideTheExperience(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		experienceID := insertExperience(t, ctx, tx, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII,
			"2026-06-01", "2026-06-15")

		for _, tc := range []struct {
			name string
			date string
			want bool
		}{
			{"first day", "2026-06-01", true},
			{"last day", "2026-06-15", true},
			{"day before", "2026-05-31", false},
			{"day after", "2026-06-16", false},
		} {
			err := probe(t, ctx, tx, func() error {
				_, err := tx.Exec(ctx, `
					insert into session_outline_entries (tenant_id, experience_id, class_date, title)
					values (app.current_tenant_id(), $1, $2, $3)
				`, experienceID, tc.date, "Sesión")
				return err
			})
			if tc.want && err != nil {
				t.Errorf("%s: rejected: %v", tc.name, err)
			}
			if !tc.want && err == nil {
				t.Errorf("%s: accepted", tc.name)
			}
		}
	})
}

// ------------------------------------------------------------- RLS --

// The new tables are tenant-scoped like the rest of the schema: a session set
// to tenant A cannot see tenant B's rows.
func TestPlanningTablesAreIsolatedBetweenTenants(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	// Seed one experience per tenant, as admin (the fixture's role), so both
	// tenants really have a row to hide.
	seed := func(tenantID, classID, yearID, termID uuid.UUID) uuid.UUID {
		var id uuid.UUID
		if err := env.Admin.Pool.QueryRow(ctx, `
			insert into learning_experiences
			  (tenant_id, class_id, academic_year_id, term_id, title, idea_text, starts_on, ends_on)
			values ($1, $2, $3, $4, 'Experiencia', 'idea', '2026-06-01', '2026-06-15')
			returning id
		`, tenantID, classID, yearID, termID).Scan(&id); err != nil {
			t.Fatalf("seed experience for tenant %s: %v", tenantID, err)
		}
		return id
	}
	experienceA := seed(env.Fx.TenantA, env.Fx.ClassMat5B, env.Fx.YearA, env.Fx.TermII)
	experienceB := seed(env.Fx.TenantB, env.Fx.ClassB, env.Fx.YearB, env.Fx.TermB)

	// These two rows are the only thing any test in this file commits, and the
	// suite shares one database and runs shuffled: without this cleanup a
	// leftover experience on ClassMat5B would collide with the overlap
	// exclusion in another test.
	t.Cleanup(func() {
		for _, id := range []uuid.UUID{experienceA, experienceB} {
			if _, err := env.Admin.Pool.Exec(context.Background(),
				`delete from learning_experiences where id = $1`, id); err != nil {
				t.Errorf("cleanup seeded experience %s: %v", id, err)
			}
		}
	})

	// As tenant A, only tenant A's experience is visible.
	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var ids []uuid.UUID
		rows, err := tx.Query(ctx, `select id from learning_experiences`)
		if err != nil {
			t.Fatalf("query: %v", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id uuid.UUID
			if err := rows.Scan(&id); err != nil {
				t.Fatalf("scan: %v", err)
			}
			ids = append(ids, id)
		}
		if err := rows.Err(); err != nil {
			t.Fatalf("rows: %v", err)
		}
		if len(ids) != 1 || ids[0] != experienceA {
			t.Errorf("tenant A sees %d experiences, want exactly its own (%s)", len(ids), experienceA)
		}

		// And writing as tenant A reaches only its own row.
		tag, err := tx.Exec(ctx, `
			update learning_experiences set title = 'Renombrada' where id = $1
		`, experienceA)
		if err != nil || tag.RowsAffected() != 1 {
			t.Errorf("tenant A could not update its own experience: %v", err)
		}
	})
}

// --------------------------------------------------------- backfill --

// The migration copies every existing capability_id into the join table, so
// the current screens keep working and no criterion silently loses its
// capability when the old column stops being the source of truth.
//
// dbtest seeds the fixture AFTER running the migration, so in the test
// database the backfill had nothing to copy. This test rebuilds the situation
// it exists for — criteria that already carry the legacy column and nothing
// else — and re-runs the migration's own INSERT to prove it does the copy. It
// runs on the admin pool inside a transaction that is rolled back, so it
// leaves nothing behind for the rest of the shuffled suite.
func TestBackfillCopiedExistingCapabilityIDs(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	tx, err := env.Admin.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	// A criterion exactly as the pre-migration code writes it: the legacy
	// capability_id column, and nothing in the join table.
	var legacy uuid.UUID
	if err := tx.QueryRow(ctx, `
		insert into evaluation_criteria (tenant_id, competency_id, capability_id, code, description)
		values ($1, $2, $3, 'CR-LEGACY', 'Traduce la situación a una expresión algebraica')
		returning id
	`, env.Fx.TenantA, env.Fx.CompetencyC2, env.Fx.CapabilityC2).Scan(&legacy); err != nil {
		t.Fatalf("insert a legacy criterion: %v", err)
	}

	// The fixture's criteria are in exactly the same state — the migration ran
	// before they existed — so they are part of the proof too.
	var before int
	if err := tx.QueryRow(ctx, `select count(*) from evaluation_criterion_capabilities`).Scan(&before); err != nil {
		t.Fatalf("count the join table: %v", err)
	}
	if before != 0 {
		t.Fatalf("the join table already has %d row(s); some other test leaked state into the shared database", before)
	}

	// The migration's backfill, verbatim.
	if _, err := tx.Exec(ctx, `
		insert into evaluation_criterion_capabilities (tenant_id, criterion_id, competency_id, capability_id)
		select ec.tenant_id, ec.id, ec.competency_id, ec.capability_id
		  from evaluation_criteria ec
		 where ec.capability_id is not null
		   and not exists (
		     select 1 from evaluation_criterion_capabilities x
		      where x.tenant_id = ec.tenant_id
		        and x.criterion_id = ec.id
		        and x.capability_id = ec.capability_id
		   )
	`); err != nil {
		t.Fatalf("run the backfill: %v", err)
	}

	// Every criterion that carries the legacy column now has exactly that
	// capability in the join table — the legacy row this test created and the
	// fixture's two alike. The pairs are collected first: pgx does not allow a
	// second query on a connection while a rows cursor is still open.
	rows, err := tx.Query(ctx, `
		select ec.id, ec.capability_id
		  from evaluation_criteria ec
		 where ec.capability_id is not null and ec.deleted_at is null
	`)
	if err != nil {
		t.Fatalf("query criteria: %v", err)
	}

	var pairs []struct {
		criterion  uuid.UUID
		capability uuid.UUID
	}
	for rows.Next() {
		var criterionID, capabilityID uuid.UUID
		if err := rows.Scan(&criterionID, &capabilityID); err != nil {
			t.Fatalf("scan: %v", err)
		}
		pairs = append(pairs, struct {
			criterion  uuid.UUID
			capability uuid.UUID
		}{criterionID, capabilityID})
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows: %v", err)
	}
	rows.Close()

	if len(pairs) == 0 {
		t.Fatal("no criterion carries the legacy capability_id; the backfill cannot be verified")
	}
	for _, p := range pairs {
		var links int
		if err := tx.QueryRow(ctx, `
			select count(*) from evaluation_criterion_capabilities
			 where criterion_id = $1 and capability_id = $2 and deleted_at is null
		`, p.criterion, p.capability).Scan(&links); err != nil {
			t.Fatalf("count links for %s: %v", p.criterion, err)
		}
		if links != 1 {
			t.Errorf("criterion %s has %d link(s) to its legacy capability %s, want exactly 1",
				p.criterion, links, p.capability)
		}
	}
}
