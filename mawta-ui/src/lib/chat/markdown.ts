// A deliberately small Markdown renderer for the model's answers. Everything
// is HTML-escaped first, so nothing the model writes can become markup; only
// paragraphs, line breaks, lists, bold, italics, inline code and headings
// (shown as bold lines) are turned back into tags.

const ESCAPES: Record<string, string> = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;',
};

export function escapeHtml(text: string): string {
	return text.replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

function inline(text: string): string {
	return escapeHtml(text)
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
		.replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, '$1<em>$2</em>')
		.replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g, '$1<em>$2</em>');
}

const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
const HEADING = /^\s*#{1,6}\s+/;

type List = { tag: 'ul' | 'ol'; items: string[] };

export function renderMarkdown(source: string): string {
	const html: string[] = [];
	for (const block of source.replace(/\r\n?/g, '\n').split(/\n{2,}/)) {
		const lines = block.split('\n').filter((line) => line.trim() !== '');
		const open: { paragraph: string[]; list: List | null } = { paragraph: [], list: null };
		const flushParagraph = () => {
			if (open.paragraph.length) html.push(`<p>${open.paragraph.join('<br>')}</p>`);
			open.paragraph = [];
		};
		const flushList = () => {
			const list = open.list;
			if (list)
				html.push(`<${list.tag}>${list.items.map((i) => `<li>${i}</li>`).join('')}</${list.tag}>`);
			open.list = null;
		};
		for (const line of lines) {
			const tag = BULLET.test(line) ? 'ul' : NUMBERED.test(line) ? 'ol' : null;
			if (tag) {
				flushParagraph();
				if (open.list && open.list.tag !== tag) flushList();
				open.list ??= { tag, items: [] };
				open.list.items.push(inline(line.replace(tag === 'ul' ? BULLET : NUMBERED, '')));
			} else if (HEADING.test(line)) {
				flushParagraph();
				flushList();
				html.push(`<p><strong>${inline(line.replace(HEADING, ''))}</strong></p>`);
			} else {
				flushList();
				open.paragraph.push(inline(line.trim()));
			}
		}
		flushParagraph();
		flushList();
	}
	return html.join('');
}
