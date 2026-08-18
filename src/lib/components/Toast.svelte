<script lang="ts">
	import { fade } from 'svelte/transition';
	import { dismissToast, toast } from '$lib/toast';

	function undo(): void {
		const current = $toast;
		dismissToast();
		current?.onUndo?.();
	}
</script>

{#if $toast}
	{#key $toast.id}
		<div class="toast" transition:fade={{ duration: 150 }} role="status">
			<span>{$toast.message}</span>
			{#if $toast.undoLabel}
				<button class="undo pressable" onclick={undo}>{$toast.undoLabel}</button>
			{/if}
		</div>
	{/key}
{/if}

<style>
	.toast {
		position: fixed;
		bottom: var(--space-xl);
		left: 50%;
		transform: translateX(-50%);
		z-index: 100;
		display: flex;
		align-items: center;
		gap: var(--space-md);
		background: var(--fill-primary);
		color: var(--on-primary);
		font-size: 14px;
		padding: var(--space-md) var(--space-lg);
		border-radius: var(--radius);
		box-shadow: var(--shadow-lg);
		white-space: nowrap;
		max-width: calc(100vw - 2 * var(--space-lg));
	}

	/* Deliberately not the accent — that stays reserved for assistant output. */
	.undo {
		color: var(--on-primary);
		text-decoration: underline;
		font-weight: 500;
		padding: var(--space-xs) var(--space-sm);
		margin: calc(-1 * var(--space-xs)) calc(-1 * var(--space-sm));
	}
</style>
