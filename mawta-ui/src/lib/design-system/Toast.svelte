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
	// Hover and focus both hold the timer; it restarts only when every hold is released.
	let hold: { pause: () => void; resume: () => void } | null = null;
	onMount(() => {
		mounted = true;
	});
	$effect(() => {
		const current = message;
		if (!mounted || !element || !current || current.id === dismissedId) return;
		element.showPopover();
		let remaining = current.durationMs ?? (current.onaction ? 7000 : 2000);
		let startedAt = 0;
		let holds = 0;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const start = () => {
			startedAt = Date.now();
			timer = setTimeout(() => dismiss(current), remaining);
		};
		hold = {
			pause() {
				holds += 1;
				if (timer === undefined) return;
				clearTimeout(timer);
				timer = undefined;
				remaining -= Date.now() - startedAt;
			},
			resume() {
				if (holds === 0) return;
				holds -= 1;
				if (holds > 0 || timer !== undefined) return;
				if (remaining <= 0) dismiss(current);
				else start();
			},
		};
		start();
		return () => {
			clearTimeout(timer);
			hold = null;
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
	role={message?.tone === 'error' ? 'alert' : 'status'}
	aria-live={message?.tone === 'error' ? 'assertive' : 'polite'}
	aria-atomic="true"
	onpointerenter={() => hold?.pause()}
	onpointerleave={() => hold?.resume()}
	onfocusin={() => hold?.pause()}
	onfocusout={() => hold?.resume()}
>
	{#if message}<span>{message.message}</span>{#if message.onaction}<button
				type="button"
				onclick={act}>{message.actionLabel ?? 'Deshacer'}</button
			>{/if}{/if}
</div>
