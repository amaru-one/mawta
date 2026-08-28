<script lang="ts">
	import { untrack } from 'svelte';
	import type { CompetencyLevel } from '$lib/types';
	import type { CriterionDto } from '$lib/api/dto';
	import type { Tier } from '$lib/grades';
	import Icon from './Icon.svelte';
	import LevelBadge from './LevelBadge.svelte';
	import LevelPicker from './LevelPicker.svelte';
	import CriterionRow from './CriterionRow.svelte';

	interface Props {
		competency: CompetencyLevel;
		/** The criterios the teacher wrote for this competencia, with the
		 *  student's level against each. The evidence the competency level is
		 *  judged from — never summed or averaged into it. */
		criteria?: CriterionDto[];
		onCriterionLevelChange?: (criterionId: string, level: Tier) => Promise<void>;
		onLevelChange: (competencyId: string, level: Tier) => Promise<void>;
		onSaveConclusion: (
			competencyId: string,
			body: string,
			includesRecommendations: boolean,
			status: 'draft' | 'final'
		) => Promise<void>;
	}

	let {
		competency,
		criteria = [],
		onCriterionLevelChange,
		onLevelChange,
		onSaveConclusion
	}: Props = $props();

	let expanded = $state(false);
	// Uncontrolled after first render on purpose: the parent only patches the
	// fields a save actually touched, so re-syncing this from the prop on
	// every update would blow away text the teacher is mid-typing. `untrack`
	// tells Svelte that capturing only the initial value here is deliberate.
	let bodyDraft = $state(untrack(() => competency.conclusionBody ?? ''));
	let includesRecommendations = $state(false);
	let showConclusionForm = $state(false);
	let saving = $state(false);

	const REQUIREMENT_LABEL: Record<CompetencyLevel['conclusionRequirement'], string> = {
		level_c: 'Conclusión descriptiva obligatoria (nivel C)',
		consecutive_c: 'Conclusión descriptiva obligatoria — sustenta por qué no hay avance',
		inclusion_support: 'Conclusión descriptiva obligatoria — incluye apoyos y ajustes',
		optional: 'Conclusión descriptiva (opcional)'
	};

	async function selectLevel(level: Tier): Promise<void> {
		if (saving) return;
		saving = true;
		try {
			await onLevelChange(competency.competencyId, level);
		} finally {
			saving = false;
		}
	}

	async function saveConclusion(status: 'draft' | 'final'): Promise<void> {
		if (saving || bodyDraft.trim() === '') return;
		if (status === 'final' && !includesRecommendations) return;
		saving = true;
		try {
			await onSaveConclusion(competency.competencyId, bodyDraft.trim(), includesRecommendations, status);
		} finally {
			saving = false;
		}
	}

	const showConclusion = $derived(competency.conclusionRequired || showConclusionForm);
</script>

<div class="card comp" class:expanded>
	<button
		type="button"
		class="header pressable"
		onclick={() => (expanded = !expanded)}
		aria-expanded={expanded}
	>
		<div class="grow">
			<p class="name">{competency.name}</p>
			{#if competency.level === null}
				<p class="sub">No desarrollada este periodo</p>
			{/if}
		</div>
		<div class="trailing">
			{#if competency.conclusionRequired && competency.conclusionStatus !== 'final'}
				<span class="warn-dot" title="Conclusión descriptiva obligatoria"></span>
			{/if}
			{#if competency.level !== null}
				<LevelBadge tier={competency.level} size={28} />
			{:else}
				<span class="dash">—</span>
			{/if}
			<span class="chevron" class:open={expanded}>
				<Icon name="chevron-right" size={16} />
			</span>
		</div>
	</button>

	{#if expanded}
		<div class="body">
			<p class="eyebrow section">Criterios de evaluación</p>
			{#if criteria.length === 0}
				<p class="empty">
					Aún no has definido criterios para esta competencia. Sin criterios no hay
					referencia contra la cual valorar la evidencia.
				</p>
			{:else}
				{#each criteria as c (c.criterion_id)}
					<CriterionRow
						criterion={c}
						onLevelChange={onCriterionLevelChange ?? (async () => {})}
					/>
				{/each}
			{/if}

			<p class="eyebrow section">Nivel de logro</p>
			<LevelPicker level={competency.level} disabled={saving} onselect={selectLevel} />
			<p class="official">
				Tu juicio sobre la evidencia del periodo. No se calcula a partir de los
				criterios ni de las notas.
			</p>

			{#if showConclusion}
				<div class="conclusion">
					<p class="conclusion-label" class:required={competency.conclusionRequired}>
						{REQUIREMENT_LABEL[competency.conclusionRequirement]}
					</p>
					<textarea
						class="conclusion-body"
						bind:value={bodyDraft}
						rows="3"
						placeholder="Avances, dificultades y recomendaciones..."
						disabled={saving}
					></textarea>
					<label class="check row">
						<input type="checkbox" bind:checked={includesRecommendations} disabled={saving} />
						<span>Incluye recomendaciones personalizadas</span>
					</label>
					<div class="actions row">
						<button
							type="button"
							class="btn-light"
							onclick={() => void saveConclusion('draft')}
							disabled={saving || bodyDraft.trim() === ''}
						>
							Guardar borrador
						</button>
						<button
							type="button"
							class="btn-dark"
							onclick={() => void saveConclusion('final')}
							disabled={saving || bodyDraft.trim() === '' || !includesRecommendations}
						>
							Guardar final
						</button>
					</div>
				</div>
			{:else}
				<button type="button" class="add-conclusion pressable" onclick={() => (showConclusionForm = true)}>
					+ Agregar conclusión
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.section {
		margin: var(--space-md) 0 var(--space-xs);
	}

	.section:first-child {
		margin-top: 0;
	}

	.empty {
		margin: 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-muted);
	}

	.official {
		margin: 8px 0 0;
		font-size: 11px;
		line-height: 1.4;
		color: var(--text-muted);
	}

	.comp {
		padding: 0;
		overflow: hidden;
	}

	.header {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		width: 100%;
		padding: var(--space-md) 14px;
		background: transparent;
		border: none;
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.name {
		margin: 0;
		font-size: 14px;
	}

	.sub {
		margin: 2px 0 0;
		font-size: 11px;
		color: var(--text-muted);
	}

	.trailing {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
		margin-top: 2px;
	}

	.warn-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--fill-danger);
		flex-shrink: 0;
	}

	.dash {
		font-size: 12px;
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.chevron {
		display: inline-flex;
		flex-shrink: 0;
		color: var(--text-muted);
		transition: transform 150ms;
	}

	.chevron.open {
		transform: rotate(90deg);
	}

	.body {
		padding: 0 14px var(--space-md);
	}

	.conclusion {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-top: var(--space-md);
	}

	.conclusion-label {
		margin: 0;
		font-size: 11px;
		color: var(--text-secondary);
	}

	.conclusion-label.required {
		color: var(--text-danger);
	}

	.conclusion-body {
		font-size: 13px;
		color: var(--text-primary);
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: var(--space-sm) 10px;
		font-family: inherit;
		resize: vertical;
		width: 100%;
		box-sizing: border-box;
	}

	.conclusion-body:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.check {
		gap: var(--space-sm);
		font-size: 12px;
		color: var(--text-secondary);
	}

	.actions {
		gap: var(--space-sm);
	}

	.actions button {
		flex: 1;
		min-width: 0;
		padding: 10px;
		border-radius: var(--radius-sm);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
	}

	.btn-light {
		background: var(--surface-2);
		color: var(--text-primary);
		border: 0.5px solid var(--border-strong);
	}

	.btn-dark {
		background: var(--fill-primary);
		color: var(--on-primary);
		border: none;
	}

	.actions button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.add-conclusion {
		width: 100%;
		padding: var(--space-sm);
		background: transparent;
		border: 0.5px dashed var(--border-strong);
		border-radius: var(--radius-sm);
		font-size: 12px;
		color: var(--text-secondary);
		cursor: pointer;
		font-family: inherit;
	}
</style>
