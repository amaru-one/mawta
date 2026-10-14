<script lang="ts">
	import type { Tier } from '$lib/levels';
	let { tier }: { tier: Tier } = $props();
	const names = { AD: 'Destacado', A: 'Esperado', B: 'En proceso', C: 'En inicio' };
</script>

<!-- A fixed pill: the same footprint as the "Sin nivel" pill in the list, so a
	 level reads as a tag and never shifts the row. -->
<span class="level" aria-label="{tier} · {names[tier]}" title={names[tier]}>{tier}</span>

<style>
	.level {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 60px;
		height: 28px;
		border-radius: var(--mw-radius-md);
		background: var(--mw-surface-tint);
		color: var(--mw-ink);
		font-size: 16px;
		font-weight: 700;
		line-height: 1;
	}
</style>
