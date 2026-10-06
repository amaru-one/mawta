<script lang="ts">
	import type { Option } from './types';
	let {
		label,
		options,
		value = $bindable(''),
		disabled = false,
		name,
		onchange,
	}: {
		label: string;
		options: Option[];
		value?: string;
		disabled?: boolean;
		name?: string;
		onchange?: (value: string) => void;
	} = $props();
	function select(next: string) {
		value = next;
		onchange?.(next);
	}
</script>

<div class="mw-seg" role="group" aria-label={label}>
	{#each options as option (option.value)}<button
			type="button"
			aria-pressed={value === option.value}
			disabled={disabled || option.disabled}
			onclick={() => select(option.value)}>{option.label}</button
		>{/each}
</div>
{#if name}<input type="hidden" {name} {value} {disabled} />{/if}
