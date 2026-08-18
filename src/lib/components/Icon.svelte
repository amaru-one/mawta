<script lang="ts">
	import type { IconName } from '$lib/icons';

	interface Props {
		name: IconName;
		size?: number;
	}

	let { name, size = 16 }: Props = $props();
</script>

<svg class="ic" style="font-size:{size}px" aria-hidden="true">
	<use href="#i-{name}" />
</svg>
