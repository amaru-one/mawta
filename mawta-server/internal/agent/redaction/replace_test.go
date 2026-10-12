package redaction

import (
	"testing"

	"mawta-server/internal/repo"
)

func TestRedactReplacesEveryOccurrenceAndNumbersClassmates(t *testing.T) {
	transcript := []rune("Hoy Mari explicó bien, pero se distrajo con Yon y el chato. La mamá de Lucía vino. Yon volvió.")
	spans, err := locate(transcript, []fragment{
		{Text: "Mari", RefersTo: repo.RefersToAssignedStudent},
		{Text: "Yon", RefersTo: repo.RefersToClassmate, StudentKey: "S3"},
		{Text: "el chato", RefersTo: repo.RefersToOtherPerson},
		{Text: "Lucía", RefersTo: repo.RefersToClassmate, StudentKey: "S2"},
		{Text: "La mamá de Lucía", RefersTo: repo.RefersToOtherPerson},
	})
	if err != nil {
		t.Fatal(err)
	}
	got, tokens := redact(transcript, spans)
	want := "Hoy [ESTUDIANTE] explicó bien, pero se distrajo con [COMPAÑERO_1] y [PERSONA]. [PERSONA] vino. [COMPAÑERO_1] volvió."
	if got != want {
		t.Fatalf("redacted:\n got %q\nwant %q", got, want)
	}
	if len(tokens) != 5 {
		t.Fatalf("tokens = %v, want 5 replacements (Lucía is inside the longer fragment)", tokens)
	}
	for _, s := range spans {
		if string(transcript[s.start:s.end]) == "" {
			t.Fatalf("empty span %+v", s)
		}
	}
}

func TestLocateRejectsInventedFragmentsAndRespectsWordBoundaries(t *testing.T) {
	transcript := []rune("Ana trabajó con Mariana.")
	if _, err := locate(transcript, []fragment{{Text: "Pedro", RefersTo: repo.RefersToOtherPerson}}); err == nil {
		t.Fatal("a fragment absent from the transcript must be rejected")
	}
	// "Ana" must not match inside "Mariana".
	spans, err := locate(transcript, []fragment{{Text: "ana", RefersTo: repo.RefersToAssignedStudent}})
	if err != nil {
		t.Fatal(err)
	}
	if len(spans) != 1 || spans[0].start != 0 || spans[0].end != 3 {
		t.Fatalf("spans = %+v, want only the leading Ana (case-insensitive, whole word)", spans)
	}
}

func TestAttribution(t *testing.T) {
	classmate := span{frag: fragment{RefersTo: repo.RefersToClassmate}}
	assigned := span{frag: fragment{RefersTo: repo.RefersToAssignedStudent}}
	other := span{frag: fragment{RefersTo: repo.RefersToOtherPerson}}
	cases := []struct {
		name       string
		spans      []span
		unreadable bool
		reassigned bool
		status     string
		reason     string
	}{
		{"no one named", nil, false, false, repo.AttributionOK, ""},
		{"only other people", []span{other}, false, false, repo.AttributionOK, ""},
		{"student and classmate", []span{assigned, classmate}, false, false, repo.AttributionOK, ""},
		{"only a classmate", []span{classmate}, false, false, repo.AttributionDiscarded, repo.DiscardMentionsOtherStudent},
		{"unreadable", nil, true, false, repo.AttributionDiscarded, repo.DiscardUnreadable},
		{"teacher moved it", []span{classmate}, false, true, repo.AttributionReassigned, ""},
		{"moved but unreadable", nil, true, true, repo.AttributionDiscarded, repo.DiscardUnreadable},
	}
	for _, c := range cases {
		status, reason := attribution(c.spans, c.unreadable, c.reassigned)
		got := ""
		if reason != nil {
			got = *reason
		}
		if status != c.status || got != c.reason {
			t.Errorf("%s: got %s/%s, want %s/%s", c.name, status, got, c.status, c.reason)
		}
	}
}
