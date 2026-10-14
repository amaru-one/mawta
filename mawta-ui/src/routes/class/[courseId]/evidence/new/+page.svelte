<script lang="ts">
	import {
		Action,
		Button,
		Checkbox,
		ConfirmDialog,
		EmptyState,
		ErrorNotice,
		Field,
		Icon,
		LoadingState,
		Segmented,
	} from '$lib/design-system';
	// Registering a piece of evidencia: a producción (an informe, a prueba
	// escrita) or an actuación (an exposición, a debate) — for the whole class,
	// or for one student.
	//
	// This was a 360px dialog. It became a screen for one reason: the decision
	// that makes evidence usable later is which competencia and which criterios
	// it speaks to, and in the dialog that was a 180px scroll box under the fold.
	// Nothing is uploaded here — an evidencia is an evaluation the teacher
	// records, not a file.
	//
	// The criterios are a tag, not a mark. Nothing on this screen computes a
	// nivel de logro, and the copy says so twice because it is what gets
	// misread.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type {
		AssessmentKind,
		CompetencyCriteriaDto,
		CriterionDto,
		ValueScale,
	} from '$lib/api/dto';
	import { createAssessment } from '$lib/api/endpoints/classes';
	import { getEvidenceCriteria } from '$lib/api/endpoints/criteria';
	import TopBar from '$lib/components/TopBar.svelte';
	import { EVIDENCE_KIND_LABEL, EVIDENCE_KINDS } from '$lib/evidence';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';
	import { guardUnsaved } from '$lib/unsaved.svelte';

	const courseId = $derived(page.params.courseId ?? '');
	// Set, and the evidence belongs to that student alone. The scope is fixed by
	// the caller and stated in a caption rather than offered as a control: which
	// screen you came from is already the answer.
	const scopeStudentId = $derived(page.url.searchParams.get('student'));
	const scopeStudentName = $derived(page.url.searchParams.get('name') ?? 'este alumno');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let comps = $state<CompetencyCriteriaDto[]>([]);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const crits = await getEvidenceCriteria(courseId);
			comps = list(crits.competencies);
			if (competencyId === '' && comps.length > 0) competencyId = comps[0].competency_id;
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// ---- the form ----

	let title = $state('');
	let kind = $state<AssessmentKind>('produccion');
	let dueAt = $state('');
	let maxScore = $state('20');
	let competencyId = $state('');
	let picked = $state<Set<string>>(new Set());
	let submitting = $state(false);
	// Set only after a save succeeds, so the guard doesn't prompt on the way out.
	let saved = false;
	const leave = guardUnsaved(() => !saved && (title.trim() !== '' || picked.size > 0));

	// Which scale values this evidence. It is a property of the work, not of the
	// app: the same teacher runs a numeric practice and a lettered exposición in
	// the same week. This is what decides which control appears later on the
	// student's screen.
	let scale = $state<ValueScale>('numeric');

	// The maximum is whatever the teacher says the work is worth — 20, 18, 100 —
	// and the app shows the mark as a percentage of it. Whole numbers only: the
	// ruler on the student's screen has one tick per point.
	const maxValid = $derived(
		Number.isInteger(Number(maxScore)) && Number(maxScore) >= 1 && Number(maxScore) <= 100
	);
	const current = $derived(comps.find((c) => c.competency_id === competencyId) ?? null);
	const others = $derived(comps.filter((c) => c.competency_id !== competencyId));

	// The criterios come from the experiencias planned this period (RVM 094-2020,
	// 5.1.1.1: a criterio is written for a situation), so they are shown under the
	// experiencia they belong to — the same sentence can exist in two of them.
	const groups = $derived.by(() => {
		const out: { id: string; title: string; criteria: CriterionDto[] }[] = [];
		for (const c of list(current?.criteria ?? null)) {
			const id = c.experience_id ?? '';
			let g = out.find((x) => x.id === id);
			if (!g) {
				g = { id, title: c.experience_title ?? 'Criterios generales', criteria: [] };
				out.push(g);
			}
			g.criteria.push(c);
		}
		return out;
	});

	// At least one criterio: that is how the evidence reaches a competencia.
	const canSubmit = $derived(
		title.trim() !== '' && picked.size > 0 && (scale !== 'numeric' || maxValid)
	);

	function selectCompetency(id: string): void {
		if (id === competencyId) return;
		hapticTap();
		competencyId = id;
		// Criterios belong to a competencia; keeping a tick across a switch would
		// file the evidence against a criterio the teacher can no longer see.
		picked = new Set();
	}

	function toggleCriterion(id: string): void {
		hapticTap();
		const next = new Set(picked);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		picked = next;
	}

	async function submit(e: Event): Promise<void> {
		e.preventDefault();
		if (!canSubmit || submitting) return;
		submitting = true;
		try {
			await createAssessment(courseId, {
				title: title.trim(),
				kind,
				value_scale: scale,
				// The denominator belongs to the numeric scale and to nothing else;
				// the server rejects it on the other two rather than storing a number
				// nobody would ever use.
				max_score: scale === 'numeric' ? Number(maxScore) : null,
				// The input is a plain date; the API takes a timestamp.
				due_at: dueAt === '' ? null : `${dueAt}T23:59:00-05:00`,
				student_id: scopeStudentId,
				criterion_ids: [...picked],
			});
			showToast(
				scopeStudentId === null
					? 'Evidencia añadida para toda la clase'
					: `Evidencia añadida para ${scopeStudentName}`
			);
			saved = true;
			await goto(`/class/${courseId}`);
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo añadir la evidencia');
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Nueva evidencia — {courseName || 'Clase'}</title>
</svelte:head>
<div class="view">
	<TopBar back="/class/{courseId}" />
	<ConfirmDialog
		bind:open={leave.state.open}
		tone="danger"
		title="¿Salir sin guardar?"
		description="Se perderá la evidencia que estás preparando."
		confirmLabel="Descartar"
		cancelLabel="Seguir editando"
		onconfirm={leave.confirmLeave}
	/>

	<div class="body">
		{#if ready}
			<h1 class="screen-title">Nueva evidencia</h1>
			{#if courseName}<span class="screen-sub">{courseName}</span>{/if}
			<p class="lede">
				{#if scopeStudentId === null}
					Registras una evidencia para toda la clase: una producción (un informe, una prueba
					escrita) o una actuación (una exposición, un debate). Queda en la pantalla de cada alumno.
				{:else}
					Solo para {scopeStudentName}. No aparece en la lista de los demás.
				{/if}
			</p>

			<form onsubmit={submit}>
				<p class="eyebrow">La evaluación</p>

				<Field label="Título" type="text" bind:value={title} placeholder="Práctica calificada" />

				<Field kind="select" label="Tipo" bind:value={kind}>
					{#each EVIDENCE_KINDS as k (k)}
						<option value={k}>{EVIDENCE_KIND_LABEL[k]}</option>
					{/each}
				</Field>

				<Field label="Entrega (opcional)" type="date" bind:value={dueAt} />

				<!-- The scale belongs to the evidence, not to the app: a numeric practice
			     and a lettered exposición can share a week. This is what decides
			     which control appears on the student's screen. -->
				<div class="field">
					<span class="lbl">Cómo se valora</span>
					<Segmented
						label="Cómo se valora"
						value={scale}
						onchange={(value) => (scale = value as typeof scale)}
						options={[
							{ value: 'numeric', label: 'Numérica · sobre un máximo' },
							{ value: 'ordinal', label: 'Literal · AD–C' },
						]}
					/>
				</div>

				{#if scale === 'numeric'}
					<Field
						label="Nota máxima"
						type="number"
						step="1"
						min="1"
						max="100"
						bind:value={maxScore}
						error={maxValid ? undefined : 'Indica un número entero entre 1 y 100.'}
						class="narrow"
					/>
				{/if}
				<p class="note">
					{#if scale === 'numeric'}
						Pones la nota sobre este máximo y la pantalla del alumno la muestra como porcentaje. Una
						nota no es un nivel de logro: ese lo pones tú al cierre, leyendo todo el periodo.
					{:else}
						Una letra en un trabajo no es un nivel de logro: ese lo pones tú al cierre, leyendo todo
						el periodo.
					{/if}
				</p>

				<!-- What makes the evidence usable later. -->
				<p class="eyebrow gap">Qué competencia ayuda a valorar</p>
				<p class="note tight">
					Y con qué criterios la vas a leer. El criterio no se califica: es lo que miras en el
					trabajo.
				</p>

				{#if current === null}
					<EmptyState title="Esta clase no tiene competencias configuradas." />
				{:else}
					<div class="comp">
						<div class="comphead">
							<span class="grow">
								<span class="ccode">{current.code}</span>
								<span class="cname">{current.name}</span>
							</span>
						</div>

						{#if groups.length === 0}
							<EmptyState
								title="Esta competencia no tiene una experiencia planificada este periodo."
								description="Los criterios se escriben para una situación: planifica una experiencia para tener criterios."
							>
								{#snippet actions()}
									<Action href="/class/{courseId}/plan">Ir al plan del trimestre</Action>
								{/snippet}
							</EmptyState>
						{:else}
							{#each groups as g (g.id)}
								<p class="exp">{g.title}</p>
								<div class="crits">
									{#each g.criteria as c (c.criterion_id)}
										<Checkbox
											label={c.code ? `${c.code} · ${c.description}` : c.description}
											checked={picked.has(c.criterion_id)}
											onchange={() => toggleCriterion(c.criterion_id)}
										/>
									{/each}
								</div>
							{/each}
						{/if}
					</div>

					{#if others.length > 0}
						<div class="rest">
							{#each others as c (c.competency_id)}
								<button
									type="button"
									class="orow"
									onclick={() => selectCompetency(c.competency_id)}
								>
									<span class="ocode">{c.code}</span>
									<span class="grow oname">{c.name}</span>
									<span class="ocount">{list(c.criteria).length}</span>
									<span class="chevron"><Icon name="chevron-right" size={16} /></span>
								</button>
							{/each}
						</div>
					{/if}
				{/if}

				<p class="note">
					Esta evidencia no calcula ni sugiere nada. Al cierre, tú pones el nivel de logro de la
					competencia leyendo todas las del periodo.
				</p>

				<Button
					variant="primary"
					block
					class="submit"
					type="submit"
					disabled={!canSubmit || submitting}
					loading={submitting}
				>
					Guardar evidencia
				</Button>
				{#if !canSubmit}<p class="caption">
						{#if title.trim() === ''}Falta el título.{:else if picked.size === 0}Elige al menos un
							criterio.{:else}Revisa la nota máxima.{/if}
					</p>{/if}
				<p class="caption">
					{#if current !== null}{current.code} · {picked.size}
						{picked.size === 1 ? 'criterio' : 'criterios'}{/if}
				</p>
			</form>
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar el formulario." onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	form {
		display: grid;
		gap: var(--mw-space-4);
	}
	.body {
		padding: 20px 20px 32px;
	}

	.lede {
		margin: 10px 0 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.45;
		color: var(--mw-ink-secondary);
		text-wrap: pretty;
	}

	.eyebrow.gap {
		margin-bottom: 6px;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-bottom: 14px;
	}
	.lbl {
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}
	.note {
		margin: 10px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.45;
		color: var(--mw-ink-muted);
		text-wrap: pretty;
	}

	.note.tight {
		margin: 0 0 14px;
	}

	.comp {
		background: var(--mw-surface-tint);
		border-radius: var(--mw-radius-xl);
		padding: 14px;
	}

	.comphead {
		display: flex;
		align-items: flex-start;
		gap: 12px;
	}

	.ccode {
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.cname {
		display: block;
		margin-top: 4px;
		font-size: var(--mw-type-body-size);
		font-weight: 500;
		line-height: 1.3;
		text-wrap: pretty;
	}

	.exp {
		margin: 14px 0 0;
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}

	.crits {
		display: flex;
		flex-direction: column;
		margin-top: 6px;
	}

	.rest {
		display: flex;
		flex-direction: column;
		margin-top: 8px;
	}

	.orow {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 14px 4px;
		border-bottom: 1px solid var(--mw-line);
		text-align: left;
	}

	.ocode {
		flex-shrink: 0;
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.oname {
		font-size: var(--mw-type-small-size);
		line-height: 1.3;
		color: var(--mw-ink-secondary);
	}

	.ocount {
		flex-shrink: 0;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.chevron {
		display: flex;
		flex-shrink: 0;
		color: var(--mw-ink-muted);
	}
	.view :global(.submit) {
		margin-top: 24px;
	}

	.caption {
		margin: 10px 0 0;
		font-size: var(--mw-type-caption-size);
		text-align: center;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}
</style>
