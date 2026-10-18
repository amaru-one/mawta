<script lang="ts">
	import { Icon } from '$lib/design-system';
	let { mensaje, onretry }: { mensaje: string; onretry?: () => void } = $props();
</script>

<div class="error" role="alert">
	<Icon name="alert" size={18} />
	<div>
		<span>{mensaje}</span>
		{#if onretry}<button type="button" class="retry" onclick={onretry}>Reintentar</button>{/if}
	</div>
</div>

<style>
	.error {
		display: flex;
		gap: var(--mw-space-2);
		padding: var(--mw-space-3) var(--mw-space-4);
		border-radius: var(--mw-radius-xl);
		background: var(--mw-danger-soft);
		color: var(--mw-ink-secondary);
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
	}
	.error > :global(.mw-icon) {
		margin-top: 1px;
		color: var(--mw-danger);
	}
	.retry {
		display: flex;
		align-items: center;
		min-height: var(--mw-touch-target);
		color: var(--mw-accent);
		font-weight: 700;
	}
</style>
