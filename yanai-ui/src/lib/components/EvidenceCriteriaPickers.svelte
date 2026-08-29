<script lang="ts">
	// The official half of one piece of evidencia: its criterios, each with a
	// level for this student. This is where a criterio level is actually
	// recorded — always naming the evidence it was read from, per RVM 094-2020
	// 5.1.1.3 p.3.
	//
	// It sits inside the evidence row, next to the mark, on purpose. That is
	// the "one capture, two readings" rule: the teacher opens the work once and
	// files both the school's number and the official judgement. What splits is
	// where each one goes, never the teacher's effort.
	import type { CriterionRefDto } from '$lib/api/dto';
	import type { Tier } from '$lib/grades';
	import LevelPicker from './LevelPicker.svelte';

	interface Props {
		criteria: CriterionRefDto[];
		onLevelChange: (criterionId: string, level: Tier) => Promise<void>;
	}

	let { criteria, onLevelChange }: Props = $props();

	// Per-criterio, not one flag for the block: saving one row must not freeze
	// the others, since a teacher taps down the list quickly.
	let saving = $state<Set<string>>(new Set());

	async function select(criterionId: string, level: Tier): Promise<void> {
		if (saving.has(criterionId)) return;
		saving = new Set(saving).add(criterionId);
		try {
			await onLevelChange(criterionId, level);
		} finally {
			const next = new Set(saving);
			next.delete(criterionId);
			saving = next;
		}
	}
</script>

<div class="block">
	<p class="eyebrow">Nivel por criterio</p>
	{#each criteria as c (c.criterion_id)}
		<div class="row">
			<p class="text">{c.code ? `${c.code} · ` : ''}{c.description}</p>
			<LevelPicker
				level={c.level}
				disabled={saving.has(c.criterion_id)}
				size={26}
				onselect={(level) => void select(c.criterion_id, level)}
			/>
		</div>
	{/each}
</div>

<style>
	.block {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-top: var(--space-sm);
		padding-top: var(--space-sm);
		border-top: 0.5px solid var(--border-subtle, var(--border-strong));
	}

	.eyebrow {
		margin: 0;
		font-size: 11px;
		font-weight: 500;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.row {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	/* Long criterio texts wrap freely — the app's standard overflow idiom, no
	   ellipsis. */
	.text {
		margin: 0;
		font-size: 12px;
		line-height: 1.35;
		color: var(--text-secondary);
	}
</style>
