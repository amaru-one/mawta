<script lang="ts">
	// The literal value of one piece of evidencia: AD · A · B · C as four large
	// letters, the chosen one underlined.
	//
	// It borrows the competency index's grammar on purpose. Both are LINE
	// controls; the boxed four-cell block is reserved for the competency level,
	// and that difference is what keeps "I valued this piece of work" from
	// reading as "I decided the official record". A letter on an evidence is not
	// a nivel de logro — two AD and one B are not an A.
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';

	interface Props {
		/** null = not valued yet. Nothing is underlined; never render it as C. */
		level: Tier | null;
		disabled?: boolean;
		onselect: (level: Tier) => void;
	}

	let { level, disabled = false, onselect }: Props = $props();

	// CNEB descending-quality order, as the norm itself lists them.
	const TIERS: Tier[] = ['AD', 'A', 'B', 'C'];

	function pick(t: Tier): void {
		if (disabled) return;
		hapticTap();
		onselect(t);
	}
</script>

<div class="scale" class:off={disabled} role="radiogroup" aria-label="Valoración de la evidencia">
	{#each TIERS as t (t)}
		<button
			type="button"
			class="opt pressable"
			class:on={level === t}
			role="radio"
			aria-checked={level === t}
			aria-label="Nivel {t}"
			{disabled}
			onclick={() => pick(t)}
		>
			{t}
		</button>
	{/each}
</div>

<style>
	.scale {
		display: flex;
		align-items: flex-end;
		border-bottom: 0.5px solid var(--border);
	}

	.scale.off {
		opacity: 0.3;
	}

	.opt {
		display: block;
		padding: 10px 14px 8px;
		border-bottom: 2px solid transparent;
		font-size: 24px;
		font-weight: 600;
		line-height: 1;
		color: var(--text-faint);
	}

	.opt.on {
		border-bottom-color: var(--aurora-deep);
		color: var(--aurora-deep);
	}

	.opt:disabled {
		cursor: default;
	}
</style>
