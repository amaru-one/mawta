<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type { CompetencyCriteriaDto } from '$lib/api/dto';
	import { createCriterion, deleteCriterion, getClassCriteria } from '$lib/api/endpoints/criteria';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let competencies = $state<CompetencyCriteriaDto[]>([]);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			competencies = list((await getClassCriteria(courseId)).competencies);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	async function reload(): Promise<void> {
		try {
			competencies = list((await getClassCriteria(courseId)).competencies);
		} catch {
			// keep showing the last good data
		}
	}

	onMount(load);

	// Which competencia is currently taking a new criterio, and the text so far.
	let composingFor = $state<string | null>(null);
	let draft = $state('');
	let saving = $state(false);
	let deletingId = $state<string | null>(null);

	const withoutCriteria = $derived(
		competencies.filter((c) => list(c.criteria).length === 0).length
	);

	function startComposing(competencyId: string): void {
		hapticTap();
		composingFor = competencyId;
		draft = '';
	}

	async function save(competencyId: string): Promise<void> {
		if (saving || draft.trim() === '') return;
		saving = true;
		try {
			await createCriterion(courseId, competencyId, { description: draft.trim() });
			showToast('Criterio guardado');
			composingFor = null;
			draft = '';
			await reload();
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar');
		} finally {
			saving = false;
		}
	}

	async function remove(criterionId: string): Promise<void> {
		deletingId = null;
		try {
			await deleteCriterion(criterionId);
			showToast('Criterio eliminado');
			await reload();
		} catch {
			showToast('No se pudo eliminar');
		}
	}
</script>

<svelte:head>
	<title>Criterios de evaluación</title>
</svelte:head>

<TopBar back={`/class/${courseId}`} useHistory />

<div class="body">
	{#if ready}
		<p class="title">Criterios de evaluación</p>
		<p class="subtitle">{courseName}</p>

		<p class="intro">
			Cada competencia se valora contra los criterios que tú defines. Son la
			referencia para tu juicio docente sobre la evidencia del periodo
			(RVM 094-2020); no se promedian ni se convierten en nota.
		</p>

		{#if withoutCriteria > 0}
			<div class="row notice">
				<Icon name="alert" size={16} />
				<p class="grow notice-text">
					{withoutCriteria === 1
						? '1 competencia todavía no tiene criterios'
						: `${withoutCriteria} competencias todavía no tienen criterios`}
				</p>
			</div>
		{/if}

		<div class="stack">
			{#each competencies as comp (comp.competency_id)}
				{@const criteria = list(comp.criteria)}
				<div class="card comp">
					<p class="comp-name">{comp.name}</p>
					{#if comp.kind === 'transversal'}
						<p class="comp-kind">Competencia transversal</p>
					{/if}

					{#if criteria.length === 0}
						<p class="empty">Sin criterios definidos.</p>
					{:else}
						{#each criteria as c (c.criterion_id)}
							<div class="row criterion">
								<p class="grow criterion-text">{c.description}</p>
								<button
									class="action pressable"
									onclick={() => (deletingId = c.criterion_id)}
									aria-label="Eliminar criterio"
									title="Eliminar"
								>
									<Icon name="trash" size={15} />
								</button>
							</div>
						{/each}
					{/if}

					{#if composingFor === comp.competency_id}
						<textarea
							class="draft"
							bind:value={draft}
							rows="3"
							placeholder="Ej.: Traduce un problema verbal con dos incógnitas a un sistema de ecuaciones."
							disabled={saving}
						></textarea>
						<div class="row actions">
							<button
								class="btn-light"
								onclick={() => {
									composingFor = null;
									draft = '';
								}}
								disabled={saving}
							>
								Cancelar
							</button>
							<button
								class="btn-dark"
								onclick={() => void save(comp.competency_id)}
								disabled={saving || draft.trim() === ''}
							>
								Guardar
							</button>
						</div>
					{:else}
						<button class="add pressable" onclick={() => startComposing(comp.competency_id)}>
							+ Agregar criterio
						</button>
					{/if}
				</div>
			{/each}
		</div>
	{:else if loadError}
		<p class="empty">No se pudieron cargar los criterios.</p>
	{/if}
</div>

{#if deletingId !== null}
	<ConfirmDialog
		title="¿Eliminar este criterio?"
		text="Los niveles ya registrados contra él se conservan como parte del historial."
		confirmLabel="Eliminar"
		onconfirm={() => void remove(deletingId ?? '')}
		oncancel={() => (deletingId = null)}
	/>
{/if}

<style>
	.title {
		margin: 0;
		font-size: 20px;
		font-weight: 500;
	}

	.subtitle {
		margin: 2px 0 var(--space-md);
		font-size: 13px;
		color: var(--text-secondary);
	}

	.intro {
		margin: 0 0 var(--space-md);
		font-size: 12px;
		line-height: 1.45;
		color: var(--text-muted);
	}

	.notice {
		gap: var(--space-sm);
		align-items: flex-start;
		background: var(--bg-danger);
		border-radius: var(--radius);
		padding: var(--space-sm) var(--space-md);
		margin-bottom: var(--space-md);
		color: var(--text-danger);
	}

	.notice-text {
		margin: 0;
		font-size: 13px;
		color: var(--text-primary);
	}

	.comp {
		padding: var(--space-md);
	}

	.comp-name {
		margin: 0;
		font-size: 14px;
		line-height: 1.35;
	}

	.comp-kind {
		margin: 2px 0 0;
		font-size: 11px;
		color: var(--text-muted);
	}

	.criterion {
		gap: var(--space-sm);
		align-items: flex-start;
		padding: var(--space-sm) 0;
		border-top: 0.5px solid var(--border-strong);
		margin-top: var(--space-sm);
	}

	.criterion-text {
		margin: 0;
		font-size: 13px;
		line-height: 1.35;
	}

	.action {
		border: none;
		background: none;
		padding: 2px;
		color: var(--text-muted);
		cursor: pointer;
		flex-shrink: 0;
	}

	.empty {
		margin: var(--space-sm) 0 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	.draft {
		width: 100%;
		margin-top: var(--space-sm);
		padding: 10px 12px;
		border-radius: var(--radius);
		border: 0.5px solid var(--border-strong);
		font-family: inherit;
		font-size: 13px;
		color: var(--text-primary);
		resize: none;
		box-sizing: border-box;
	}

	.actions {
		gap: var(--space-sm);
		margin-top: var(--space-sm);
	}

	.add {
		margin-top: var(--space-sm);
		border: none;
		background: none;
		padding: 0;
		font-family: inherit;
		font-size: 13px;
		color: var(--text-secondary);
		cursor: pointer;
	}
</style>
