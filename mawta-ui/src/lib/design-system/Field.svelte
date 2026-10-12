<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes, HTMLInputAttributes } from 'svelte/elements';
	import type { Option } from './types';
	interface Props extends Omit<
		HTMLAttributes<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
		'children'
	> {
		control?: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
		name?: string;
		form?: string;
		type?:
			| 'text'
			| 'email'
			| 'password'
			| 'search'
			| 'tel'
			| 'url'
			| 'number'
			| 'date'
			| 'time'
			| 'datetime-local'
			| 'month'
			| 'week';
		required?: boolean;
		disabled?: boolean;
		readonly?: boolean;
		placeholder?: string;
		autocomplete?: HTMLInputAttributes['autocomplete'];
		min?: string | number;
		max?: string | number;
		step?: string | number;
		minlength?: number;
		maxlength?: number;
		pattern?: string;
		children?: Snippet;
		label: string;
		value?: string | number | null;
		kind?: 'input' | 'textarea' | 'select';
		options?: Option[];
		help?: string;
		error?: string;
		large?: boolean;
		rows?: number;
		labelAction?: Snippet;
	}
	const uid = $props.id();
	let {
		children,
		control = $bindable(null),
		label,
		value = $bindable<string | number | null | undefined>(),
		kind = 'input',
		options = [],
		help,
		error,
		large = false,
		rows = 4,
		labelAction,
		type = 'text',
		id = uid,
		class: className = '',
		'aria-describedby': describedBy,
		...rest
	}: Props = $props();
	const description = $derived(
		[describedBy, help ? `${id}-help` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ') ||
			undefined
	);
</script>

<div class="mw-field {error ? 'mw-field--error' : ''} {className}">
	<div class="mw-field__head">
		<label class="mw-field__label" for={id}>{label}</label
		>{#if labelAction}{@render labelAction()}{/if}
	</div>
	{#if kind === 'textarea'}
		<textarea
			bind:this={control}
			{...rest}
			{id}
			{rows}
			bind:value
			aria-describedby={description}
			aria-invalid={error ? true : rest['aria-invalid']}
			class="mw-input {large ? 'mw-input--lg' : ''}"></textarea>
	{:else if kind === 'select'}
		<select
			bind:this={control}
			{...rest}
			{id}
			bind:value
			aria-describedby={description}
			aria-invalid={error ? true : rest['aria-invalid']}
			class="mw-input {large ? 'mw-input--lg' : ''}"
			>{#if children}{@render children()}{:else}{#each options as option (option.value)}<option
						value={option.value}
						disabled={option.disabled}>{option.label}</option
					>{/each}{/if}</select
		>
	{:else}
		<input
			bind:this={control}
			{...rest}
			{type}
			{id}
			bind:value
			aria-describedby={description}
			aria-invalid={error ? true : rest['aria-invalid']}
			class="mw-input {large ? 'mw-input--lg' : ''}"
		/>
	{/if}
	{#if help}<p id="{id}-help" class="mw-field__help">{help}</p>{/if}
	{#if error}<p id="{id}-error" class="mw-field__error" role="alert">{error}</p>{/if}
</div>
