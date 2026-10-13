export interface BatchResult<T> {
	done: number;
	failed: T[];
}

// Runs one request per item, in order, so the server sees one change at a time.
// A failure does not stop the batch: the failed items come back for a retry.
export async function runSequential<T>(
	items: readonly T[],
	run: (item: T) => Promise<unknown>,
	onProgress?: (completed: number, total: number) => void
): Promise<BatchResult<T>> {
	const failed: T[] = [];
	let done = 0;
	for (const item of items) {
		try {
			await run(item);
			done += 1;
		} catch {
			failed.push(item);
		}
		onProgress?.(done + failed.length, items.length);
	}
	return { done, failed };
}
