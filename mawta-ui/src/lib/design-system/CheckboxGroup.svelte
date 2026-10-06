<script lang="ts">
	import type { CheckOption } from './types';
	import Checkbox from './Checkbox.svelte';
	const uid = $props.id();
	let {
		label,
		options,
		value = $bindable([]),
		disabled = false,
		name,
		help,
		error,
		onchange,
	}: {
		label: string;
		options: CheckOption[];
		value?: string[];
		disabled?: boolean;
		name?: string;
		help?: string;
		error?: string;
		onchange?: (value: string[]) => void;
	} = $props();
	function toggle(option: string, checked: boolean) {
		value = checked ? [...value, option] : value.filter((item) => item !== option);
		onchange?.(value);
	}
</script>

<fieldset
	class="mw-field mw-check-group"
	{disabled}
	aria-describedby={help || error ? `${uid}-help` : undefined}
>
	<legend class="mw-field__label">{label}</legend>
	<div class="mw-checks">
		{#each options as option (option.value)}<Checkbox
				aria-invalid={error ? true : undefined}
				label={option.label}
				description={option.description}
				{name}
				value={option.value}
				checked={value.includes(option.value)}
				disabled={disabled || option.disabled}
				onchange={(event) => toggle(option.value, event.currentTarget.checked)}
			/>{/each}
	</div>
	{#if help || error}<p id="{uid}-help" class={error ? 'mw-field__error' : 'mw-field__help'}>
			{error || help}
		</p>{/if}
</fieldset>
