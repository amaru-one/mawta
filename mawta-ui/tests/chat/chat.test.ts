import { afterEach, describe, expect, test, vi } from 'vitest';
import { groupThreads } from '../../src/lib/chat/groups';
import { renderMarkdown } from '../../src/lib/chat/markdown';
import { createSseParser, readSse } from '../../src/lib/chat/sse';
import { chatToken, forgetChatToken } from '../../src/lib/chat/token';

describe('SSE reader', () => {
	test('splits events whatever the network chunks look like', () => {
		const events: string[] = [];
		const parser = createSseParser((data) => events.push(data));
		// sse-starlette ends lines with \r\n; the \r and \n land in different chunks.
		const stream = 'event: estado\r\ndata: {"a":1}\r\n\r\nevent: texto\r\ndata: {"b":2}\r\n\r\n';
		for (const chunk of [
			stream.slice(0, 10),
			stream.slice(10, 31),
			stream.slice(31, 33),
			stream.slice(33),
		]) {
			parser.push(chunk);
		}
		parser.end();
		expect(events).toEqual(['{"a":1}', '{"b":2}']);
	});

	test('keeps several events of one chunk and ignores comments', () => {
		const events: string[] = [];
		const parser = createSseParser((data) => events.push(data));
		parser.push(': ping\n\ndata: 1\n\ndata: 2\n\n');
		parser.end();
		expect(events).toEqual(['1', '2']);
	});

	test('decodes a multi-byte character split across chunks', async () => {
		const bytes = new TextEncoder().encode('data: {"texto":"Mañana"}\r\n\r\n');
		const cut = bytes.indexOf(0xc3) + 1; // inside the two bytes of "ñ"
		const body = new ReadableStream<Uint8Array>({
			start(controller) {
				controller.enqueue(bytes.slice(0, cut));
				controller.enqueue(bytes.slice(cut));
				controller.close();
			},
		});
		const events: unknown[] = [];
		await readSse(body, (event) => events.push(event));
		expect(events).toEqual([{ texto: 'Mañana' }]);
	});
});

describe('Markdown', () => {
	test('never renders markup the model wrote', () => {
		const html = renderMarkdown('<script>alert(1)</script> <img src=x onerror=alert(1)>');
		expect(html).not.toContain('<script');
		expect(html).not.toContain('<img');
		expect(html).toContain('&lt;script&gt;');
	});

	test('renders bold, italics, lists and paragraphs', () => {
		const html = renderMarkdown(
			'Hay **una** sección, *activa*.\n\n- 1.° A\n- 1.° B\n\n1. uno\n2. dos'
		);
		expect(html).toBe(
			'<p>Hay <strong>una</strong> sección, <em>activa</em>.</p>' +
				'<ul><li>1.° A</li><li>1.° B</li></ul>' +
				'<ol><li>uno</li><li>dos</li></ol>'
		);
	});
});

describe('Chat list groups', () => {
	test('groups threads by how recently they were used', () => {
		const now = new Date(2026, 9, 18, 12, 0);
		const at = (daysBack: number) => new Date(2026, 9, 18 - daysBack, 9, 0).toISOString();
		const thread = (id: string, daysBack: number) => ({
			id,
			title: id,
			created_at: at(daysBack),
			updated_at: at(daysBack),
		});
		const groups = groupThreads(
			[thread('a', 0), thread('b', 1), thread('c', 3), thread('d', 30)],
			now
		);
		expect(groups.map((g) => [g.label, g.threads.map((t) => t.id)])).toEqual([
			['Hoy', ['a']],
			['Ayer', ['b']],
			['Esta semana', ['c']],
			['Anteriores', ['d']],
		]);
	});
});

describe('Chat token', () => {
	afterEach(() => {
		forgetChatToken();
		vi.unstubAllGlobals();
	});

	function serveTokens(minutesLeft: number) {
		let n = 0;
		const fetchMock = vi.fn(async () => {
			n += 1;
			const expires_at = new Date(Date.now() + minutesLeft * 60_000).toISOString();
			return new Response(JSON.stringify({ token: `t${n}`, expires_at }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' },
			});
		});
		vi.stubGlobal('fetch', fetchMock);
		return fetchMock;
	}

	test('is asked once, shared by concurrent callers and cached', async () => {
		const fetchMock = serveTokens(60);
		const [a, b] = await Promise.all([chatToken(), chatToken()]);
		expect([a, b]).toEqual(['t1', 't1']);
		expect(await chatToken()).toBe('t1');
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	test('is renewed when less than five minutes are left, or on demand', async () => {
		serveTokens(3);
		expect(await chatToken()).toBe('t1');
		expect(await chatToken()).toBe('t2');
		forgetChatToken();
		serveTokens(60);
		expect(await chatToken()).toBe('t1');
		expect(await chatToken(true)).toBe('t2');
	});
});
