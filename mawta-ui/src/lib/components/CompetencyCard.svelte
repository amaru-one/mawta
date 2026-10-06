<script lang="ts">
	import { Action, Button, Checkbox, Disclosure, Field, Icon } from '$lib/design-system';
	import { untrack } from 'svelte';
	import type { CompetencyLevel } from '$lib/types';
	import type { CriterionDto } from '$lib/api/dto';
	import type { Tier } from '$lib/grades';
	import LevelBadge from './LevelBadge.svelte';
	import LevelPicker from './LevelPicker.svelte';

	interface Props {
		competency: CompetencyLevel;

		criteria?: CriterionDto[];
		onLevelChange: (competencyId: string, level: Tier) => Promise<void>;
		onSaveConclusion: (
			competencyId: string,
			body: string,
			includesRecommendations: boolean,
			status: 'draft' | 'final'
		) => Promise<void>;
	}

	let { competency, criteria = [], onLevelChange, onSaveConclusion }: Props = $props();

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
		optional: 'Conclusión descriptiva (opcional)',
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
			await onSaveConclusion(
				competency.competencyId,
				bodyDraft.trim(),
				includesRecommendations,
				status
			);
		} finally {
			saving = false;
		}
	}

	const showConclusion = $derived(competency.conclusionRequired || showConclusionForm);
</script>

<div class="view">
	<Disclosure bind:open={expanded}>
		{#snippet summary()}<span class="summary">
				<div class="grow">
					<p class="name">{competency.name}</p>
					{#if competency.level === null}
						<p class="sub">No desarrollada este periodo</p>
					{/if}
				</div>
				<div class="trailing">
					{#if competency.conclusionRequired && competency.conclusionStatus !== 'final'}
						<span class="required-text">Conclusión pendiente</span>
					{/if}
					{#if competency.level !== null}
						<LevelBadge tier={competency.level} size={28} />
					{:else}
						<span class="dash">Sin nivel</span>
					{/if}
				</div>
			</span>{/snippet}
		{#if expanded}
			<div class="body">
				<p class="eyebrow section">Criterios de evaluación</p>
				{#if criteria.length === 0}
					<p class="empty">
						Aún no has definido criterios para esta competencia. Sin criterios no hay referencia
						contra la cual valorar la evidencia.
					</p>
				{:else}
					<!-- Read-only, and deliberately so: a criterio says what to look at in
				     a piece of work, it is not itself graded (RVM 094-2020, 5.1.1.3
				     p.3). Putting a picker back on this row would have the teacher
				     marking the ruler instead of the work. -->
					<ul class="crits">
						{#each criteria as c (c.criterion_id)}
							<li class="crit">
								{#if c.code}<span class="crit-code">{c.code}</span> ·
								{/if}{c.description}
							</li>
						{/each}
					</ul>
				{/if}

				<p class="eyebrow section">Nivel de logro</p>
				<LevelPicker level={competency.level} disabled={saving} onselect={selectLevel} />
				<p class="official">
					Tu juicio sobre la evidencia del periodo, leída contra estos criterios. No se calcula ni
					se promedia a partir de ellos ni de las notas.
				</p>

				{#if showConclusion}
					<div class="conclusion">
						<Field
							kind="textarea"
							label={REQUIREMENT_LABEL[competency.conclusionRequirement]}
							bind:value={bodyDraft}
							rows={3}
							placeholder="Avances, dificultades y recomendaciones..."
							disabled={saving}
						/>
						<Checkbox bind:checked={includesRecommendations} disabled={saving}>
							<span>Incluye recomendaciones personalizadas</span>
						</Checkbox>
						<div class="actions row">
							<Button
								variant="secondary"
								type="button"
								onclick={() => void saveConclusion('draft')}
								disabled={saving || bodyDraft.trim() === ''}
							>
								Guardar borrador
							</Button>
							<Action
								variant="main"
								type="button"
								onclick={() => void saveConclusion('final')}
								disabled={saving || bodyDraft.trim() === '' || !includesRecommendations}
							>
								Guardar final
							</Action>
						</div>
					</div>
				{:else}
					<Action variant="link" type="button" onclick={() => (showConclusionForm = true)}>
						+ Agregar conclusión
					</Action>
				{/if}
			</div>
		{/if}
	</Disclosure>
</div>

<style>
	.summary {
		display: flex;
		align-items: center;
		gap: var(--mw-space-3);
	}
	.required-text {
		font-size: var(--mw-type-label-size);
		color: var(--mw-attention);
	}

	.section {
		margin: var(--mw-space-3) 0 var(--mw-space-1);
	}

	.section:first-child {
		margin-top: 0;
	}

	.empty {
		margin: 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
	}

	.crits {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.crit {
		padding: var(--mw-space-2) 0;
		border-top: 1px solid var(--mw-line);
		font-size: var(--mw-type-small-size);
		line-height: 1.35;
		color: var(--mw-ink);
		text-wrap: pretty;
	}

	.crit:first-child {
		border-top: none;
	}

	.crit-code {
		font-weight: 600;
		color: var(--mw-ink-secondary);
	}

	.official {
		margin: 8px 0 0;
		font-size: var(--mw-type-label-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.name {
		margin: 0;
		font-size: var(--mw-type-body-size);
	}

	.sub {
		margin: 2px 0 0;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
	}

	.trailing {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
		margin-top: 2px;
	}

	.dash {
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
		flex-shrink: 0;
	}

	.body {
		padding: 0 14px var(--mw-space-3);
	}

	.conclusion {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-2);
		margin-top: var(--mw-space-3);
	}

	.view :global(.conclusion-body) {
		width: 100%;
	}

	.actions {
		gap: var(--mw-space-2);
	}

	.view :global(.add-conclusion) {
		width: 100%;
	}
</style>
