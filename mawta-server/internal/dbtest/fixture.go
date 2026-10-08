package dbtest

import (
	"context"
	_ "embed"
	"fmt"
	"os"
	"path/filepath"

	"github.com/google/uuid"

	"mawta-server/internal/db"
)

//go:embed fixture.sql
var fixtureSQL string

// Fixture names the rows fixture.sql creates. The ids are fixed so a test can
// say Fx.ClassMat5B instead of querying for it, and so a failure message names
// something a human recognises.
//
// The scenario, in one paragraph: two schools. In Cristo Rey, Quispe teaches
// Matemática to 5to B and Rojas teaches nothing — Rojas exists to be the
// same-school teacher who must not reach Quispe's class. San Martín is a
// second school entirely, to prove tenant isolation. Bimestre II is the live
// term; Bimestre I is closed behind it so "the preceding period" is a real
// thing a test can reason about.
type Fixture struct {
	// Tenant A — I.E. Cristo Rey
	TenantA       uuid.UUID
	UserQuispe    uuid.UUID
	TeacherQuispe uuid.UUID
	UserRojas     uuid.UUID
	TeacherRojas  uuid.UUID

	YearA      uuid.UUID
	TermI      uuid.UUID // closed, the preceding period
	TermII     uuid.UUID // active
	GradeLevel uuid.UUID
	SectionB   uuid.UUID
	SubjectMat uuid.UUID
	CourseMat  uuid.UUID
	ClassMat5B uuid.UUID

	CompetencyC1 uuid.UUID
	CompetencyC2 uuid.UUID
	CapabilityC2 uuid.UUID
	CriterionOne uuid.UUID
	CriterionTwo uuid.UUID

	ScaleMinedu uuid.UUID // ordinal AD/A/B/C — the official ladder
	LevelAD     uuid.UUID
	LevelA      uuid.UUID
	LevelB      uuid.UUID
	LevelC      uuid.UUID

	Students [5]uuid.UUID

	SessionOne uuid.UUID

	// AssessmentNumeric carries a max_score and real scores.
	AssessmentNumeric uuid.UUID
	// AssessmentOrdinal has no max_score and is valued with an AD/A/B/C level.
	AssessmentOrdinal uuid.UUID
	ScoreOne          uuid.UUID // student 0's live score on AssessmentNumeric

	// Tenant B — I.E. San Martín
	TenantB       uuid.UUID
	UserFlores    uuid.UUID
	TeacherFlores uuid.UUID
	YearB         uuid.UUID
	TermB         uuid.UUID
	ClassB        uuid.UUID
	StudentB      uuid.UUID
}

// Fixed ids. Chosen to be readable in a psql session: the trailing segment
// says what the row is.
var fx = Fixture{
	TenantA:       uuid.MustParse("a0000000-0000-4000-8000-000000000001"),
	UserQuispe:    uuid.MustParse("a0000000-0000-4000-8000-000000000010"),
	TeacherQuispe: uuid.MustParse("a0000000-0000-4000-8000-000000000011"),
	UserRojas:     uuid.MustParse("a0000000-0000-4000-8000-000000000020"),
	TeacherRojas:  uuid.MustParse("a0000000-0000-4000-8000-000000000021"),

	YearA:      uuid.MustParse("a0000000-0000-4000-8000-000000000030"),
	TermI:      uuid.MustParse("a0000000-0000-4000-8000-000000000031"),
	TermII:     uuid.MustParse("a0000000-0000-4000-8000-000000000032"),
	GradeLevel: uuid.MustParse("a0000000-0000-4000-8000-000000000040"),
	SectionB:   uuid.MustParse("a0000000-0000-4000-8000-000000000041"),
	SubjectMat: uuid.MustParse("a0000000-0000-4000-8000-000000000050"),
	CourseMat:  uuid.MustParse("a0000000-0000-4000-8000-000000000051"),
	ClassMat5B: uuid.MustParse("a0000000-0000-4000-8000-000000000052"),

	CompetencyC1: uuid.MustParse("a0000000-0000-4000-8000-000000000060"),
	CompetencyC2: uuid.MustParse("a0000000-0000-4000-8000-000000000061"),
	CapabilityC2: uuid.MustParse("a0000000-0000-4000-8000-000000000062"),
	CriterionOne: uuid.MustParse("a0000000-0000-4000-8000-000000000063"),
	CriterionTwo: uuid.MustParse("a0000000-0000-4000-8000-000000000064"),

	ScaleMinedu: uuid.MustParse("a0000000-0000-4000-8000-000000000070"),
	LevelAD:     uuid.MustParse("a0000000-0000-4000-8000-000000000071"),
	LevelA:      uuid.MustParse("a0000000-0000-4000-8000-000000000072"),
	LevelB:      uuid.MustParse("a0000000-0000-4000-8000-000000000073"),
	LevelC:      uuid.MustParse("a0000000-0000-4000-8000-000000000074"),

	Students: [5]uuid.UUID{
		uuid.MustParse("a0000000-0000-4000-8000-000000000101"),
		uuid.MustParse("a0000000-0000-4000-8000-000000000102"),
		uuid.MustParse("a0000000-0000-4000-8000-000000000103"),
		uuid.MustParse("a0000000-0000-4000-8000-000000000104"),
		uuid.MustParse("a0000000-0000-4000-8000-000000000105"),
	},

	SessionOne: uuid.MustParse("a0000000-0000-4000-8000-000000000110"),

	AssessmentNumeric: uuid.MustParse("a0000000-0000-4000-8000-000000000120"),
	AssessmentOrdinal: uuid.MustParse("a0000000-0000-4000-8000-000000000121"),
	ScoreOne:          uuid.MustParse("a0000000-0000-4000-8000-000000000122"),

	TenantB:       uuid.MustParse("b0000000-0000-4000-8000-000000000001"),
	UserFlores:    uuid.MustParse("b0000000-0000-4000-8000-000000000010"),
	TeacherFlores: uuid.MustParse("b0000000-0000-4000-8000-000000000011"),
	YearB:         uuid.MustParse("b0000000-0000-4000-8000-000000000030"),
	TermB:         uuid.MustParse("b0000000-0000-4000-8000-000000000032"),
	ClassB:        uuid.MustParse("b0000000-0000-4000-8000-000000000052"),
	StudentB:      uuid.MustParse("b0000000-0000-4000-8000-000000000101"),
}

// seed applies fixture.sql on the admin pool. As superuser it bypasses RLS,
// which is deliberate: the fixture is scaffolding, not a thing under test, and
// making it set app.tenant_id per statement would only obscure it.
func seed(ctx context.Context, admin *db.DB) (Fixture, error) {
	if _, err := admin.Pool.Exec(ctx, fixtureSQL); err != nil {
		return Fixture{}, err
	}
	return fx, nil
}

// migrationsDir finds mawta-server/migrations from whichever package directory
// `go test` happens to be running in, by walking up to the module root.
func migrationsDir() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("working directory: %w", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			path := filepath.Join(dir, "migrations")
			if _, err := os.Stat(path); err != nil {
				return "", fmt.Errorf("found the module root at %s but no migrations/ in it", dir)
			}
			return path, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("no go.mod above the working directory; cannot locate migrations/")
		}
		dir = parent
	}
}
