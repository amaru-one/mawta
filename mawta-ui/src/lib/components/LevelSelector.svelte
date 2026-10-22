<script lang="ts">
	import { TIER_DEFINITIONS, TIER_NAMES, TIERS, type Tier } from '$lib/levels';
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
	// An evidence mark keeps the short words: it sits on every card and is not
	// the official record. The nivel de logro uses the CNEB's own names.
	const SHORT: Record<Tier, string> = {
		AD: 'Destacado',
		A: 'Esperado',
		B: 'En proceso',
		C: 'En inicio',
	};
	const tiers = $derived(
		TIERS.map((value) => ({
			value,
			label: variant === 'evidence' ? SHORT[value] : TIER_NAMES[value],
		}))
	);
	let scaleOpen = $state(false);
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

{#if variant === 'official'}
	<!-- Each level is defined against the expected level (CNEB): the chosen
	     one's definition is always in view, the whole scale one tap away. -->
	<div class="scale">
		{#if level !== null}
			<p class="def">
				<strong>{level} · {TIER_NAMES[level]}.</strong>
				{TIER_DEFINITIONS[level]}
			</p>
		{/if}
		<button
			type="button"
			class="scale-toggle"
			aria-expanded={scaleOpen}
			aria-controls="{uid}-scale"
			onclick={() => (scaleOpen = !scaleOpen)}
		>
			{scaleOpen ? 'Ocultar la escala' : 'Ver la escala completa'}
		</button>
		{#if scaleOpen}
			<div id="{uid}-scale" class="scale-list">
				{#each TIERS as value (value)}
					<p class="def small">
						<strong>{value} · {TIER_NAMES[value]}.</strong>
						{TIER_DEFINITIONS[value]}
					</p>
				{/each}
				<p class="source">Escala de calificación del Currículo Nacional (CNEB).</p>
			</div>
		{/if}
	</div>
{/if}

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
	.official label {
		min-height: 72px;
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

	.scale {
		margin-top: var(--mw-space-3);
		padding-top: var(--mw-space-3);
		border-top: 1px solid var(--mw-line);
	}
	.def {
		margin: 0;
		max-width: 68ch;
		font-size: var(--mw-type-small-size);
		line-height: 1.5;
		color: var(--mw-ink-secondary);
		text-wrap: pretty;
	}
	.def strong {
		color: var(--mw-ink);
	}
	.def.small {
		font-size: var(--mw-type-caption-size);
	}
	.scale-toggle {
		margin: var(--mw-space-1) 0 0;
		padding: var(--mw-space-2) 0;
		min-height: var(--mw-touch-target);
		border: 0;
		background: none;
		font: inherit;
		font-size: var(--mw-type-caption-size);
		font-weight: 700;
		color: var(--mw-ink);
		text-decoration: underline;
		cursor: pointer;
	}
	.scale-list {
		display: grid;
		gap: 10px;
	}
	.source {
		margin: 0;
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
		color: var(--mw-ink-muted);
	}
</style>
