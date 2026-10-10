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
	m := Material{NoteCounts: repo.VoiceNoteCounts{Discarded: 2, Pending: 1}}
	got := m.Warnings()
	if len(got) != 3 || got[0].Code != WarnVoiceNotesDiscarded || got[0].Count != 2 ||
		got[1].Code != WarnVoiceNotesPending || got[2].Code != WarnNoVoiceNotes {
		t.Fatalf("warnings = %+v", got)
	}
	m.VoiceNotes = []repo.ConclusionVoiceNote{{}}
	m.NoteCounts = repo.VoiceNoteCounts{}
	if got := m.Warnings(); len(got) != 0 {
		t.Fatalf("no warnings expected, got %+v", got)
	}
}
