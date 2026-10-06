import { writable, type Writable } from 'svelte/store';

export interface Toast {
	id: number;
	message: string;
	undoLabel?: string;
	onUndo?: () => void;
	durationMs: number;
}

export const toast: Writable<Toast | null> = writable(null);

let nextId = 1;

export function showToast(
	message: string,
	options?: { onUndo?: () => void; undoLabel?: string; durationMs?: number }
): void {
	const durationMs = options?.durationMs ?? (options?.onUndo ? 7000 : 2000);
	toast.set({
		id: nextId++,
		message,
		undoLabel: options?.onUndo ? (options.undoLabel ?? 'Deshacer') : undefined,
		onUndo: options?.onUndo,
		durationMs,
	});
}

export function dismissToast(id?: number): void {
	toast.update((current) => (id === undefined || current?.id === id ? null : current));
}
