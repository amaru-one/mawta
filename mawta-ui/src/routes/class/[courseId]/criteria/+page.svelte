<script lang="ts">
	import {
		Action,
		Button,
		Card,
		EmptyState,
		Field,
		Icon,
		IconButton,
		LoadingState,
		Notice,
	} from '$lib/design-system';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type { CompetencyCriteriaDto } from '$lib/api/dto';
	import { createCriterion, deleteCriterion, getClassCriteria } from '$lib/api/endpoints/criteria';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
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
<div class="view">
	<TopBar back={`/class/${courseId}`} useHistory />

	<div class="body">
		{#if ready}
			<p class="title">Criterios de evaluación</p>
			<p class="subtitle">{courseName}</p>

			<p class="intro">
				Cada competencia se valora contra los criterios que tú defines. Son la referencia para tu
				juicio docente sobre la evidencia del periodo (RVM 094-2020); no se promedian ni se
				convierten en nota.
			</p>

			{#if withoutCriteria > 0}
				<Notice variant="attention">
					<p class="grow notice-text">
						{withoutCriteria === 1
							? '1 competencia todavía no tiene criterios'
							: `${withoutCriteria} competencias todavía no tienen criterios`}
					</p>
				</Notice>
			{/if}

			<div class="stack">
				{#each competencies as comp (comp.competency_id)}
					{@const criteria = list(comp.criteria)}
					<Card>
						<p class="comp-name">{comp.name}</p>
						{#if comp.kind === 'transversal'}
							<p class="comp-kind">Competencia transversal</p>
						{/if}

						{#if criteria.length === 0}
							<EmptyState title="Sin criterios definidos." />
						{:else}
							{#each criteria as c (c.criterion_id)}
								<div class="row criterion">
									<p class="grow criterion-text">{c.description}</p>
									<IconButton
										icon="trash"
										label="Eliminar criterio"
										onclick={() => (deletingId = c.criterion_id)}
										title="Eliminar"
									/>
								</div>
							{/each}
						{/if}

						{#if composingFor === comp.competency_id}
							<Field
								kind="textarea"
								label="Criterio"
								bind:value={draft}
								rows={3}
								placeholder="Ej.: Traduce un problema verbal con dos incógnitas a un sistema de ecuaciones."
								disabled={saving}
							/>
							<div class="row actions">
								<Button
									variant="secondary"
									onclick={() => {
										composingFor = null;
										draft = '';
									}}
									disabled={saving}
								>
									Cancelar
								</Button>
								<Button
									variant="primary"
									onclick={() => void save(comp.competency_id)}
									disabled={saving || draft.trim() === ''}
								>
									Guardar
								</Button>
							</div>
						{:else}
							<Action variant="link" onclick={() => startComposing(comp.competency_id)}>
								+ Agregar criterio
							</Action>
						{/if}
					</Card>
				{/each}
			</div>
		{:else if loadError}
			<Notice variant="danger" live>No se pudieron cargar los criterios.</Notice>
		{:else}<LoadingState label="Cargando…" />{/if}
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
</div>

<style>
	.title {
		margin: 0;
		padding-bottom: 14px;

		font-size: var(--mw-type-title-size);
		font-weight: 800;
		letter-spacing: -0.03em;
		line-height: var(--mw-type-title-line);
	}

	.subtitle {
		margin: 10px 0 var(--mw-space-4);
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}

	.intro {
		margin: 0 0 var(--mw-space-3);
		font-size: var(--mw-type-caption-size);
		line-height: 1.45;
		color: var(--mw-ink-muted);
	}

	.notice-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink);
	}

	.comp-name {
		margin: 0;
		font-size: var(--mw-type-body-size);
		line-height: 1.35;
	}

	.comp-kind {
		margin: 2px 0 0;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
	}

	.criterion {
		gap: var(--mw-space-2);
		align-items: flex-start;
		padding: var(--mw-space-2) 0;
		border-top: 1px solid var(--mw-line-control);
		margin-top: var(--mw-space-2);
	}

	.criterion-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.35;
	}

	.view :global(.draft) {
		width: 100%;
		margin-top: var(--mw-space-2);
	}

	.actions {
		gap: var(--mw-space-2);
		margin-top: var(--mw-space-2);
	}
	.view :global(.add) {
		margin-top: var(--mw-space-3);
	}
</style>
