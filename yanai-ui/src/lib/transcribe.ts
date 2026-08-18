// Transcription is stubbed for MVP. This is the hook for a future
// speech-to-text integration (e.g. Whisper API): call it after a note is
// saved, then update `note.transcript` in IndexedDB as a background job.
// Not called anywhere yet.

export async function transcribeNote(blob: Blob): Promise<string | null> {
	void blob;
	return null;
}
