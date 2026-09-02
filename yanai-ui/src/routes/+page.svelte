<script lang="ts">
	import { onMount } from 'svelte';
	import { list } from '$lib/api/client';
	import type { HomeDto, SessionStatus } from '$lib/api/dto';
	import { getHome } from '$lib/api/endpoints/home';
	import { formatTimeHHMM, parseDateOnly } from '$lib/api/mappers';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';

	let d = $state<HomeDto | null>(null);
	let ready = $state(false);
	let loadError = $state(false);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			d = await getHome();
			ready = true;
		} catch {
			loadError = true;
		}
	}

	// Wall-clock reference for the "ahora" marker and the en curso / finished
	// row states, refreshed on an interval so the agenda keeps up with the day
	// while the page stays open. Same pattern as the class dashboard.
	let now = $state(Date.now());

	onMount(() => {
		load();
		const id = setInterval(() => {
			now = Date.now();
		}, 60_000);
		return () => clearInterval(id);
	});

	// Search stays folded away until asked for: the day is what this screen is
	// about, and most teachers have few enough classes to never need it.
	let searching = $state(false);
	let query = $state('');

	function toggleSearch(): void {
		hapticTap();
		searching = !searching;
		if (!searching) query = '';
	}

	// The field is inserted on tap, and the `autofocus` attribute is ignored on
	// an element added after load — opening the search has to land the caret.
	function focusHere(node: HTMLInputElement): void {
		node.focus();
	}

	const matches = (name: string): boolean => {
		const q = query.trim().toLowerCase();
		return q === '' || name.toLowerCase().includes(q);
	};

	// One class in one time slot — the unit both the rail and the week render.
	type Slot = {
		classId: string;
		sessionId: string;
		name: string;
		start: string;
		end: string;
		room: string | null;
		status: SessionStatus;
	};

	const todaySlots = $derived.by((): Slot[] =>
		list(d?.today)
			.filter((t) => t.session_id !== null && t.scheduled_start_at !== null)
			.map((t) => ({
				classId: t.class_id,
				sessionId: t.session_id as string,
				name: t.name,
				start: t.scheduled_start_at as string,
				end: t.scheduled_end_at as string,
				room: t.room,
				status: (t.status ?? 'scheduled') as SessionStatus,
			}))
			.filter((s) => matches(s.name))
	);

	// An hour label with the sessions that start in it, or an empty hour marking
	// a gap in the day. Gaps are what make the rail read as time rather than as
	// a list — one row is enough to show the day breathes there.
	type RailRow = { kind: 'hour'; hour: number; slots: Slot[] } | { kind: 'gap'; hour: number };

	const hourOf = (ts: string): number => new Date(ts).getHours();

	const rail = $derived.by((): RailRow[] => {
		const rows: RailRow[] = [];
		let prevEndHour: number | null = null;

		for (const s of todaySlots) {
			const h = hourOf(s.start);
			const last = rows.at(-1);
			if (last?.kind === 'hour' && last.hour === h) {
				last.slots.push(s);
			} else {
				if (prevEndHour !== null && h - prevEndHour > 1) {
					rows.push({ kind: 'gap', hour: prevEndHour + 1 });
				}
				rows.push({ kind: 'hour', hour: h, slots: [s] });
			}
			prevEndHour = hourOf(s.end);
		}
		return rows;
	});

	const hourLabel = (h: number): string => `${String(h).padStart(2, '0')}:00`;

	type Phase = 'before' | 'during' | 'after';

	// Clock-derived, never status-derived — `status` only tells us a session was
	// called off, not where the day currently stands.
	const phaseOf = (s: Slot, ref: number): Phase => {
		const start = new Date(s.start).getTime();
		const end = new Date(s.end).getTime();
		if (ref < start) return 'before';
		if (ref > end) return 'after';
		return 'during';
	};

	const isOff = (s: Slot): boolean => s.status === 'cancelled' || s.status === 'rescheduled';

	// The marker belongs on the day it describes: paging to another date, or
	// leaving the tab open past midnight, must not draw "ahora" on it.
	const isRealToday = $derived.by(() => {
		if (d === null) return false;
		const t = new Date(now);
		const iso = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
		return d.date === iso;
	});

	// The marker sits above the first session that has not finished yet; once
	// the last one ends it drops to the bottom of the rail.
	const nowBefore = $derived(todaySlots.find((s) => new Date(s.end).getTime() >= now)?.sessionId);
	const nowAtEnd = $derived(isRealToday && todaySlots.length > 0 && nowBefore === undefined);

	const nowLabel = $derived.by(() => {
		const t = new Date(now);
		return `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
	});

	const capitalize = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

	const shortMonth = (dt: Date): string =>
		dt.toLocaleDateString('es-PE', { month: 'short' }).replace('.', '').toUpperCase();

	// "2026-09-01" → "Miércoles 1 SEP"
	const longDate = (iso: string): string => {
		const dt = parseDateOnly(iso);
		const weekday = capitalize(dt.toLocaleDateString('es-PE', { weekday: 'long' }));
		return `${weekday} ${dt.getDate()} ${shortMonth(dt)}`;
	};

	// "2026-08-31" → { day: "LUN", num: "31" }
	const dayParts = (iso: string): { day: string; num: string } => {
		const dt = parseDateOnly(iso);
		return {
			day: dt.toLocaleDateString('es-PE', { weekday: 'short' }).replace('.', '').toUpperCase(),
			num: String(dt.getDate()),
		};
	};

	const summary = $derived.by(() => {
		const n = todaySlots.length;
		if (n === 0) return '';
		const label = n === 1 ? '1 clase' : `${n} clases`;
		const first = formatTimeHHMM(todaySlots[0].start);
		const lastEnd = formatTimeHHMM(todaySlots[todaySlots.length - 1].end);
		return `${label} · ${first} – ${lastEnd}`;
	});

	// Days keep their order from the server; a day whose every class is filtered
	// out drops away rather than showing an empty gutter.
	const weekDays = $derived.by(() =>
		list(d?.week)
			.map((day) => ({
				date: day.date,
				past: d !== null && day.date < d.date,
				sessions: list(day.sessions).filter((s) => matches(s.name)),
			}))
			.filter((day) => day.sessions.length > 0)
	);
</script>

<svelte:head>
	<title>Yanai — Inicio</title>
</svelte:head>

<TopBar variant="home" />

<div class="body">
	{#if ready && d}
		<div class="head">
			<h1 class="date">{longDate(d.date)}</h1>
			<button
				type="button"
				class="find pressable"
				aria-label={searching ? 'Cerrar búsqueda' : 'Buscar por clase'}
				aria-expanded={searching}
				onclick={toggleSearch}
			>
				<Icon name="search" size={16} />
			</button>
		</div>
		<p class="sum">{summary || 'Sin clases hoy'}</p>

		{#if searching}
			<div class="search-wrap">
				<span class="search-icon"><Icon name="search" size={16} /></span>
				<input
					class="search"
					type="text"
					placeholder="Buscar por clase"
					bind:value={query}
					{@attach focusHere}
				/>
			</div>
		{/if}

		{#if todaySlots.length > 0}
			<div class="rail">
				{#each rail as row (row.kind + row.hour)}
					<div class="slot" class:empty={row.kind === 'gap'}>
						<span class="hr">{hourLabel(row.hour)}</span>
						{#if row.kind === 'hour'}
							{#each row.slots as s (s.sessionId)}
								{#if isRealToday && nowBefore === s.sessionId}
									<div class="nowline" aria-hidden="true"><span>{nowLabel}</span></div>
								{/if}
								{@const phase = phaseOf(s, now)}
								{@const off = isOff(s)}
								{#if off}
									<span class="item off">
										<b>{s.name}</b>
										<span class="meta">
											{formatTimeHHMM(s.start)} – {formatTimeHHMM(s.end)}
											{#if s.room}· {s.room}{/if} · cancelada
										</span>
									</span>
								{:else}
									<a
										class="item pressable"
										class:now={phase === 'during'}
										class:done={phase === 'after'}
										href="/class/{s.classId}/lesson/{s.sessionId}"
										onclick={hapticTap}
									>
										<b>{s.name}</b>
										<span class="meta">
											{formatTimeHHMM(s.start)} – {formatTimeHHMM(s.end)}
											{#if s.room}· {s.room}{/if}
											{#if phase === 'during'}· <em>en curso</em>{/if}
										</span>
									</a>
								{/if}
							{/each}
						{/if}
					</div>
				{/each}
				{#if nowAtEnd}
					<div class="nowline trailing" aria-hidden="true"><span>{nowLabel}</span></div>
				{/if}
			</div>
		{:else}
			<p class="none">
				{query.trim() === '' ? 'Hoy no tienes clases.' : 'Ninguna clase de hoy coincide.'}
			</p>
		{/if}

		{#if weekDays.length > 0}
			<div class="week">
				<p class="eyebrow">La semana</p>
				{#each weekDays as day (day.date)}
					{@const dp = dayParts(day.date)}
					<div class="day" class:past={day.past}>
						<span class="d">
							<b>{dp.day}</b>
							<span>{dp.num}</span>
						</span>
						<span class="lines">
							{#each day.sessions as s (s.session_id)}
								<a
									class="wline pressable"
									href="/class/{s.class_id}/lesson/{s.session_id}"
									onclick={hapticTap}
								>
									<span class="wname">{s.name}</span>
									<span class="wtime">{formatTimeHHMM(s.scheduled_start_at)}</span>
								</a>
							{/each}
						</span>
					</div>
				{/each}
			</div>
		{:else if todaySlots.length === 0 && query.trim() === ''}
			<p class="none quiet">No tienes clases esta semana.</p>
		{/if}
	{:else if loadError}
		<p class="none">
			No se pudieron cargar las clases.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	/* This screen sets its own gutter, matching the class dashboard's — the two
	   read as one family, and the rail's hour column is measured against it. */
	.body {
		padding: 22px 18px 30px;
	}

	/* Wider-tracked and bolder than the app-wide .eyebrow, as on the dashboard. */
	.eyebrow {
		margin: 0 0 6px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 6px;
	}

	.date {
		margin: 0;
		font-size: 22px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}

	.find {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		flex-shrink: 0;
		border-radius: 50%;
		color: var(--text-muted);
		/* Baseline alignment puts a bare icon too high beside 22px type. */
		transform: translateY(4px);
	}

	.sum {
		margin: 0 0 28px;
		font-size: 12px;
		font-family: var(--font-mono);
		letter-spacing: 0.04em;
		color: var(--text-muted);
	}

	.search-wrap {
		margin: -14px 0 26px;
	}

	/* ---- the day, as a time rail ---- */

	.rail {
		position: relative;
		padding-left: 50px;
		/* Keeps the trailing marker's margins from collapsing out of the rail,
		   which would drop it onto the week heading below. */
		padding-bottom: 2px;
	}

	.rail::before {
		content: '';
		position: absolute;
		left: 42px;
		top: 4px;
		bottom: 10px;
		width: 1px;
		background: var(--border);
	}

	.slot {
		position: relative;
	}

	/* An empty hour still occupies the rail — that is the gap being shown. */
	.slot.empty {
		min-height: 52px;
	}

	/* Sits on the first row's title line, not above the group — the label reads
	   as the time that row happens at. */
	.hr {
		position: absolute;
		left: -50px;
		top: 12px;
		width: 34px;
		text-align: right;
		font-size: 11px;
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	.item {
		display: block;
		padding: 11px 0 13px;
		color: inherit;
		border-top: 0.5px solid var(--border);
	}

	/* Every row is ruled off from the one above, across hour groups as well as
	   within them; only the very first row in the day opens without a rule.
	   The hour label is each slot's first child, so the row is matched through
	   it rather than with :first-child. */
	.slot:first-child .hr + .item {
		border-top: none;
	}

	.item b {
		display: block;
		font-size: 16px;
		font-weight: 500;
		line-height: 1.2;
	}

	.item .meta {
		display: block;
		margin-top: 4px;
		font-size: 12.5px;
		color: var(--text-secondary);
	}

	/* The one loud element on the screen is black, not accent — the accent is
	   reserved for assistant-generated signals (see app.css). */
	.item.now {
		padding-left: 12px;
		border-left: 2px solid var(--fill-primary);
	}

	.item.now .meta em {
		font-style: normal;
		font-family: var(--font-mono);
		font-size: 11px;
		letter-spacing: 0.03em;
	}

	.item.done b,
	.item.done .meta,
	.item.off b,
	.item.off .meta {
		color: var(--text-muted);
	}

	.nowline {
		position: relative;
		height: 0;
		margin: 6px 0 2px;
	}

	.nowline::before {
		content: '';
		position: absolute;
		left: -10px;
		top: -3px;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--fill-primary);
	}

	.nowline::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		height: 1px;
		background: var(--fill-primary);
		opacity: 0.35;
	}

	.nowline span {
		position: absolute;
		right: 0;
		top: -15px;
		font-size: 10px;
		font-family: var(--font-mono);
		color: var(--text-primary);
	}

	/* With the day over the marker lands at the foot of the rail, where it needs
	   room on both sides or it reads as a section rule. */
	.nowline.trailing {
		margin: 26px 0 0;
	}

	/* ---- the week ---- */

	.week {
		margin-top: 34px;
	}

	.day {
		display: flex;
		gap: 16px;
		padding: 12px 0;
		border-top: 0.5px solid var(--border);
	}

	.day:last-child {
		border-bottom: 0.5px solid var(--border);
	}

	/* Days already behind us stay readable but stop asking for attention. */
	.day.past .wname,
	.day.past .wtime,
	.day.past .d span {
		color: var(--text-muted);
	}

	.d {
		width: 40px;
		flex-shrink: 0;
		padding-top: 4px;
	}

	.d b {
		display: block;
		font-size: 11px;
		font-weight: 400;
		font-family: var(--font-mono);
		letter-spacing: 0.06em;
		color: var(--text-muted);
	}

	.d span {
		display: block;
		margin-top: 2px;
		font-size: 16px;
		font-weight: 600;
	}

	.lines {
		flex: 1;
		min-width: 0;
	}

	.wline {
		display: flex;
		align-items: baseline;
		gap: var(--space-md);
		padding: 4px 0;
		color: inherit;
	}

	.wname {
		flex: 1;
		min-width: 0;
		font-size: 14px;
		line-height: 1.45;
	}

	.wtime {
		flex-shrink: 0;
		font-size: 12px;
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	/* ---- empty and error ---- */

	.none {
		margin: 8px 0 0;
		font-size: 17px;
		color: var(--text-secondary);
	}

	.none.quiet {
		margin-top: 28px;
		font-size: 14px;
		color: var(--text-muted);
	}
</style>
