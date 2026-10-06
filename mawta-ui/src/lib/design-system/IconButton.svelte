<script lang="ts">
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import type { IconName } from './icons';
	import Icon from './Icon.svelte';
	interface Props extends Omit<HTMLButtonAttributes, 'children'> {
		icon: IconName;
		label: string;
		outlined?: boolean;
	}
	let {
		icon,
		label,
		outlined = false,
		type = 'button',
		class: className = '',
		...rest
	}: Props = $props();
</script>

<button
	{...rest}
	{type}
	aria-label={label}
	class="mw-icon-button {outlined ? 'mw-icon-button--outlined' : ''} {className}"
	><Icon name={icon} size={20} /></button
>
