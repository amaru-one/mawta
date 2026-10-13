<script lang="ts">
	import { tick, untrack } from 'svelte';
	import Icon from './Icon.svelte';
	import {
		addDays,
		compareYearMonth,
		dayLabel,
		monthGrid,
		monthTitle,
		parseISO,
		shiftMonth,
		toISO,
		WEEKDAY_INITIALS,
		yearMonthOf,
		type DayKind,
		type YearMonth,
	} from '$lib/calendar';

	let {
		min,
		max,
		start = null,
		end = null,
		kindOf,
		canStart,
		canEnd,
		onpick,
	}: {
		min: string;
		max: string;
		start?: string | null;
		end?: string | null;
		kindOf: (date: string) => DayKind;
		canStart: (date: string) => boolean;
		canEnd: (date: string) => boolean;
		onpick: (date: string) => void;
	} = $props();

	const REASON: Record<DayKind, string> = {
		free: 'no puede ser inicio ni fin',
		busy: 'ocupado por otra experiencia',
		holiday: 'feriado',
		vacation: 'vacaciones',
		management: 'día de gestión',
		noclass: 'sin clase',
	};

	// Start from the chosen start's month, or the term's first month.
	// Seeded once from the props; afterwards the calendar owns its month and focus.
	let shown = $state<YearMonth>(untrack(() => yearMonthOf(start ?? min)));
	let focus = $state(untrack(() => start ?? min));
	let root: HTMLDivElement | undefined = $state();

	const minYM = $derived(yearMonthOf(min));
	const maxYM = $derived(yearMonthOf(max));
	const canPrev = $derived(compareYearMonth(shown, minYM) > 0);
	const canNext = $derived(compareYearMonth(shown, maxYM) < 0);
	const weeks = $derived(monthGrid(shown));

	const inTerm = (date: string): boolean => date >= min && date <= max;
	const actionable = (date: string): boolean => canStart(date) || canEnd(date);

	function labelFor(date: string, kind: DayKind): string {
		const name = dayLabel(date);
		if (date === start) return `${name}, inicio`;
		if (date === end) return `${name}, fin`;
		if (actionable(date)) return `${name}, disponible`;
		return `${name}, ${REASON[kind]}`;
	}

	function show(next: YearMonth): void {
		shown = next;
	}

	function move(target: string): void {
		const clamped = target < min ? min : target > max ? max : target;
		focus = clamped;
		shown = yearMonthOf(clamped);
	}

	async function moveFocus(target: string): Promise<void> {
		move(target);
		await tick();
		root?.querySelector<HTMLButtonElement>(`[data-date="${focus}"]`)?.focus();
	}

	function onKey(event: KeyboardEvent): void {
		const keys: Record<string, () => string> = {
			ArrowLeft: () => addDays(focus, -1),
			ArrowRight: () => addDays(focus, 1),
			ArrowUp: () => addDays(focus, -7),
			ArrowDown: () => addDays(focus, 7),
			PageUp: () => monthStep(-1),
			PageDown: () => monthStep(1),
		};
		const pick = keys[event.key];
		if (!pick) return;
		event.preventDefault();
		void moveFocus(pick());
	}

	// Same weekday-of-month a month away, clamped to that month's last day.
	function monthStep(delta: number): string {
		const day = parseISO(focus).getDate();
		const target = shiftMonth(yearMonthOf(focus), delta);
		const last = new Date(target.year, target.month + 1, 0).getDate();
		return toISO(new Date(target.year, target.month, Math.min(day, last)));
	}

	function prevMonth(): void {
		const next = shiftMonth(shown, -1);
		show(next);
		focus = clampToMonth(focus, next);
	}

	function nextMonth(): void {
		const next = shiftMonth(shown, 1);
		show(next);
		focus = clampToMonth(focus, next);
	}

	// Keeps the focused day inside the month shown, staying within the term.
	function clampToMonth(date: string, ym: YearMonth): string {
		if (yearMonthOf(date).year === ym.year && yearMonthOf(date).month === ym.month) return date;
		const first = toISO(new Date(ym.year, ym.month, 1));
		const last = toISO(new Date(ym.year, ym.month + 1, 0));
		const candidate = date < first ? first : last;
		return candidate < min ? min : candidate > max ? max : candidate;
	}
</script>

<div class="cal" bind:this={root}>
	<div class="head">
		<button
			type="button"
			class="nav"
			aria-label="Mes anterior"
			disabled={!canPrev}
			onclick={prevMonth}
		>
			<Icon name="chevron-left" size={18} />
		</button>
		<p class="title" aria-live="polite">{monthTitle(shown)}</p>
		<button
			type="button"
			class="nav"
			aria-label="Mes siguiente"
			disabled={!canNext}
			onclick={nextMonth}
		>
			<Icon name="chevron-right" size={18} />
		</button>
	</div>

	<div class="weekdays" aria-hidden="true">
		{#each WEEKDAY_INITIALS as initial, index (index)}<span>{initial}</span>{/each}
	</div>

	{#each weeks as week, weekIndex (weekIndex)}
		<div class="week" role="group">
			{#each week as date, dayIndex (dayIndex)}
				{#if date === null || !inTerm(date)}
					<span class="pad" aria-hidden="true"></span>
				{:else}
					{@const kind = kindOf(date)}
					{@const picked = date === start || date === end}
					{@const selectable = actionable(date)}
					<button
						type="button"
						class="day {kind}"
						class:start={date === start}
						class:end={date === end}
						class:between={start !== null && end !== null && date > start && date < end}
						class:off={!selectable && !picked}
						data-date={date}
						tabindex={date === focus ? 0 : -1}
						aria-disabled={selectable || picked ? undefined : 'true'}
						aria-current={date === start ? 'date' : undefined}
						aria-label={labelFor(date, kind)}
						onfocus={() => (focus = date)}
						onkeydown={onKey}
						onclick={() => {
							if (selectable) onpick(date);
						}}
					>
						<span class="num">{Number(date.slice(8))}</span>
						{#if kind !== 'free' && kind !== 'noclass' && kind !== 'busy'}
							<i class="mark" aria-hidden="true"></i>
						{/if}
					</button>
				{/if}
			{/each}
		</div>
	{/each}

	<ul class="legend" aria-label="Leyenda">
		<li><span class="sw sw-edge"></span>Inicio y fin</li>
		<li><span class="sw sw-between"></span>Dentro del rango</li>
		<li><span class="sw sw-busy"></span>Ocupado</li>
		<li><span class="sw sw-mark"></span>Feriado o vacaciones</li>
	</ul>
</div>

<style>
	.cal {
		display: grid;
		gap: var(--mw-space-2);
		min-width: 0;
	}

	.head {
		display: grid;
		grid-template-columns: var(--mw-touch-target) 1fr var(--mw-touch-target);
		align-items: center;
	}

	.title {
		margin: 0;
		text-align: center;
		text-transform: capitalize;
		font-weight: 700;
		font-size: var(--mw-type-body-size);
	}

	.nav {
		display: grid;
		place-items: center;
		min-height: var(--mw-touch-target);
		min-width: var(--mw-touch-target);
		border: 0;
		border-radius: var(--mw-radius-full);
		background: transparent;
		color: var(--mw-ink-secondary);
	}

	.nav:disabled {
		opacity: 0.35;
	}

	.weekdays,
	.week {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
		gap: 2px;
	}

	.weekdays span {
		text-align: center;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
	}

	.pad {
		min-height: var(--mw-touch-target);
	}

	.day {
		position: relative;
		display: grid;
		place-items: center;
		min-height: var(--mw-touch-target);
		min-width: 0;
		border: 1px solid transparent;
		border-radius: var(--mw-radius-md);
		background: var(--mw-surface-card);
		color: var(--mw-ink);
		font-size: var(--mw-type-small-size);
		font-weight: 600;
	}

	.day.between {
		background: var(--mw-surface-tint);
		border-radius: 0;
	}

	.day.start,
	.day.end {
		background: var(--mw-accent);
		color: var(--mw-on-accent);
	}

	.day.off {
		color: var(--mw-ink-muted);
		font-weight: 500;
	}

	.day.busy {
		background: repeating-linear-gradient(45deg, var(--mw-line) 0 4px, transparent 4px 8px);
	}

	.day.noclass {
		color: var(--mw-ink-muted);
		opacity: 0.6;
	}

	.day[aria-disabled='true'] {
		cursor: not-allowed;
	}

	.mark {
		position: absolute;
		bottom: 5px;
		left: 50%;
		width: 4px;
		height: 4px;
		margin-left: -2px;
		border-radius: 50%;
		background: var(--mw-danger);
	}

	.day:focus-visible {
		outline: 2px solid var(--mw-focus-ring);
		outline-offset: 2px;
	}

	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--mw-space-2) var(--mw-space-3);
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}

	.legend li {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.sw {
		width: 12px;
		height: 12px;
		border-radius: 3px;
	}

	.sw-edge {
		background: var(--mw-accent);
	}

	.sw-between {
		background: var(--mw-surface-tint);
	}

	.sw-busy {
		background: repeating-linear-gradient(45deg, var(--mw-line) 0 3px, transparent 3px 6px);
	}

	.sw-mark {
		border-radius: 50%;
		width: 6px;
		height: 6px;
		background: var(--mw-danger);
	}
</style>
