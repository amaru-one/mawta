// Server-Sent Events reader. The answer is a POST with an Authorization
// header, which EventSource cannot send, so the stream is read with fetch.
// Network chunks do not respect event boundaries: an event can arrive split
// across chunks, several can arrive in one, and sse-starlette ends lines with
// \r\n, whose two characters can themselves land in different chunks.

export function createSseParser(onData: (data: string) => void) {
	let buffer = '';

	function drain(final: boolean): void {
		let text = buffer;
		// A trailing \r may be the first half of \r\n: keep it for the next chunk.
		const hold = !final && text.endsWith('\r') ? '\r' : '';
		if (hold) text = text.slice(0, -1);
		text = text.replace(/\r\n|\r/g, '\n');
		let end: number;
		while ((end = text.indexOf('\n\n')) !== -1) {
			emit(text.slice(0, end));
			text = text.slice(end + 2);
		}
		if (final && text.trim()) {
			emit(text);
			text = '';
		}
		buffer = text + hold;
	}

	function emit(raw: string): void {
		const data = raw
			.split('\n')
			.filter((line) => line.startsWith('data:'))
			.map((line) => line.slice(5).replace(/^ /, ''))
			.join('\n');
		if (data) onData(data);
	}

	return {
		push(chunk: string): void {
			buffer += chunk;
			drain(false);
		},
		end(): void {
			drain(true);
		},
	};
}

export async function readSse(
	body: ReadableStream<Uint8Array>,
	onEvent: (event: unknown) => void
): Promise<void> {
	const parser = createSseParser((data) => {
		try {
			onEvent(JSON.parse(data));
		} catch {
			// A malformed event is skipped; the next one still arrives.
		}
	});
	const decoder = new TextDecoder();
	const reader = body.getReader();
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		// stream: true keeps a multi-byte character split across chunks intact.
		parser.push(decoder.decode(value, { stream: true }));
	}
	parser.push(decoder.decode());
	parser.end();
}
