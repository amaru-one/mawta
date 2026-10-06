// Press-and-hold voice recording built on MediaRecorder.
// The mic stream is kept warm after the first grant so subsequent
// recordings start instantly.

/**
 * Hard cap on a voice note, in seconds. The server enforces the same number,
 * so this is a recording fact rather than a view one — it lives here because
 * both the control that stops at the cap and the screen that counts down to it
 * need to agree with the server.
 */
export const MAX_RECORD_SEC = 60;

let stream: MediaStream | null = null;

async function getStream(): Promise<MediaStream | null> {
	if (stream && stream.getAudioTracks().some((t) => t.readyState === 'live')) return stream;
	try {
		stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		return stream;
	} catch {
		return null;
	}
}

export function releaseMicrophone(): void {
	stream?.getTracks().forEach((track) => track.stop());
	stream = null;
}

function pickMimeType(): string | undefined {
	const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
	return candidates.find((t) => MediaRecorder.isTypeSupported(t));
}

export interface ActiveRecording {
	stop: () => Promise<Blob | null>;
	cancel: () => void;
}

export async function startRecording(): Promise<ActiveRecording | null> {
	const s = await getStream();
	if (!s || typeof MediaRecorder === 'undefined') return null;

	const chunks: BlobPart[] = [];
	const mimeType = pickMimeType();
	const recorder = new MediaRecorder(s, mimeType ? { mimeType } : undefined);
	recorder.ondataavailable = (e: BlobEvent) => {
		if (e.data.size > 0) chunks.push(e.data);
	};
	recorder.start();

	let settled = false;
	return {
		stop: () =>
			new Promise<Blob | null>((resolve) => {
				if (settled || recorder.state === 'inactive') return resolve(null);
				settled = true;
				recorder.onstop = () => {
					resolve(chunks.length > 0 ? new Blob(chunks, { type: recorder.mimeType }) : null);
				};
				recorder.stop();
			}),
		cancel: () => {
			if (settled || recorder.state === 'inactive') return;
			settled = true;
			recorder.onstop = null;
			recorder.stop();
		},
	};
}

// Media elements are unreliable with MediaRecorder webm blobs (Infinity
// duration, stalled metadata), so decoding and playback go through Web Audio,
// which reads the actual samples.

let sharedCtx: AudioContext | null = null;

export function audioContext(): AudioContext {
	if (!sharedCtx) sharedCtx = new AudioContext();
	if (sharedCtx.state === 'suspended') void sharedCtx.resume();
	return sharedCtx;
}

export async function decodeBlob(blob: Blob): Promise<AudioBuffer | null> {
	try {
		const buffer = await blob.arrayBuffer();
		return await audioContext().decodeAudioData(buffer);
	} catch {
		return null;
	}
}

export function formatDuration(seconds: number): string {
	const s = Math.max(0, Math.round(seconds));
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
