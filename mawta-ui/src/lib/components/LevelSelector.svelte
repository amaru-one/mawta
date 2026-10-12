<script lang="ts">
	import type { Tier } from '$lib/levels';
	import { hapticTap } from '$lib/haptics';
	let {
		level,
		disabled = false,
		variant = 'official',
		onselect,
	}: {
		level: Tier | null;
		disabled?: boolean;
		variant?: 'official' | 'evidence';
		onselect: (level: Tier) => void;
	} = $props();
	const uid = $props.id();
	const legend = $derived(variant === 'evidence' ? 'Valoración de la evidencia' : 'Nivel de logro');
	const tiers: { value: Tier; label: string }[] = [
		{ value: 'AD', label: 'Destacado' },
		{ value: 'A', label: 'Esperado' },
		{ value: 'B', label: 'En proceso' },
		{ value: 'C', label: 'En inicio' },
	];
	function pick(value: Tier) {
		if (!disabled) {
			hapticTap();
			onselect(value);
		}
	}
</script>

<fieldset class="levels {variant}" {disabled}>
	<legend>{legend}</legend>
	<div class="options">
		{#each tiers as tier (tier.value)}<label class:chosen={level === tier.value}>
				<input
					type="radio"
					name={uid}
					aria-label="{tier.value} · {tier.label}"
					value={tier.value}
					checked={level === tier.value}
					onchange={() => pick(tier.value)}
				/>
				<span class="code">{tier.value}</span><span class="name">{tier.label}</span>
			</label>{/each}
	</div>
	{#if level === null}<p class="unset">Sin valorar</p>{/if}
</fieldset>

<style>
	.levels {
		border: 0;
		padding: 0;
		margin: 0;
		min-width: 0;
	}
	legend {
		padding: 0;
		margin-bottom: var(--mw-space-2);
		font-size: var(--mw-type-small-size);
		font-weight: 600;
	}
	.options {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: var(--mw-space-1);
	}
	label {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--mw-space-1);
		padding: var(--mw-space-2) var(--mw-space-1);
		min-height: 64px;
		cursor: pointer;
		border: 1px solid var(--mw-line-control);
		border-radius: var(--mw-radius-md);
	}
	input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	label:has(input:focus-visible) {
		outline: 2px solid var(--mw-focus-ring);
		outline-offset: 2px;
	}
	.code {
		font-size: var(--mw-type-heading-size);
		font-weight: 700;
	}
	.name {
		font-size: var(--mw-type-label-size);
		line-height: var(--mw-type-label-line);
		text-align: center;
	}
	.official .chosen {
		background: var(--mw-accent);
		border-color: var(--mw-accent);
		color: var(--mw-on-accent);
	}

	.evidence label {
		border: 0;
		border-bottom: 2px solid var(--mw-line-control);
		border-radius: 0;
	}
	.evidence .chosen {
		border-color: var(--mw-accent);
		color: var(--mw-accent);
		background: var(--mw-surface-tint);
	}

	.unset {
		margin: var(--mw-space-2) 0 0;
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}
	fieldset:disabled {
		opacity: 0.55;
	}
	fieldset:disabled label {
		cursor: not-allowed;
	}
</style>
