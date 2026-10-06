<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { ActionVariant } from './types';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	interface Props {
		children: Snippet;
		variant?: ActionVariant;
		icon?: IconName;
		href?: string;
		target?: string;
		rel?: string;
		disabled?: boolean;
		loading?: boolean;
		type?: 'button' | 'submit' | 'reset';
		onclick?: (event: MouseEvent) => void;
		class?: string;
		'aria-label'?: string;
		'aria-describedby'?: string;
	}
	let {
		children,
		variant = 'neutral',
		icon,
		href,
		target,
		rel,
		disabled = false,
		loading = false,
		type = 'button',
		onclick,
		class: className = '',
		...rest
	}: Props = $props();
	const classes = $derived(`mw-action mw-action--${variant} ${className}`);
</script>

{#snippet content()}{#if loading}<span class="mw-spinner" aria-hidden="true"
		></span>{:else if icon}<Icon name={icon} />{/if}{@render children()}{/snippet}
{#if href !== undefined}
	<a
		{...rest}
		href={disabled || loading ? undefined : href}
		role={disabled || loading ? 'link' : undefined}
		aria-disabled={disabled || loading || undefined}
		aria-busy={loading || undefined}
		tabindex={disabled || loading ? -1 : undefined}
		{target}
		{rel}
		onclick={(event) => {
			if (disabled || loading) event.preventDefault();
			else onclick?.(event);
		}}
		class={classes}>{@render content()}</a
	>
{:else}
	<button
		{...rest}
		{type}
		disabled={disabled || loading}
		aria-busy={loading || undefined}
		{onclick}
		class={classes}>{@render content()}</button
	>
{/if}
