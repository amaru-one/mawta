<script lang="ts">
	import type { ContentProps } from './types';
	let { children, class: className = '' }: ContentProps = $props();
</script>

<div class="mw-btn-row {className}">{@render children()}</div>
