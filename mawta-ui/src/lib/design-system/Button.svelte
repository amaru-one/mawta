<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import type { ButtonVariant } from './types';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	interface Props extends Omit<HTMLButtonAttributes, 'children'> {
		children: Snippet;
		variant?: ButtonVariant;
		block?: boolean;
		loading?: boolean;
		icon?: IconName;
		iconPosition?: 'start' | 'end';
	}
	let {
		children,
		variant = 'secondary',
		block = false,
		loading = false,
		icon,
		iconPosition = 'start',
		disabled = false,
		type = 'button',
		class: className = '',
		...rest
	}: Props = $props();
</script>

<button
	{...rest}
	{type}
	disabled={disabled || loading}
	aria-busy={loading || undefined}
	class="mw-btn mw-btn--{variant} {block ? 'mw-btn--block' : ''} {className}"
>
	{#if loading}<span class="mw-spinner" aria-hidden="true"
		></span>{:else if icon && iconPosition === 'start'}<Icon name={icon} />{/if}
	{@render children()}
	{#if icon && iconPosition === 'end'}<Icon name={icon} />{/if}
</button>
