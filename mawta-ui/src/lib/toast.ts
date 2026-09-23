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
let hideTimer: ReturnType<typeof setTimeout> | undefined;

export function showToast(message: string, options?: { onUndo?: () => void; durationMs?: number }): void {
	const durationMs = options?.durationMs ?? (options?.onUndo ? 2000 : 1500);
	clearTimeout(hideTimer);
	toast.set({
		id: nextId++,
		message,
		undoLabel: options?.onUndo ? 'Undo' : undefined,
		onUndo: options?.onUndo,
		durationMs
	});
	hideTimer = setTimeout(() => toast.set(null), durationMs);
}

export function dismissToast(): void {
	clearTimeout(hideTimer);
	toast.set(null);
}
