<script lang="ts">
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	interface Props extends Omit<HTMLButtonAttributes, 'children' | 'onclick'> {
		href?: string;
		target?: string;
		rel?: string;
		onclick?: (event: MouseEvent) => void;
		icon: IconName;
		label: string;
		outlined?: boolean;
	}
	let {
		icon,
		label,
		outlined = false,
		disabled = false,
		href,
		type = 'button',
		class: className = '',
		...rest
	}: Props = $props();
</script>

{#if href !== undefined}
	<a
		href={disabled ? undefined : href}
		role={disabled ? 'link' : undefined}
		aria-disabled={disabled || undefined}
		tabindex={disabled ? -1 : undefined}
		{...rest as HTMLAnchorAttributes}
		onclick={(event) => {
			if (disabled) event.preventDefault();
			else rest.onclick?.(event);
		}}
		aria-label={label}
		class="mw-icon-button {outlined ? 'mw-icon-button--outlined' : ''} {className}"
		><Icon name={icon} size={20} /></a
	>
{:else}
	<button
		{...rest}
		{type}
		{disabled}
		aria-label={label}
		class="mw-icon-button {outlined ? 'mw-icon-button--outlined' : ''} {className}"
		><Icon name={icon} size={20} /></button
	>
{/if}
