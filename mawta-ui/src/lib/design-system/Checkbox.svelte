<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import Icon from './Icon.svelte';
	interface Props extends Omit<HTMLInputAttributes, 'type' | 'children' | 'size'> {
		label: string;
		description?: string;
	}
	let {
		label,
		description,
		checked = $bindable(false),
		class: className = '',
		...rest
	}: Props = $props();
</script>

<label class="mw-check {checked ? 'mw-check--checked' : ''} {className}">
	<input {...rest} type="checkbox" bind:checked class="mw-check__native" />
	<span class="mw-check__box" aria-hidden="true"
		>{#if checked}<Icon name="check" size={14} />{/if}</span
	>
	<span class="mw-check__text"
		>{label}{#if description}<span class="mw-check__description">{description}</span>{/if}</span
	>
</label>
