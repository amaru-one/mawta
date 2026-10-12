<script lang="ts">
	import { Toast } from '$lib/design-system';
	import { dismissToast, toast } from '$lib/toast';
	const message = $derived(
		$toast
			? {
					id: $toast.id,
					message: $toast.message,
					tone: $toast.tone,
					actionLabel: $toast.undoLabel,
					onaction: $toast.onUndo,
					durationMs: $toast.durationMs,
				}
			: null
	);
</script>

<Toast {message} ondismiss={(id) => dismissToast(Number(id))} />
