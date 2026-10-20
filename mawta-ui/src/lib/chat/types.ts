// Protocol v1 between mawta-chat and this UI (mawta-chat/src/protocol.py).
// Saved blocks and streamed events share their shapes; a streamed `texto`
// carries a `delta`, a saved one the whole `md`.

export type TextBlock = { tipo: 'texto'; md: string };
export type TableBlock = {
	tipo: 'tabla';
	titulo: string;
	columnas: string[];
	filas: (string | number | null)[][];
	nota?: string;
};
export type ErrorBlock = { tipo: 'error'; codigo: string; mensaje: string };
// Any block type this UI does not know yet (e.g. `grafico` before level 1)
// is kept and ignored when rendering.
export type UnknownBlock = { tipo: string; [key: string]: unknown };
export type Block = TextBlock | TableBlock | ErrorBlock | UnknownBlock;

export type Thread = { id: string; title: string; created_at: string; updated_at: string };

export type Message = {
	id: string;
	author: 'director' | 'mawta';
	protocol_version: number;
	blocks: Block[];
	created_at: string;
};

export type StreamEvent =
	| { version: number; tipo: 'estado'; texto: string }
	| { version: number; tipo: 'texto'; delta: string }
	| ({ version: number } & TableBlock)
	| ({ version: number } & ErrorBlock)
	| { version: number; tipo: 'fin'; message_id: string }
	| ({ version: number } & UnknownBlock);

export function isTextBlock(block: Block): block is TextBlock {
	return block.tipo === 'texto' && typeof (block as TextBlock).md === 'string';
}
export function isTableBlock(block: Block): block is TableBlock {
	return block.tipo === 'tabla' && Array.isArray((block as TableBlock).filas);
}
export function isErrorBlock(block: Block): block is ErrorBlock {
	return block.tipo === 'error';
}
