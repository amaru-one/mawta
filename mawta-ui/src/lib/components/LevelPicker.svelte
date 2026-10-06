<script lang="ts">
	import type { Tier } from '$lib/grades';
	import LevelSelector from './LevelSelector.svelte';
	let {
		level,
		disabled = false,
		onselect,
	}: {
		level: Tier | null;
		disabled?: boolean;
		size?: number;
		onselect: (level: Tier) => void;
	} = $props();
</script>

<LevelSelector {level} {disabled} {onselect} />
