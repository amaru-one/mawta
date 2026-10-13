import { writable, type Writable } from 'svelte/store';

export interface Toast {
	id: number;
	message: string;
	tone: 'info' | 'error';
	undoLabel?: string;
	onUndo?: () => void;
	durationMs: number;
}

export const toast: Writable<Toast | null> = writable(null);

let nextId = 1;

export function showToast(
	message: string,
	options?: { onUndo?: () => void; undoLabel?: string; durationMs?: number; tone?: Toast['tone'] }
): void {
	const durationMs = options?.durationMs ?? (options?.onUndo ? 7000 : 2000);
	toast.set({
		id: nextId++,
		message,
		tone: options?.tone ?? 'info',
		undoLabel: options?.onUndo ? (options.undoLabel ?? 'Deshacer') : undefined,
		onUndo: options?.onUndo,
		durationMs,
	});
}

// A failure stays long enough to read and offers a retry in the action slot.
export function showError(message: string, options?: { onRetry?: () => void }): void {
	showToast(message, {
		tone: 'error',
		onUndo: options?.onRetry,
		undoLabel: 'Reintentar',
		durationMs: 6000,
	});
}

export function dismissToast(id?: number): void {
	toast.update((current) => (id === undefined || current?.id === id ? null : current));
}
