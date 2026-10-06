<script lang="ts">
	import type { ContentProps } from './types';
	let { children, class: className = '' }: ContentProps = $props();
</script>

<div class="mw-context {className}">{@render children()}</div>
