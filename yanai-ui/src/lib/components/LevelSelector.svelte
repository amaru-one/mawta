<script lang="ts">
	// The nivel de logro of a competencia — the official record, and the only
	// control on the student's screen enclosed in a 1px stroke.
	//
	// That enclosure is the whole argument of the layout: everything above it
	// (the marks, the letters on each evidence) is a line control that INFORMS
	// this decision, and this is the decision. It carries the MINEDU label of each
	// level because the letter alone does not say what it means.
	//
	// Nothing computes it. There is no suggested level anywhere in the app.
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';

	interface Props {
		/** null = not evaluated this period (RVM 048-2024, 5.1.2.2) — a real
		 *  state, rendered as no selection and never as C. */
		level: Tier | null;
		disabled?: boolean;
		onselect: (level: Tier) => void;
	}

	let { level, disabled = false, onselect }: Props = $props();

	const TIERS: { tier: Tier; label: string }[] = [
		{ tier: 'AD', label: 'Destacado' },
		{ tier: 'A', label: 'Esperado' },
		{ tier: 'B', label: 'En proceso' },
		{ tier: 'C', label: 'En inicio' },
	];

	function pick(t: Tier): void {
		if (disabled) return;
		hapticTap();
		onselect(t);
	}
</script>

<div class="sel" role="radiogroup" aria-label="Nivel de logro">
	{#each TIERS as t (t.tier)}
		<button
			type="button"
			class="cell pressable"
			class:on={level === t.tier}
			role="radio"
			aria-checked={level === t.tier}
			aria-label="{t.tier} · {t.label}"
			{disabled}
			onclick={() => pick(t.tier)}
		>
			<span class="code">{t.tier}</span>
			<span class="name">{t.label}</span>
		</button>
	{/each}
</div>

<style>
	.sel {
		display: flex;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	.cell {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 3px;
		height: 62px;
		border-right: 1px solid var(--border-strong);
	}

	.cell:last-child {
		border-right: none;
	}

	.cell.on {
		background: var(--fill-primary);
		color: var(--on-primary);
	}

	.cell:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.code {
		font-size: 16px;
		font-weight: 600;
		line-height: 1;
	}

	.name {
		font-size: 10px;
		line-height: 1.2;
		color: var(--text-muted);
	}

	.cell.on .name {
		color: rgba(255, 255, 255, 0.7);
	}
</style>
