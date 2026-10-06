<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
	import type { ButtonVariant } from './types';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	interface Props extends Omit<HTMLButtonAttributes, 'children' | 'onclick'> {
		href?: string;
		target?: string;
		rel?: string;
		onclick?: (event: MouseEvent) => void;
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
		href,
		type = 'button',
		class: className = '',
		...rest
	}: Props = $props();
</script>

{#if href !== undefined}
	<a
		href={disabled || loading ? undefined : href}
		role={disabled || loading ? 'link' : undefined}
		aria-disabled={disabled || loading || undefined}
		tabindex={disabled || loading ? -1 : undefined}
		{...rest as HTMLAnchorAttributes}
		onclick={(event) => {
			if (disabled || loading) event.preventDefault();
			else rest.onclick?.(event);
		}}
		aria-busy={loading || undefined}
		class="mw-btn mw-btn--{variant} {block ? 'mw-btn--block' : ''} {className}"
	>
		{#if loading}<span class="mw-spinner" aria-hidden="true"
			></span>{:else if icon && iconPosition === 'start'}<Icon name={icon} />{/if}
		{@render children()}
		{#if icon && iconPosition === 'end'}<Icon name={icon} />{/if}
	</a>
{:else}
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
{/if}
