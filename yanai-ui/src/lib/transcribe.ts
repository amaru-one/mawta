// Transcription is stubbed for MVP. This is the hook for a future
// speech-to-text integration (e.g. Whisper API): call it after a note is
// saved, then update `note.transcript`.
//
// Not called anywhere yet, and there is no longer an endpoint to post a
// transcript to — `POST /voice-notes/{id}/transcript` was removed on
// 2026-08-29 as an unreachable route. Wiring this up means bringing that
// endpoint back with the code that actually produces a transcript.

export async function transcribeNote(blob: Blob): Promise<string | null> {
	void blob;
	return null;
}
