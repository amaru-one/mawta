package conclusions

import (
	"regexp"
	"strings"
	"unicode"

	"mawta-server/internal/repo"
)

// The last check before a proposal reaches a teacher (and, once saved, SIAGIE):
// no replacement token and no name of a student on the roster may appear in
// the text. It is not a redaction method — the sweep already ran on the voice
// notes — but a net for whatever slipped through, including names the teacher
// wrote in a score's feedback.

var tokenPattern = regexp.MustCompile(`\[[^\]\s]{2,}\]`)

// guard returns why a text cannot be used, or "" when it can.
func guard(text string, names []string) string {
	if t := tokenPattern.FindString(text); t != "" {
		return "el texto contiene la marca " + t + "; escribe sin nombres ni marcas, en tercera persona"
	}
	words := tokenize(text)
	for _, name := range names {
		if containsName(words, name) {
			return "el texto contiene un nombre de estudiante («" + name + "»); nunca nombres a nadie"
		}
	}
	return ""
}

// nameWords lists the individual names of the students that the output must
// not contain. Very short names (two letters or fewer) are skipped: they
// collide with ordinary words.
func nameWords(students []repo.StudentName) []string {
	seen := map[string]bool{}
	var out []string
	add := func(s string) {
		for _, w := range strings.Fields(s) {
			if len([]rune(w)) <= 2 || seen[fold(w)] {
				continue
			}
			seen[fold(w)] = true
			out = append(out, w)
		}
	}
	for _, s := range students {
		add(s.GivenName)
		add(s.PaternalSurname)
		if s.PreferredName != nil {
			add(*s.PreferredName)
		}
		if s.MaternalSurname != nil {
			add(*s.MaternalSurname)
		}
	}
	return out
}

type word struct {
	folded      string
	capitalized bool
}

func tokenize(text string) []word {
	var out []word
	for _, w := range strings.FieldsFunc(text, func(r rune) bool { return !unicode.IsLetter(r) }) {
		r := []rune(w)
		out = append(out, word{folded: fold(w), capitalized: unicode.IsUpper(r[0])})
	}
	return out
}

// containsName reports whether a name occurs as a capitalised word: a name
// that is also a common word ("Rosa", "Flor") only counts when written as a
// name, so "una flor" in a science conclusion is not rejected.
func containsName(words []word, name string) bool {
	target := fold(name)
	for _, w := range words {
		if w.capitalized && w.folded == target {
			return true
		}
	}
	return false
}

var accents = strings.NewReplacer("á", "a", "é", "e", "í", "i", "ó", "o", "ú", "u", "ü", "u", "à", "a", "è", "e", "ì", "i", "ò", "o", "ù", "u")

// fold lowercases and strips accents, so "María" and "Maria" are one name.
func fold(s string) string { return accents.Replace(strings.ToLower(s)) }
