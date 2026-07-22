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
		background: var(--neutral-900);
		color: white;
		font-size: 14px;
		padding: var(--space-md) var(--space-lg);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		white-space: nowrap;
	}

	.undo {
		color: #7cc7f0;
		font-weight: 700;
		padding: var(--space-xs) var(--space-sm);
		margin: calc(-1 * var(--space-xs)) calc(-1 * var(--space-sm));
	}

	@media (min-width: 768px) {
		.toast {
			bottom: auto;
			top: var(--space-xl);
			left: auto;
			right: var(--space-xl);
			transform: none;
		}
	}
</style>
