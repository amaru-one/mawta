package domain

import "testing"

func TestNormalizeConclusion(t *testing.T) {
	cases := []struct{ in, want string }{
		{"  Explica  el problema.\n\nSe recomienda  practicar. ", "Explica el problema. Se recomienda practicar."},
		{"Ana\r\nlee", "Ana lee"},
		// A decomposed "á" (a + combining acute) becomes one character.
		{"Practicá", "Practicá"},
	}
	for _, c := range cases {
		if got := NormalizeConclusion(c.in); got != c.want {
			t.Errorf("NormalizeConclusion(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestConclusionLengthCountsCharacters(t *testing.T) {
	if got := ConclusionLength("año"); got != 3 {
		t.Fatalf("ConclusionLength(año) = %d, want 3 (characters, not bytes)", got)
	}
	if got := ConclusionLength(NormalizeConclusion("á")); got != 1 {
		t.Fatalf("a decomposed á counts %d, want 1 after normalizing", got)
	}
}
