package domain

import (
	"strings"
	"unicode/utf8"

	"golang.org/x/text/unicode/norm"
)

// A conclusión descriptiva is registered in SIAGIE, which accepts 10 to 350
// characters. Every conclusion respects it, draft or final: the agent writes
// for SIAGIE and the teacher never holds a text that could not be exported.
const (
	ConclusionMinChars = 10
	ConclusionMaxChars = 350
)

// NormalizeConclusion puts a conclusion in the shape SIAGIE receives: one
// paragraph in NFC, with line breaks and runs of whitespace collapsed to a
// single space. NFC matters for the count: a decomposed "á" is two runes.
func NormalizeConclusion(s string) string {
	return strings.Join(strings.Fields(norm.NFC.String(s)), " ")
}

// ConclusionLength counts characters, not bytes: "ñ" is one character but
// two bytes in UTF-8.
func ConclusionLength(s string) int { return utf8.RuneCountInString(s) }
