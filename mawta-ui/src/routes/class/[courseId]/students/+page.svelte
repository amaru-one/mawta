<script lang="ts">
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
	import Icon from '$lib/components/Icon.svelte';
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

	$effect(() => {
		const competencyId = selected;
		untrack(() => {
			if (!ready || competencyId === '') return;
			switching = true;
			getClassStudents(courseId, competencyId)
				.then((res) => {
					rows = list(res.students);
				})
				.catch(() => {
					/* the list on screen stays; the next switch or a reload retries */
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
	function focusHere(node: HTMLInputElement): void {
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

<TopBar back="/class/{courseId}" useHistory />

<div class="body">
	{#if ready}
		<div class="titlerow">
			<h1 class="title">Alumnos</h1>
			<button
				type="button"
				class="find pressable"
				aria-label={searching ? 'Cerrar búsqueda' : 'Buscar por apellido'}
				aria-expanded={searching}
				onclick={toggleSearch}
			>
				<Icon name="search" size={18} />
			</button>
		</div>
		<span class="sub">{className} · {rows.length} alumnos</span>

		{#if searching}
			<div class="search-wrap">
				<span class="search-icon"><Icon name="search" size={16} /></span>
				<input
					class="search"
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
			<p class="empty">
				{query.trim() === '' ? 'Esta clase no tiene alumnos.' : 'Ningún alumno coincide.'}
			</p>
		{:else}
			<div class="list" class:switching>
				{#each shown as r (r.student_id)}
					<a class="row pressable" href={href(r)} onclick={hapticTap}>
						{#if r.level !== null}
							<LevelBadge tier={r.level} size={26} />
						{:else}
							<span class="nolevel" title="Sin nivel">–</span>
						{/if}
						<span class="grow">
							<span class="name">{r.full_name}</span>
							<span class="ev">{evidenceLabel(r.evidence_count)}</span>
						</span>
						<span class="chevron"><Icon name="chevron-right" size={18} /></span>
					</a>
				{/each}
			</div>

			<p class="foot">
				El nivel de logro lo pones tú, leyendo las evidencias del periodo. Ninguna evidencia lo
				calcula.
			</p>
		{/if}
	{:else if loadError}
		<p class="empty">
			No se pudo cargar la lista.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	/* Same gutter as the área — this screen is read as its continuation. */
	.body {
		padding: 22px 18px 30px;
	}

	.titlerow {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding-bottom: 14px;
		border-bottom: 1.5px solid var(--text-primary);
	}

	.title {
		margin: 0;
		font-size: 34px;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.12;
	}

	.find {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 34px;
		height: 34px;
		flex-shrink: 0;
		border-radius: 50%;
		background: var(--aurora-tint);
		color: var(--aurora-deep);
	}

	.sub {
		display: block;
		margin-top: 8px;
		font-size: 13px;
		color: var(--text-muted);
		font-family: var(--font-mono);
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
		font-size: 11px;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.list {
		display: flex;
		flex-direction: column;
		margin-top: 24px;
	}

	/* The level leads the row: it is what the teacher scans down, and putting it
	   left means the eye never has to cross a ragged name column to find it. */
	.row {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px 4px;
		border-top: 0.5px solid var(--border);
		color: inherit;
	}

	.row:last-child {
		border-bottom: 0.5px solid var(--border);
	}

	/* Switching competencia refetches levels and counts; the names are the same
	   either way, so the list dims rather than disappearing. */
	.list.switching {
		opacity: 0.5;
	}

	.name {
		display: block;
		font-size: 16px;
		font-weight: 600;
		letter-spacing: -0.01em;
		line-height: 1.25;
	}

	.ev {
		display: block;
		margin-top: 2px;
		font-size: 12px;
		line-height: 1.3;
		color: var(--text-muted);
	}

	/* Not evaluated is its own state — a dash, never a C. */
	.nolevel {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		flex-shrink: 0;
		border: 1px dashed var(--border-strong);
		border-radius: 50%;
		font-size: 15px;
		font-weight: 600;
		color: var(--text-muted);
	}

	.chevron {
		display: flex;
		flex-shrink: 0;
		color: var(--text-muted);
	}

	.foot {
		margin: 16px 4px 0;
		font-size: 12px;
		line-height: 1.45;
		color: var(--text-muted);
		text-wrap: pretty;
	}

	.empty {
		margin: 24px 0 0;
		font-size: 15px;
		line-height: 1.45;
		color: var(--text-secondary);
	}
</style>
