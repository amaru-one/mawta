<script lang="ts">
	// One criterio de evaluación and the row of evidence behind it — the
	// evidencia × criterio grid, read one criterio at a time.
	//
	// Deliberately read-only. Until 2026-08-28 this component carried a
	// LevelPicker, which let a teacher put AD/A/B/C on the criterio itself with
	// no evidence in hand. That inverts RVM 094-2020 5.1.1.3 p.3: the norm
	// values *evidence*, and the criterio is the ruler it is valued against.
	// Levels are now recorded inside each piece of evidence, and this row is
	// where they add up to something readable.
	//
	// What the teacher does here is read left to right. C → B → A → A is a
	// student who learned to justify their procedure; no single value can say
	// that, which is the whole reason the grain changed.
	import type { CriterionDto } from '$lib/api/dto';
	import { list } from '$lib/api/client';
	import LevelBadge from './LevelBadge.svelte';

	interface Props {
		criterion: CriterionDto;
		/** Called when a cell is tapped, so the caller can open that evidencia.
		 *  Omitted, the cells are inert. */
		onopenevidence?: (assessmentId: string) => void;
	}

	let { criterion, onopenevidence }: Props = $props();

	const cells = $derived(list(criterion.evidence));

	const dateFmt = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'short' });

	function when(dueAt: string | null): string {
		if (dueAt === null) return 'sin fecha';
		return dateFmt.format(new Date(dueAt));
	}
</script>

<div class="criterion">
	<p class="text">{criterion.code ? `${criterion.code} · ` : ''}{criterion.description}</p>

	{#if cells.length > 0}
		<!-- Scrolls inside itself: a busy period can produce more evidence than
		     fits, and the page must never scroll sideways. -->
		<div class="track">
			{#each cells as cell (cell.assessment_id)}
				<button
					type="button"
					class="cell"
					class:tappable={onopenevidence !== undefined}
					disabled={onopenevidence === undefined}
					onclick={() => onopenevidence?.(cell.assessment_id)}
					title={`${cell.title} · ${when(cell.due_at)}`}
				>
					<LevelBadge tier={cell.level} size={24} />
					<span class="when">{when(cell.due_at)}</span>
					<span class="what">{cell.title}</span>
				</button>
			{/each}
		</div>
	{:else}
		<p class="empty">Sin evidencia valorada contra este criterio.</p>
	{/if}

	{#if criterion.period_level !== null}
		<!-- History. The app used to let a criterio be graded on its own; those
		     rows are part of a student's record, so they are shown and labelled
		     rather than hidden or quietly deleted. -->
		<p class="legacy">
			<LevelBadge tier={criterion.period_level} size={20} />
			<span>Juicio del periodo (registro anterior, ya no editable)</span>
		</p>
	{/if}
</div>

<style>
	.criterion {
		padding: var(--space-sm) 0;
		border-top: 0.5px solid var(--border-subtle, var(--border-strong));
	}

	.text {
		margin: 0 0 8px;
		font-size: 13px;
		line-height: 1.35;
		color: var(--text-primary);
	}

	.track {
		display: flex;
		gap: var(--space-sm);
		overflow-x: auto;
		padding-bottom: 2px;
	}

	.cell {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 3px;
		width: 76px;
		padding: 6px 4px;
		border: none;
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		text-align: center;
		font-family: inherit;
	}

	.cell.tappable {
		cursor: pointer;
	}

	.when {
		font-size: 10px;
		color: var(--text-muted);
	}

	/* Two lines of title, then it stops — the badge and the date are what the
	   row is read for; the title is only there to identify the piece of work. */
	.what {
		font-size: 11px;
		line-height: 1.2;
		color: var(--text-secondary);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.empty,
	.legacy {
		margin: 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	.legacy {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-top: var(--space-sm);
	}
</style>
