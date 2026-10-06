<script lang="ts">
	import { onMount } from 'svelte';
	import type { ToastMessage } from './types';
	let {
		message = null,
		ondismiss,
	}: { message?: ToastMessage | null; ondismiss: (id: ToastMessage['id']) => void } = $props();
	let element: HTMLDivElement;
	let dismissedId = $state<ToastMessage['id'] | null>(null);
	let mounted = $state(false);
	onMount(() => {
		mounted = true;
	});
	$effect(() => {
		const current = message;
		if (!mounted || !element || !current || current.id === dismissedId) return;
		element.showPopover();
		const timer = setTimeout(
			() => dismiss(current),
			current.durationMs ?? (current.onaction ? 7000 : 2000)
		);
		return () => {
			clearTimeout(timer);
			element?.hidePopover();
		};
	});
	function dismiss(current: ToastMessage) {
		dismissedId = current.id;
		ondismiss(current.id);
	}
	function act() {
		const current = message;
		if (!current || current.id === dismissedId) return;
		dismiss(current);
		current.onaction?.();
	}
</script>

<div
	bind:this={element}
	popover="manual"
	class="mw-toast"
	role="status"
	aria-live="polite"
	aria-atomic="true"
>
	{#if message}<span>{message.message}</span>{#if message.onaction}<button
				type="button"
				onclick={act}>{message.actionLabel ?? 'Deshacer'}</button
			>{/if}{/if}
</div>
