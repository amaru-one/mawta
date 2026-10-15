// A conclusión descriptiva is registered in SIAGIE, which accepts 10 to 350
// characters. Mirrors mawta-server/internal/domain/conclusion.go: the server
// normalizes and counts the same way and rejects anything outside the range,
// draft or final.

export const CONCLUSION_MIN_CHARS = 10;
export const CONCLUSION_MAX_CHARS = 350;

// One paragraph in NFC, with line breaks and runs of whitespace collapsed to a
// single space: the text as SIAGIE receives it.
export function normalizeConclusion(text: string): string {
	return text.normalize('NFC').split(/\s+/).filter(Boolean).join(' ');
}

// Characters (code points), not UTF-16 units, so it matches the server's count.
export function conclusionLength(text: string): number {
	return [...text].length;
}
