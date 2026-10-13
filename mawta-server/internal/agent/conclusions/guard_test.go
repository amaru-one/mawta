package conclusions

import (
	"strings"
	"testing"

	"github.com/google/uuid"

	"mawta-server/internal/repo"
)

func ptr(s string) *string { return &s }

func TestGuardRejectsNamesAndTokens(t *testing.T) {
	names := nameWords([]repo.StudentName{
		{GivenName: "María José", PaternalSurname: "Quispe", MaternalSurname: ptr("Flor"), PreferredName: ptr("Majo")},
		{GivenName: "Li", PaternalSurname: "Huamán"},
	})
	cases := []struct {
		text   string
		reject bool
	}{
		{"Explica sus ideas con claridad.", false},
		{"Maria explica sus ideas.", true}, // accent-insensitive
		{"Trabajó bien con Huaman.", true}, // surname
		{"Se le recomienda leer más, Majo.", true},
		{"Describe las partes de una flor.", false}, // a name that is also a word, written as a word
		{"Lee en voz alta con [COMPAÑERO_1].", true},
		{"[ESTUDIANTE] resuelve problemas.", true},
		{"Li es muy breve para ser filtrado.", false}, // two-letter names are skipped
	}
	for _, c := range cases {
		if got := guard(c.text, names) != ""; got != c.reject {
			t.Errorf("guard(%q) rejected=%v, want %v", c.text, got, c.reject)
		}
	}
}

func TestComposeOrdersSectionsAndClosesSentences(t *testing.T) {
	body := compose(Result{
		Progress:                []Point{{Text: "Explica el problema con sus palabras"}},
		Difficulties:            []Point{{Text: "Aún confunde fracciones equivalentes."}},
		NoProgressJustification: "No logró aplicar la estrategia en situaciones nuevas",
		Recommendations:         []Point{{Text: "Practicar con material concreto"}, {Text: "Explicar en voz alta cada paso."}},
	})
	want := strings.Join([]string{
		"Explica el problema con sus palabras.",
		"Aún confunde fracciones equivalentes.",
		"No logró aplicar la estrategia en situaciones nuevas.",
		"Practicar con material concreto. Explicar en voz alta cada paso.",
	}, "\n\n")
	if body != want {
		t.Fatalf("body:\n%s\n--- want ---\n%s", body, want)
	}
}

func TestVarietyWarnings(t *testing.T) {
	// Only the variety codes: voice-note warnings are tested in TestWarnings.
	codes := func(ws []Warning) []string {
		var out []string
		for _, w := range ws {
			if strings.HasPrefix(w.Code, "evidence_") {
				out = append(out, w.Code)
			}
		}
		return out
	}
	// graded builds evidence the student has a score for; ungraded has none.
	graded := func(kind string, exp *uuid.UUID) repo.ConclusionEvidence {
		return repo.ConclusionEvidence{ID: uuid.New(), Kind: kind, ExperienceID: exp, ScoreStatus: ptr("graded")}
	}
	ungraded := func(kind string, exp *uuid.UUID) repo.ConclusionEvidence {
		return repo.ConclusionEvidence{ID: uuid.New(), Kind: kind, ExperienceID: exp}
	}
	exp1, exp2 := uuid.New(), uuid.New()
	withGraded := func(m Material) Material {
		for _, e := range m.Evidences {
			if e.Graded() {
				m.Graded++
			}
		}
		return m
	}
	cases := []struct {
		name  string
		m     Material
		codes []string
	}{
		{"two of one kind from one experience", withGraded(Material{Evidences: []repo.ConclusionEvidence{
			graded("produccion", &exp1), graded("produccion", &exp1)}}),
			[]string{WarnEvidenceSingleKind, WarnEvidenceSingleExperience}},
		{"two kinds from two experiences", withGraded(Material{Evidences: []repo.ConclusionEvidence{
			graded("produccion", &exp1), graded("actuacion", &exp2)}}), nil},
		{"two kinds from one experience", withGraded(Material{Evidences: []repo.ConclusionEvidence{
			graded("produccion", &exp1), graded("actuacion", &exp1)}}),
			[]string{WarnEvidenceSingleExperience}},
		{"below the minimum: nothing to say yet", withGraded(Material{Evidences: []repo.ConclusionEvidence{
			graded("produccion", &exp1)}}), nil},
		{"hand-added evidence never proves one experience", withGraded(Material{Evidences: []repo.ConclusionEvidence{
			graded("produccion", nil), graded("produccion", nil)}}),
			[]string{WarnEvidenceSingleKind}},
		{"ungraded evidence does not count", withGraded(Material{Evidences: []repo.ConclusionEvidence{
			graded("produccion", &exp1), graded("produccion", &exp2), ungraded("actuacion", &exp1)}}),
			[]string{WarnEvidenceSingleKind}},
	}
	for _, c := range cases {
		if got := codes(c.m.Warnings()); strings.Join(got, ",") != strings.Join(c.codes, ",") {
			t.Errorf("%s: warnings = %v, want %v", c.name, got, c.codes)
		}
	}
}

func TestWarnings(t *testing.T) {
	codes := func(ws []Warning) []string {
		var out []string
		for _, w := range ws {
			out = append(out, w.Code)
		}
		return out
	}
	usable := []repo.ConclusionVoiceNote{{}}
	cases := []struct {
		name  string
		m     Material
		codes []string
	}{
		{"every note discarded (worst case)", Material{NoteCounts: repo.VoiceNoteCounts{Discarded: 2, Pending: 1}},
			[]string{WarnAllVoiceNotesDiscarded, WarnVoiceNotesPending}},
		{"some discarded, some used", Material{VoiceNotes: usable, NoteCounts: repo.VoiceNoteCounts{Discarded: 1}},
			[]string{WarnVoiceNotesDiscarded}},
		{"no notes at all", Material{}, []string{WarnNoVoiceNotes}},
		{"all good", Material{VoiceNotes: usable}, nil},
	}
	for _, c := range cases {
		if got := codes(c.m.Warnings()); strings.Join(got, ",") != strings.Join(c.codes, ",") {
			t.Errorf("%s: warnings = %v, want %v", c.name, got, c.codes)
		}
	}
}
