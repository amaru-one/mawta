<script lang="ts">
	import { Button, EmptyState, LoadingState } from '$lib/design-system';
	import { onMount, untrack } from 'svelte';
	import { list } from '$lib/api/client';
	import type { HomeDto, HomeTodayDto, HomeWeekSessionDto, SessionStatus } from '$lib/api/dto';
	import { getHome } from '$lib/api/endpoints/home';
	import { formatTimeHHMM, parseDateOnly } from '$lib/api/mappers';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';

	// The grid's fixed window and scale. One hour is always HOUR_PX tall, which
	// is what makes a 90-minute class read as twice a 45-minute one and a break
	// read as the space it actually occupies.
	const OPEN_H = 7;
	const CLOSE_H = 17;
	const HOUR_PX = 64;

	let d = $state<HomeDto | null>(null);

	let selected = $state('');
	let ready = $state(false);
	let loadError = $state(false);
	let gridEl = $state<HTMLDivElement | null>(null);

	// One call, once: the screen never leaves the ISO week it loads, so
	// `getHome`'s date parameter is deliberately unused here.
	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const res = await getHome();
			d = res;
			// The strip is Monday to Friday, so a weekend "today" has no cell of
			// its own. Land on that week's Friday — the last school day, and
			// inside the ISO week this payload already covers.
			const dow = parseDateOnly(res.date).getDay();
			selected = dow === 0 ? addDays(res.date, -2) : dow === 6 ? addDays(res.date, -1) : res.date;
			ready = true;
		} catch {
			loadError = true;
		}
	}

	// Wall-clock reference for the "ahora" line and the en curso / finished
	// states, refreshed on an interval so the screen keeps up with the day.
	let now = $state(Date.now());

	onMount(() => {
		load();
		const id = setInterval(() => {
			now = Date.now();
		}, 60_000);
		return () => clearInterval(id);
	});

	// ---- dates ----

	const isoOf = (dt: Date): string =>
		`${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;

	const addDays = (iso: string, n: number): string => {
		const dt = parseDateOnly(iso);
		dt.setDate(dt.getDate() + n);
		return isoOf(dt);
	};

	const mondayOf = (iso: string): string => {
		const dt = parseDateOnly(iso);
		dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
		return isoOf(dt);
	};

	const realToday = $derived(isoOf(new Date(now)));
	const isRealToday = $derived(selected !== '' && selected === realToday);

	// ---- sessions for a day ----

	type Slot = {
		classId: string;
		sessionId: string;
		name: string;
		start: string;
		end: string;
		room: string | null;
		status: SessionStatus;
	};

	const fromToday = (t: HomeTodayDto): Slot | null =>
		t.session_id !== null && t.scheduled_start_at !== null && t.scheduled_end_at !== null
			? {
					classId: t.class_id,
					sessionId: t.session_id,
					name: t.name,
					start: t.scheduled_start_at,
					end: t.scheduled_end_at,
					room: t.room,
					status: (t.status ?? 'scheduled') as SessionStatus,
				}
			: null;

	const fromWeek = (s: HomeWeekSessionDto): Slot => ({
		classId: s.class_id,
		sessionId: s.session_id,
		name: s.name,
		start: s.scheduled_start_at,
		end: s.scheduled_end_at,
		room: s.room,
		status: s.status,
	});

	// `GetHome` answers with the requested day in `today` and the REST of its ISO
	// week in `week` — the day itself is excluded there (`session_date <> $2`).
	// The union covers the whole week, so moving between weekdays needs no call.
	const sessionsFor = (iso: string): Slot[] => {
		if (d === null) return [];
		const raw =
			iso === d.date
				? list(d.today)
						.map(fromToday)
						.filter((s): s is Slot => s !== null)
				: list(list(d.week).find((w) => w.date === iso)?.sessions).map(fromWeek);
		return raw.slice().sort((a, b) => a.start.localeCompare(b.start));
	};

	const slots = $derived(sessionsFor(selected));

	// ---- the week strip ----

	const LETTERS = ['L', 'M', 'M', 'J', 'V'];

	// Monday to Friday of the selected day's week. Built from the dates rather
	// than from `week`, which only carries days that have sessions at all.
	const strip = $derived.by(() => {
		if (selected === '') return [];
		const mon = mondayOf(selected);
		return LETTERS.map((letter, i) => {
			const iso = addDays(mon, i);
			return {
				iso,
				letter,
				num: String(parseDateOnly(iso).getDate()),
				// Deliberately unfiltered by the search: the dot says the day has
				// classes, not that it has matching ones.
				has: sessionsFor(iso).length > 0,
				selected: iso === selected,
				today: iso === realToday,
			};
		});
	});

	function pick(iso: string): void {
		if (iso === selected) return;
		hapticTap();
		selected = iso;
	}

	// ---- the grid ----

	const minsOf = (ts: string): number => {
		const dt = new Date(ts);
		return dt.getHours() * 60 + dt.getMinutes();
	};

	// The window is fixed so that changing day does not move the scale under the
	// teacher's feet; it only stretches for a day with something outside it.
	const openH = $derived(
		slots.length === 0 ? OPEN_H : Math.min(OPEN_H, Math.floor(minsOf(slots[0].start) / 60))
	);
	const closeH = $derived(
		slots.length === 0
			? CLOSE_H
			: Math.max(CLOSE_H, Math.ceil(Math.max(...slots.map((s) => minsOf(s.end))) / 60))
	);
	const gridHeight = $derived((closeH - openH) * HOUR_PX);

	const hours = $derived.by(() =>
		Array.from({ length: closeH - openH + 1 }, (_, i) => ({
			h: openH + i,
			label: `${String(openH + i).padStart(2, '0')}:00`,
			y: i * HOUR_PX,
		}))
	);

	const nowMin = $derived.by(() => {
		const t = new Date(now);
		return t.getHours() * 60 + t.getMinutes();
	});

	const blocks = $derived.by(() =>
		slots.map((s) => {
			const startM = minsOf(s.start);
			const endM = minsOf(s.end);
			const off = s.status === 'cancelled' || s.status === 'rescheduled';
			return {
				...s,
				off,
				live: isRealToday && !off && nowMin >= startM && nowMin <= endM,
				done: isRealToday && !off && nowMin > endM,
				top: ((startM - openH * 60) / 60) * HOUR_PX,
				// 2px shaved off so two back-to-back classes keep a seam.
				height: ((endM - startM) / 60) * HOUR_PX - 2,
				time: `${formatTimeHHMM(s.start)} – ${formatTimeHHMM(s.end)}${s.room ? ` · ${s.room}` : ''}`,
			};
		})
	);

	const nowTop = $derived(
		isRealToday && nowMin >= openH * 60 && nowMin <= closeH * 60
			? ((nowMin - openH * 60) / 60) * HOUR_PX
			: null
	);

	const nowLabel = $derived.by(() => {
		const t = new Date(now);
		return `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
	});

	// Ten hours do not fit under the strip, so the grid opens where the day is:
	// on the current time today, on the first class otherwise. Untracked on
	// purpose — this must fire on a day change, never on a clock tick, or it
	// would yank the teacher's scroll back every minute.
	$effect(() => {
		const day = selected;
		if (!ready || gridEl === null || day === '') return;
		untrack(() => {
			const target = nowTop ?? (blocks.length > 0 ? blocks[0].top : 0);
			gridEl!.scrollTop = Math.max(0, target - 80);
		});
	});

	// ---- labels ----

	const capitalize = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

	const shortMonth = (dt: Date): string =>
		dt.toLocaleDateString('es-PE', { month: 'short' }).replace('.', '').toUpperCase();

	// "2026-09-03" → "Jueves 3 SET"
	const longDate = (iso: string): string => {
		const dt = parseDateOnly(iso);
		return `${capitalize(dt.toLocaleDateString('es-PE', { weekday: 'long' }))} ${dt.getDate()} ${shortMonth(dt)}`;
	};

	const summary = $derived.by(() => {
		if (slots.length === 0) return 'Sin clases';
		const label = slots.length === 1 ? '1 clase' : `${slots.length} clases`;
		const lastEnd = slots.reduce((a, s) => (minsOf(s.end) > minsOf(a.end) ? s : a), slots[0]);
		return `${label} · ${formatTimeHHMM(slots[0].start)} – ${formatTimeHHMM(lastEnd.end)}`;
	});
</script>

<svelte:head>
	<title>Mawta — Inicio</title>
</svelte:head>
<div class="view">
	<div class="screen">
		<TopBar variant="home" />

		{#if ready && selected !== ''}
			<div class="head">
				<div class="titlerow">
					<h1 class="date">{longDate(selected)}</h1>
				</div>
				<p class="sum">{summary}</p>

				<!-- The strip is the whole of the day navigation: five days, the week on
			     screen is the only week there is. -->
				<div class="strip">
					{#each strip as day (day.iso)}
						<button
							type="button"
							class="day pressable"
							aria-label={longDate(day.iso)}
							aria-current={day.selected ? 'date' : undefined}
							onclick={() => pick(day.iso)}
						>
							<span class="dow" class:on={day.selected}>{day.letter}</span>
							<span class="num" class:on={day.selected} class:ring={day.today && !day.selected}
								>{day.num}</span
							>
							<span class="dot" class:has={day.has} class:on={day.selected}></span>
						</button>
					{/each}
				</div>
			</div>

			<!-- No classes, no grid: ten empty hours state the same thing as one line
		     and take the whole screen to do it. -->
			{#if blocks.length === 0}
				<div class="head">
					<EmptyState title="Este día no tienes clases." />
				</div>
			{:else}
				<div class="grid" bind:this={gridEl}>
					<div class="canvas" style="height: {gridHeight}px">
						{#each hours as hour (hour.h)}
							<div class="hline" style="top: {hour.y}px"></div>
							<span class="hlabel" style="top: {hour.y - 1}px">{hour.label}</span>
						{/each}

						{#each blocks as b (b.sessionId)}
							{#if b.off}
								<span class="box off" style="top: {b.top}px; height: {b.height}px">
									<span class="btime"
										>{b.time} · {b.status === 'rescheduled' ? 'reprogramada' : 'cancelada'}</span
									>
									<span class="bname">{b.name}</span>
								</span>
							{:else}
								<a
									class="box pressable"
									class:live={b.live}
									class:done={b.done}
									style="top: {b.top}px; height: {b.height}px"
									href="/class/{b.classId}/lesson/{b.sessionId}?from=home"
									onclick={hapticTap}
								>
									<span class="btime">{b.time}</span>
									<span class="bname">{b.name}</span>
								</a>
							{/if}
						{/each}

						{#if nowTop !== null}
							<div class="nowline" style="top: {nowTop}px" aria-hidden="true">
								<span class="nowrule"></span>
								<span class="nowdot"></span>
								<span class="nowlabel">{nowLabel}</span>
							</div>
						{/if}
					</div>
				</div>
			{/if}
		{:else if loadError}
			<div class="head">
				<p class="none">
					No se pudieron cargar las clases.
					<Button variant="secondary" onclick={() => load()}>Reintentar</Button>
				</p>
			</div>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	.screen {
		display: flex;
		flex-direction: column;
		height: 100dvh;
		overflow: hidden;
	}

	.head {
		flex-shrink: 0;
		padding: 18px var(--mw-space-5) 0;
	}

	.titlerow {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--mw-space-3);
		padding-bottom: 14px;
	}

	.date {
		margin: 0;
		font-size: var(--mw-type-title-size);
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.1;
	}

	.sum {
		margin: 10px 0 var(--mw-space-4);
		font-size: var(--mw-type-label-size);
		font-family: var(--mw-font-sans);
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
	}

	.strip {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--mw-space-1);
		padding: 2px 0 var(--mw-space-3);
		border-bottom: 1px solid var(--mw-line);
	}

	.day {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		width: 46px;
		padding: var(--mw-space-1) 0;
	}

	.dow {
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.06em;
		color: var(--mw-ink-muted);
	}

	.dow.on {
		color: var(--mw-ink);
	}

	.num {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border-radius: var(--mw-radius-md);
		font-size: var(--mw-type-heading-size);
		font-weight: 600;
		line-height: 1;
		color: var(--mw-ink-muted);
	}

	.num.on {
		background: var(--mw-accent);
		color: var(--mw-on-accent);
		font-weight: 700;
		box-shadow: var(--mw-shadow-card);
	}

	.num.ring {
		border: 1px solid var(--mw-accent);
		color: var(--mw-ink);
	}

	.dot {
		width: 4px;
		height: 4px;
		border-radius: 50%;
		background: transparent;
	}

	.dot.has {
		background: var(--mw-ink-muted);
	}

	.dot.has.on {
		background: var(--mw-accent);
	}

	.grid {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 14px 18px var(--mw-space-6);
	}

	.grid::-webkit-scrollbar {
		width: 0;
	}

	.canvas {
		position: relative;
	}

	.hline {
		position: absolute;
		left: 50px;
		right: 0;
		height: 0;
		border-top: 1px solid var(--mw-line);
	}

	.hlabel {
		position: absolute;
		left: 0;
		width: 34px;
		text-align: right;
		font-size: var(--mw-type-label-size);
		line-height: 1.4;
		font-family: var(--mw-font-sans);
		color: var(--mw-ink-secondary);
	}

	.box {
		position: absolute;
		left: 50px;
		right: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
		justify-content: center;
		padding: 6px var(--mw-space-3);
		border-radius: var(--mw-radius-lg);
		background: var(--mw-surface-tint);
		border: 1px solid var(--mw-line);
		overflow: hidden;
		color: inherit;
	}

	.box.live {
		background: var(--mw-accent);
		border-color: transparent;
		box-shadow: var(--mw-shadow-card);
	}

	.box.live .bname {
		color: var(--mw-on-accent);
	}

	.box.live .btime {
		color: var(--mw-on-accent);
	}

	.box.done,
	.box.off {
		background: var(--mw-surface-card);
		border-color: var(--mw-line);
	}

	.btime {
		display: block;
		font-size: var(--mw-type-label-size);
		line-height: 1.2;
		font-family: var(--mw-font-sans);
		letter-spacing: 0.02em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		color: var(--mw-accent);
	}

	.bname {
		display: block;
		font-size: var(--mw-type-body-size);
		font-weight: 700;
		letter-spacing: -0.01em;
		line-height: 1.15;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.box.done .bname,
	.box.off .bname {
		color: var(--mw-ink-secondary);
		font-weight: 600;
	}

	.box.done .btime,
	.box.off .btime {
		color: var(--mw-ink-muted);
	}

	.nowline {
		position: absolute;
		left: 0;
		right: 0;
		height: 0;
		z-index: var(--mw-z-overlay);
	}

	.nowrule {
		position: absolute;
		left: 50px;
		right: 0;
		top: 0;
		height: 1px;
		background: var(--mw-accent);
	}

	.nowdot {
		position: absolute;
		left: 47px;
		top: -3px;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--mw-accent);
	}

	.nowlabel {
		position: absolute;
		left: 0;
		top: -7px;
		width: 34px;
		text-align: right;
		font-size: var(--mw-type-label-size);
		line-height: 1.4;
		font-family: var(--mw-font-sans);
		color: var(--mw-ink);
		background: var(--mw-surface-card);
	}

	.none {
		margin: var(--mw-space-2) 0 0;
		font-size: var(--mw-type-heading-size);
		color: var(--mw-ink-secondary);
	}
</style>
