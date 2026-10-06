<script lang="ts">
	import type { Tier } from '$lib/grades';
	let { tier, size = 22 }: { tier: Tier; size?: number } = $props();
	const names = { AD: 'Destacado', A: 'Esperado', B: 'En proceso', C: 'En inicio' };
</script>

<span
	class="level"
	style:font-size="{Math.max(13, Math.min(17, size / 2))}px"
	aria-label="{tier} · {names[tier]}"
	title={names[tier]}>{tier}</span
>

<style>
	.level {
		display: inline-block;
		min-width: 24px;
		text-align: center;
		flex-shrink: 0;
		color: var(--mw-ink);
		font-weight: 700;
		line-height: var(--mw-type-heading-line);
	}
</style>
