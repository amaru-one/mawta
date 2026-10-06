import { writable } from 'svelte/store';

import type { GenerationDto } from './dto';
import { getGeneration } from './endpoints/planning';

// "✦ Generar con Mawta" runs in the background: a route starts a generation
// and the app polls it. One helper for every screen.

const POLL_MS = 1500;
// The server reads a generation as failed 5 minutes after it was requested;
// a little more here so the server's own message is the one shown.
const GIVE_UP_MS = 6 * 60 * 1000;
// Network blips while waiting are tolerated; this many in a row give up.
const MAX_NETWORK_ERRORS = 3;

export const GENERATION_TIMEOUT_TEXT =
	'Mawta tardó demasiado en responder. Intenta de nuevo o escríbelo a mano.';

export class GenerationAborted extends Error {
	constructor() {
		super('generation wait aborted');
	}
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
	return new Promise((resolve, reject) => {
		if (signal?.aborted) return reject(new GenerationAborted());
		const timer = setTimeout(resolve, ms);
		signal?.addEventListener(
			'abort',
			() => {
				clearTimeout(timer);
				reject(new GenerationAborted());
			},
			{ once: true }
		);
	});
}

// waitForGeneration polls until the generation completes or fails. It stops
// (GenerationAborted) when signal aborts — the screen was left — and returns
// a failed generation if the wait runs past the server's deadline.
export async function waitForGeneration(
	generation: GenerationDto,
	signal?: AbortSignal
): Promise<GenerationDto> {
	const startedAt = Date.now();
	let current = generation;
	let networkErrors = 0;
	while (current.status !== 'completed' && current.status !== 'failed') {
		if (Date.now() - startedAt > GIVE_UP_MS) {
			return { ...current, status: 'failed', error: GENERATION_TIMEOUT_TEXT };
		}
		await sleep(POLL_MS, signal);
		try {
			current = await getGeneration(generation.id);
			networkErrors = 0;
		} catch (error) {
			if (signal?.aborted) throw new GenerationAborted();
			networkErrors++;
			if (networkErrors >= MAX_NETWORK_ERRORS) throw error;
		}
	}
	return current;
}

// agentUnavailable is set once the server answers agent_unavailable (no model
// configured), so every planning screen hides "✦ Generar con Mawta" for the
// rest of the visit and offers manual creation only.
export const agentUnavailable = writable(false);
