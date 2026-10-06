<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	let {
		title,
		description,
		icon,
		actions,
	}: { title: string; description?: string; icon?: IconName; actions?: Snippet } = $props();
</script>

<div class="mw-empty">
	{#if icon}<Icon name={icon} size={20} />{/if}
	<p class="mw-text mw-text--heading">{title}</p>
	{#if description}<p class="mw-meta">{description}</p>{/if}{#if actions}<div
			class="mw-empty__actions"
		>
			{@render actions()}
		</div>{/if}
</div>
