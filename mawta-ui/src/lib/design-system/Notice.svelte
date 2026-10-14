<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { NoticeVariant } from './types';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	let {
		children,
		action,
		variant = 'info',
		icon,
		live = false,
	}: {
		children: Snippet;
		action?: Snippet;
		variant?: NoticeVariant;
		icon?: IconName;
		live?: boolean;
	} = $props();
</script>

<div
	class="mw-notice mw-notice--{variant}"
	role={live ? (variant === 'danger' ? 'alert' : 'status') : undefined}
>
	<Icon name={icon ?? (variant === 'info' ? 'sparkles' : 'alert')} size={20} />
	<div>
		{@render children()}
		{#if action}<div class="mw-notice__action">{@render action()}</div>{/if}
	</div>
</div>
