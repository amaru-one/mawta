<script lang="ts">
	import type { Tier } from '$lib/grades';

	interface Props {
		tier: Tier;
		size?: number;
	}

	let { tier, size = 22 }: Props = $props();

	// AD carries the accent — it's the tier the assistant highlights.
	const FILL: Record<Tier, string> = {
		AD: 'var(--fill-accent)',
		A: 'var(--fill-success)',
		B: 'var(--fill-warning)',
		C: 'var(--fill-tier-c)',
	};

	const ON: Record<Tier, string> = {
		AD: 'var(--on-accent)',
		A: 'var(--on-success)',
		B: 'var(--on-warning)',
		C: 'var(--on-tier-c)',
	};
</script>

<span
	class="lvl"
	class:outlined={tier === 'C'}
	style="width:{size}px;height:{size}px;font-size:{Math.round(size * 0.5)}px;
	       background:{FILL[tier]};color:{ON[tier]}"
	title={tier}
>
	{tier}
</span>

<style>
	.outlined {
		border: 0.5px solid var(--border-strong);
	}
</style>
