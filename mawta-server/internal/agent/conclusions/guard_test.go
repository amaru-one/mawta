package conclusions

import (
	"strings"
	"testing"

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
