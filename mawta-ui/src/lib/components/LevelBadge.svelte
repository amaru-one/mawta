<script lang="ts">
	import type { Tier } from '$lib/levels';
	// tier null = not judged yet: the same pill, outlined, with "Sin nivel".
	let { tier }: { tier: Tier | null } = $props();
	const names = { AD: 'Destacado', A: 'Esperado', B: 'En proceso', C: 'En inicio' };
</script>

<!-- A fixed pill, the same footprint in both states, so a level reads as a tag
	 and never shifts the row. -->
{#if tier === null}
	<span class="level level--unset" aria-label="Sin nivel">Sin nivel</span>
{:else}
	<span class="level" aria-label="{tier} · {names[tier]}" title={names[tier]}>{tier}</span>
{/if}

<style>
	.level {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 60px;
		height: 28px;
		box-sizing: border-box;
		border-radius: var(--mw-radius-md);
		background: var(--mw-surface-tint);
		color: var(--mw-ink);
		font-size: 16px;
		font-weight: 700;
		line-height: 1;
	}

	.level--unset {
		padding: 0 4px;
		border: 1px dashed var(--mw-line-control);
		background: none;
		color: var(--mw-ink-secondary);
		font-size: var(--mw-type-caption-size);
		font-weight: 600;
		white-space: nowrap;
	}
</style>
