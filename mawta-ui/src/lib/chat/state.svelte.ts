// The director's chat list, shared by the /direccion layout (sidebar) and its
// pages, plus a question waiting to be sent once its new chat opens.
import { ApiError } from '$lib/api/client';
import { createThread, listThreads } from './api';
import type { Thread } from './types';

type Status = 'loading' | 'ready' | 'error' | 'unavailable';

class ChatList {
	threads = $state<Thread[]>([]);
	status = $state<Status>('loading');
	// A suggestion picked before its chat existed: the chat page sends it.
	pendingQuestion = $state<string | null>(null);

	async load(): Promise<void> {
		try {
			this.threads = await listThreads();
			this.status = 'ready';
		} catch (err) {
			this.status =
				err instanceof ApiError && err.code === 'chat_unavailable' ? 'unavailable' : 'error';
		}
	}

	// Refreshes titles and order after an answer, without a loading state.
	async refresh(): Promise<void> {
		try {
			this.threads = await listThreads();
		} catch {
			// The list stays as it was; the next refresh tries again.
		}
	}

	async create(): Promise<Thread> {
		const thread = await createThread();
		this.threads = [thread, ...this.threads];
		return thread;
	}

	replace(thread: Thread): void {
		this.threads = this.threads.map((t) => (t.id === thread.id ? thread : t));
	}

	remove(id: string): void {
		this.threads = this.threads.filter((t) => t.id !== id);
	}
}

export const chatList = new ChatList();
