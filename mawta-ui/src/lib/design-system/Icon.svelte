<script lang="ts">
	import { glyphs, type IconName } from './icons';
	let { name, size = 16 }: { name: IconName; size?: number } = $props();
</script>

<svg
	class="mw-icon"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
	focusable="false">{@html glyphs[name]}</svg
>
