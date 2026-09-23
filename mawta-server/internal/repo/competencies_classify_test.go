package repo

import (
	"testing"

	"mawta-server/internal/domain"
)

// classifyConclusionRequirement is the one pure function in this package: no
// tx, no ctx, no clock. It decides whether a teacher is obliged to write a
// conclusión descriptiva, so getting it wrong either burdens a teacher with
// paperwork the norm does not ask for, or lets a period close without the
// justification RVM 048-2024 requires. It is unexported, hence an in-package
// test; it needs no database.

func level(code string) *string { return &code }

func TestClassifyConclusionRequirement(t *testing.T) {
	cases := []struct {
		name             string
		inclusionSupport bool
		stage            string
		cycle            string
		levelCode        *string
		consecutiveC     bool
		want             string
	}{
		// Inclusion support outranks everything: level, stage, cycle, even a
		// missing level.
		{"inclusion support with no level at all", true, domain.StageSecundaria, "", nil, false, domain.ConclusionInclusionSupport},
		{"inclusion support outranks a comfortable AD", true, domain.StageSecundaria, "", level(domain.LevelAD), false, domain.ConclusionInclusionSupport},
		{"inclusion support outranks consecutive C", true, domain.StagePrimaria, "", level(domain.LevelC), true, domain.ConclusionInclusionSupport},
		{"inclusion support outranks Ciclo I", true, domain.StageInicial, domain.CycleI, nil, false, domain.ConclusionInclusionSupport},

		// Inicial Ciclo I: every competencia, whatever the level.
		{"Ciclo I with no level", false, domain.StageInicial, domain.CycleI, nil, false, domain.ConclusionCycleIMandatory},
		{"Ciclo I with AD", false, domain.StageInicial, domain.CycleI, level(domain.LevelAD), false, domain.ConclusionCycleIMandatory},
		{"Ciclo I outranks consecutive C", false, domain.StageInicial, domain.CycleI, level(domain.LevelC), true, domain.ConclusionCycleIMandatory},

		// No level asserted is a valid state — "no desarrollada", not C — and
		// carries no obligation on its own.
		{"no level in secundaria", false, domain.StageSecundaria, "", nil, false, domain.ConclusionOptional},
		{"no level in primaria", false, domain.StagePrimaria, "", nil, false, domain.ConclusionOptional},
		{"no level in Ciclo II", false, domain.StageInicial, domain.CycleII, nil, false, domain.ConclusionOptional},
		{"no level, consecutiveC ignored without a level", false, domain.StageSecundaria, "", nil, true, domain.ConclusionOptional},

		// Level C is mandatory everywhere.
		{"C in secundaria", false, domain.StageSecundaria, "", level(domain.LevelC), false, domain.ConclusionLevelC},
		{"C in primaria", false, domain.StagePrimaria, "", level(domain.LevelC), false, domain.ConclusionLevelC},
		{"C in Ciclo II", false, domain.StageInicial, domain.CycleII, level(domain.LevelC), false, domain.ConclusionLevelC},
		{"C in otro", false, domain.StageOtro, "", level(domain.LevelC), false, domain.ConclusionLevelC},

		// A second consecutive C is the stronger classification — the one that
		// has to justify the lack of progress.
		{"consecutive C in secundaria", false, domain.StageSecundaria, "", level(domain.LevelC), true, domain.ConclusionConsecutiveC},
		{"consecutive C in primaria", false, domain.StagePrimaria, "", level(domain.LevelC), true, domain.ConclusionConsecutiveC},
		{"consecutive C in Ciclo II", false, domain.StageInicial, domain.CycleII, level(domain.LevelC), true, domain.ConclusionConsecutiveC},

		// Level B: primaria and Inicial Ciclo II only.
		{"B in primaria", false, domain.StagePrimaria, "", level(domain.LevelB), false, domain.ConclusionLevelB},
		{"B in Ciclo II", false, domain.StageInicial, domain.CycleII, level(domain.LevelB), false, domain.ConclusionLevelB},
		{"B in secundaria is optional", false, domain.StageSecundaria, "", level(domain.LevelB), false, domain.ConclusionOptional},
		{"B in otro is optional", false, domain.StageOtro, "", level(domain.LevelB), false, domain.ConclusionOptional},

		// Level A: Inicial Ciclo II only.
		{"A in Ciclo II", false, domain.StageInicial, domain.CycleII, level(domain.LevelA), false, domain.ConclusionLevelA},
		{"A in primaria is optional", false, domain.StagePrimaria, "", level(domain.LevelA), false, domain.ConclusionOptional},
		{"A in secundaria is optional", false, domain.StageSecundaria, "", level(domain.LevelA), false, domain.ConclusionOptional},

		// AD never obliges anyone, anywhere.
		{"AD in secundaria", false, domain.StageSecundaria, "", level(domain.LevelAD), false, domain.ConclusionOptional},
		{"AD in primaria", false, domain.StagePrimaria, "", level(domain.LevelAD), false, domain.ConclusionOptional},
		{"AD in Ciclo II", false, domain.StageInicial, domain.CycleII, level(domain.LevelAD), false, domain.ConclusionOptional},

		// consecutiveC is only ever consulted for C.
		{"consecutiveC alongside B is ignored", false, domain.StagePrimaria, "", level(domain.LevelB), true, domain.ConclusionLevelB},
		{"consecutiveC alongside AD is ignored", false, domain.StageSecundaria, "", level(domain.LevelAD), true, domain.ConclusionOptional},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := classifyConclusionRequirement(tc.inclusionSupport, tc.stage, tc.cycle, tc.levelCode, tc.consecutiveC)
			if got != tc.want {
				t.Errorf("classifyConclusionRequirement(%v, %q, %q, %v, %v) = %q, want %q",
					tc.inclusionSupport, tc.stage, tc.cycle, tc.levelCode, tc.consecutiveC, got, tc.want)
			}
		})
	}
}

// Inicial without a cycle recorded is neither Ciclo I nor Ciclo II, so it must
// fall through to the plain level rules rather than silently taking either
// branch.
func TestClassifyInicialWithoutACycle(t *testing.T) {
	for _, tc := range []struct {
		name  string
		level *string
		want  string
	}{
		{"C still mandatory", level(domain.LevelC), domain.ConclusionLevelC},
		{"B is not, without Ciclo II", level(domain.LevelB), domain.ConclusionOptional},
		{"A is not, without Ciclo II", level(domain.LevelA), domain.ConclusionOptional},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := classifyConclusionRequirement(false, domain.StageInicial, "", tc.level, false); got != tc.want {
				t.Errorf("got %q, want %q", got, tc.want)
			}
		})
	}
}

// Every value this function can return must be one the database will accept,
// or a conclusion write fails at the CHECK constraint on
// descriptive_conclusions.requirement.
func TestClassifyOnlyReturnsStorableRequirements(t *testing.T) {
	storable := map[string]bool{
		domain.ConclusionLevelC:           true,
		domain.ConclusionLevelB:           true,
		domain.ConclusionLevelA:           true,
		domain.ConclusionCycleIMandatory:  true,
		domain.ConclusionConsecutiveC:     true,
		domain.ConclusionInclusionSupport: true,
		domain.ConclusionOptional:         true,
	}

	levels := []*string{nil, level(domain.LevelC), level(domain.LevelB), level(domain.LevelA), level(domain.LevelAD)}
	stages := []string{domain.StageInicial, domain.StagePrimaria, domain.StageSecundaria, domain.StageOtro}
	cycles := []string{"", domain.CycleI, domain.CycleII}

	for _, inclusion := range []bool{false, true} {
		for _, stage := range stages {
			for _, cycle := range cycles {
				for _, lvl := range levels {
					for _, consecutive := range []bool{false, true} {
						got := classifyConclusionRequirement(inclusion, stage, cycle, lvl, consecutive)
						if !storable[got] {
							t.Fatalf("classify(%v, %q, %q, %v, %v) returned %q, which descriptive_conclusions.requirement would reject",
								inclusion, stage, cycle, lvl, consecutive, got)
						}
					}
				}
			}
		}
	}
}
