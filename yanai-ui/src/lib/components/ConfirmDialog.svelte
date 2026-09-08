<script lang="ts">
	import { scale } from 'svelte/transition';

	interface Props {
		title: string;
		text: string;
		confirmLabel: string;
		onconfirm: () => void;
		oncancel: () => void;
	}

	let { title, text, confirmLabel, onconfirm, oncancel }: Props = $props();

	const titleId = `confirm-${Math.random().toString(36).slice(2, 8)}`;
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && oncancel()} />

<div
	class="dialog"
	in:scale={{ start: 0.95, duration: 150 }}
	out:scale={{ start: 0.95, duration: 150 }}
	role="alertdialog"
	aria-modal="true"
	aria-labelledby={titleId}
>
	<button class="backdrop" onclick={oncancel} aria-label="Cerrar diálogo" tabindex="-1"></button>
	<div class="content">
		<p class="title" id={titleId}>{title}</p>
		<p class="text">{text}</p>
		<div class="actions">
			<button class="cancel pressable" onclick={oncancel}>Cancelar</button>
			<button class="confirm pressable" onclick={onconfirm}>{confirmLabel}</button>
		</div>
	</div>
</div>

<style>
	.dialog {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 2000;
		padding: var(--space-lg);
	}

	.backdrop {
		position: absolute;
		inset: 0;
		background: rgba(22, 24, 58, 0.55);
		border: none;
		cursor: pointer;
	}

	.content {
		position: relative;
		background: var(--surface-2);
		border-radius: var(--radius-lg);
		padding: var(--space-xl);
		max-width: 320px;
		box-shadow: var(--shadow-lg);
	}

	.title {
		margin: 0 0 var(--space-sm);
		font-size: 16px;
		font-weight: 500;
	}

	.text {
		margin: 0 0 20px;
		font-size: 14px;
		color: var(--text-secondary);
	}

	.actions {
		display: flex;
		gap: var(--space-md);
		justify-content: flex-end;
	}

	.cancel,
	.confirm {
		padding: 10px var(--space-lg);
		min-height: 36px;
		border-radius: var(--radius-md);
		font-size: 14px;
		font-weight: 500;
	}

	.cancel {
		background: var(--surface-1);
		color: var(--text-primary);
	}

	.confirm {
		background: var(--fill-danger);
		color: var(--on-danger);
	}
</style>
