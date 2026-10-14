<script lang="ts">
	import { showError } from '$lib/toast';
	import {
		Button,
		EmptyState,
		ErrorNotice,
		Field,
		Icon,
		IconButton,
		ListRow,
		LoadingState,
	} from '$lib/design-system';
	// The class list. It navigates and it reports — it does NOT evaluate.
	//
	// Everything on screen is scoped to one competencia, chosen in the index at
	// the top, because a nivel de logro only means anything against one. The badge
	// on each row is that competencia's level for that student; a student with no
	// level shows a dash, never a C (RVM 048-2024, 5.1.2.2).
	//
	// Evaluating happens one screen in, on the student. That separation is
	// deliberate: a list that also marked would either overflow or force the
	// teacher to judge thirty students without the evidence in front of them.
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { list } from '$lib/api/client';
	import type { ClassStudentDto, CompetencyCriteriaDto } from '$lib/api/dto';
	import { getClassDashboard } from '$lib/api/endpoints/classes';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import { getClassStudents } from '$lib/api/endpoints/students';
	import CompetencyIndex from '$lib/components/CompetencyIndex.svelte';
	import LevelBadge from '$lib/components/LevelBadge.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import type { CompetencyIndexItem } from '$lib/types';

	const courseId = $derived(page.params.courseId ?? '');
	// `?comp=` names which competencia was being looked at, so it survives a
	// remount (back navigation, a reload) the same way `?name=`/`?course=` do on
	// the student screen this list opens.
	const compParam = $derived(page.url.searchParams.get('comp') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let className = $state('');
	let rows = $state<ClassStudentDto[]>([]);
	let comps = $state<CompetencyCriteriaDto[]>([]);
	let selected = $state('');

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const [dash, crits] = await Promise.all([
				getClassDashboard(courseId),
				getClassCriteria(courseId),
			]);
			className = dash.name;
			comps = list(crits.competencies);
			if (selected === '' && comps.length > 0) {
				selected =
					compParam && comps.some((c) => c.competency_id === compParam)
						? compParam
						: comps[0].competency_id;
			}
			rows = list((await getClassStudents(courseId, selected || undefined)).students);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// The levels and the evidence counts are per competencia, so switching the
	// index refetches the list. The names do not change, so the rows are left on
	// screen while it lands rather than blanking to a spinner.
	let switching = $state(false);
	// Bumped by "Reintentar" to run the competencia fetch again.
	let attempt = $state(0);

	$effect(() => {
		const competencyId = selected;
		void attempt;
		untrack(() => {
			if (!ready || competencyId === '') return;
			switching = true;
			getClassStudents(courseId, competencyId)
				.then((res) => {
					rows = list(res.students);
				})
				.catch(() => {
					// Old rows must not stay under the new competencia's header.
					rows = [];
					showError('No se pudo cargar esta competencia', {
						onRetry: () => {
							attempt += 1;
						},
					});
				})
				.finally(() => {
					switching = false;
				});
		});
	});

	// ---- the index ----

	// Reflects the choice into `?comp=` with replaceState — no new history entry,
	// so a back navigation (e.g. from a student's screen) lands on the URL that
	// already names this competencia instead of on the pre-choice one. The
	// existing `$effect` above (keyed on `selected`) still does the actual
	// refetch; this only makes the choice survive a remount.
	function selectCompetency(id: string): void {
		selected = id;
		const params = new URLSearchParams(page.url.searchParams);
		params.set('comp', id);
		void goto(`?${params.toString()}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// Área competencias are numbered in the order the área lists them;
	// transversales keep a short code, since they belong to no área.
	// Only the selected competencia's levels are loaded, so the index can only
	// mark the one being looked at — "closed for the whole class" for the others
	// would need every competencia's levels, which is a bigger read than the
	// glyph is worth.
	const allJudged = $derived(rows.length > 0 && rows.every((r) => r.level !== null));

	const indexItems = $derived.by<CompetencyIndexItem[]>(() => {
		let n = 0;
		return comps.map((c) => {
			const area = c.kind !== 'transversal';
			if (area) n += 1;
			return {
				id: c.competency_id,
				label: area ? String(n) : c.code.replace(/^TRANS-/, ''),
				kind: c.kind,
				hasLevel: c.competency_id === selected && allJudged,
			};
		});
	});

	const currentName = $derived(comps.find((c) => c.competency_id === selected)?.name ?? '');
	const withLevel = $derived(rows.filter((r) => r.level !== null).length);

	// ---- search ----

	let searching = $state(false);
	let query = $state('');

	function toggleSearch(): void {
		hapticTap();
		searching = !searching;
		if (!searching) query = '';
	}

	// The field is inserted on tap, and `autofocus` is ignored on an element added
	// after load — opening the search has to land the caret.
	function focusHere(node: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): void {
		node.focus();
	}

	const shown = $derived.by(() => {
		const q = query.trim().toLowerCase();
		return q === '' ? rows : rows.filter((r) => r.full_name.toLowerCase().includes(q));
	});

	const href = (r: ClassStudentDto): string =>
		`/class/${courseId}/students/${r.student_id}?name=${encodeURIComponent(r.full_name)}&course=${encodeURIComponent(className)}&comp=${encodeURIComponent(selected)}`;

	const evidenceLabel = (n: number): string =>
		n === 0 ? 'Sin evidencias' : n === 1 ? '1 evidencia' : `${n} evidencias`;
</script>

<svelte:head>
	<title>Alumnos — {className || 'Clase'}</title>
</svelte:head>
<div class="view">
	<TopBar back="/class/{courseId}" />

	<div class="body">
		{#if ready}
			<div class="titlerow">
				<h1 class="title">Alumnos</h1>
				<IconButton
					icon="search"
					label={searching ? 'Cerrar búsqueda' : 'Buscar por apellido'}
					aria-expanded={searching}
					onclick={toggleSearch}
				/>
			</div>
			<span class="sub">{className} · {rows.length} alumnos</span>

			{#if searching}
				<div class="search-wrap">
					<Field
						label="Buscar por apellido"
						type="text"
						placeholder="Buscar por apellido"
						bind:value={query}
						{@attach focusHere}
					/>
				</div>
			{/if}

			{#if indexItems.length > 0}
				<div class="idx">
					<CompetencyIndex items={indexItems} selectedId={selected} onselect={selectCompetency} />
				</div>
				<p class="comp">{currentName}</p>
				<p class="count">{withLevel} DE {rows.length} CON NIVEL</p>
			{/if}

			{#if shown.length === 0}
				<EmptyState
					title={query.trim() === '' ? 'Esta clase no tiene alumnos.' : 'Ningún alumno coincide.'}
				/>
			{:else}
				<div class="list" class:switching>
					{#each shown as r (r.student_id)}
						<ListRow href={href(r)} onclick={hapticTap}>
							<span class="lvl">
								{#if r.level !== null}
									<LevelBadge tier={r.level} />
								{:else}
									<span class="nolevel" aria-label="Sin nivel">Sin nivel</span>
								{/if}
							</span>
							<span class="grow">
								<span class="name">{r.full_name}</span>
								<span class="ev">{evidenceLabel(r.evidence_count)}</span>
							</span>
						</ListRow>
					{/each}
				</div>

				<p class="foot">
					El nivel de logro lo pones tú, leyendo las evidencias del periodo. Ninguna evidencia lo
					calcula.
				</p>
			{/if}
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar la lista." onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	.body {
		padding: 20px 20px 32px;
	}

	.titlerow {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding-bottom: 14px;
	}

	.title {
		margin: 0;
		font-size: var(--mw-type-title-size);
		font-weight: 800;
		letter-spacing: -0.03em;
		line-height: 1.12;
	}

	.sub {
		display: block;
		margin-top: 8px;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.search-wrap {
		margin-top: 16px;
	}

	.idx {
		margin-top: 14px;
	}

	.comp {
		margin: 16px 0 0;
		font-size: 19px;
		font-weight: 500;
		line-height: 1.3;
		letter-spacing: -0.01em;
		text-wrap: pretty;
	}

	.count {
		margin: 6px 0 0;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.list {
		display: flex;
		flex-direction: column;
		margin-top: 24px;
	}

	.list.switching {
		opacity: 0.5;
	}

	.name {
		display: block;
		font-size: var(--mw-type-heading-size);
		font-weight: 600;
		letter-spacing: -0.01em;
		line-height: 1.25;
	}

	.ev {
		display: block;
		margin-top: 2px;
		font-size: var(--mw-type-caption-size);
		line-height: 1.3;
		color: var(--mw-ink-muted);
	}

	/* A fixed, centred slot for the level, so names line up whether the student
	 * has a level or not. The slot is wider than the 60px pill on purpose. */
	.lvl {
		flex: 0 0 64px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	/* Same footprint as the level pill, with a dashed outline so "no level"
	 * is told apart by shape and text, not only by colour. */
	.nolevel {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 60px;
		height: 28px;
		box-sizing: border-box;
		padding: 0 4px;
		border: 1px dashed var(--mw-line-control);
		border-radius: var(--mw-radius-md);
		font-size: 12px;
		font-weight: 600;
		color: var(--mw-ink-secondary);
		white-space: nowrap;
	}

	.foot {
		margin: 16px 4px 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.45;
		color: var(--mw-ink-muted);
		text-wrap: pretty;
	}
</style>
