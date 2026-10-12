package redaction

import (
	"fmt"
	"sort"
	"strings"
	"unicode"

	"mawta-server/internal/repo"
)

// fragment is one person reference the model pointed at: the exact words as
// they appear in the transcript, who they refer to and, for a classmate, the
// roster key it matched.
type fragment struct {
	Text       string `json:"text"`
	RefersTo   string `json:"refers_to"`
	StudentKey string `json:"student_key"`
}

// span is one occurrence of a fragment in the transcript, in runes.
type span struct {
	start, end int
	frag       fragment
}

// Replacement tokens left in transcript_redacted.
const (
	tokenStudent = "[ESTUDIANTE]"
	tokenPerson  = "[PERSONA]"
)

func classmateToken(n int) string { return fmt.Sprintf("[COMPAÑERO_%d]", n) }

// locate finds every whole-word occurrence of each fragment. The model is
// told to copy fragments exactly; a case difference is forgiven, anything
// else is not: a fragment that does not occur is an error the model gets one
// chance to fix. Longer fragments claim their text first, so "la mamá de
// Lucía" wins over "Lucía" inside it; a fragment whose every occurrence lies
// inside a longer one is fine.
func locate(transcript []rune, frags []fragment) ([]span, error) {
	order := make([]int, len(frags))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(a, b int) bool {
		return len([]rune(frags[order[a]].Text)) > len([]rune(frags[order[b]].Text))
	})

	claimed := make([]bool, len(transcript))
	var spans []span
	for _, i := range order {
		f := frags[i]
		needle := []rune(f.Text)
		found := false
		for start := 0; start+len(needle) <= len(transcript); start++ {
			end := start + len(needle)
			if !equalFold(transcript[start:end], needle) || !wordBoundary(transcript, start, end) {
				continue
			}
			found = true
			if anyClaimed(claimed, start, end) {
				continue
			}
			for k := start; k < end; k++ {
				claimed[k] = true
			}
			spans = append(spans, span{start: start, end: end, frag: f})
		}
		if !found {
			return nil, fmt.Errorf("el fragmento %q no aparece en la transcripción; copia el texto exacto", f.Text)
		}
	}
	sort.Slice(spans, func(a, b int) bool { return spans[a].start < spans[b].start })
	return spans, nil
}

func equalFold(a, b []rune) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] && unicode.ToLower(a[i]) != unicode.ToLower(b[i]) {
			return false
		}
	}
	return true
}

func isWordRune(r rune) bool { return unicode.IsLetter(r) || unicode.IsDigit(r) }

func wordBoundary(s []rune, start, end int) bool {
	if start > 0 && isWordRune(s[start-1]) && isWordRune(s[start]) {
		return false
	}
	if end < len(s) && isWordRune(s[end]) && isWordRune(s[end-1]) {
		return false
	}
	return true
}

func anyClaimed(claimed []bool, start, end int) bool {
	for k := start; k < end; k++ {
		if claimed[k] {
			return true
		}
	}
	return false
}

// redact builds the redacted transcript from spans sorted by start, and the
// replacement token of each span. Classmates are numbered by first
// appearance, and the same classmate keeps the same number.
func redact(transcript []rune, spans []span) (string, []string) {
	numbers := map[string]int{}
	tokens := make([]string, len(spans))
	var b strings.Builder
	prev := 0
	for i, s := range spans {
		switch s.frag.RefersTo {
		case repo.RefersToAssignedStudent:
			tokens[i] = tokenStudent
		case repo.RefersToClassmate:
			n, ok := numbers[s.frag.StudentKey]
			if !ok {
				n = len(numbers) + 1
				numbers[s.frag.StudentKey] = n
			}
			tokens[i] = classmateToken(n)
		default:
			tokens[i] = tokenPerson
		}
		b.WriteString(string(transcript[prev:s.start]))
		b.WriteString(tokens[i])
		prev = s.end
	}
	b.WriteString(string(transcript[prev:]))
	return b.String(), tokens
}

// attribution decides whether a swept note is usable as evidence of its
// assigned student. A note that names classmates and never the assigned
// student was most likely recorded on the wrong student. reassigned means a
// teacher moved the note on purpose: that decision stands unless the note
// cannot be read at all.
func attribution(spans []span, unreadable, reassigned bool) (status string, reason *string) {
	if unreadable {
		r := repo.DiscardUnreadable
		return repo.AttributionDiscarded, &r
	}
	if reassigned {
		return repo.AttributionReassigned, nil
	}
	var assigned, classmate bool
	for _, s := range spans {
		switch s.frag.RefersTo {
		case repo.RefersToAssignedStudent:
			assigned = true
		case repo.RefersToClassmate:
			classmate = true
		}
	}
	if classmate && !assigned {
		r := repo.DiscardMentionsOtherStudent
		return repo.AttributionDiscarded, &r
	}
	return repo.AttributionOK, nil
}
