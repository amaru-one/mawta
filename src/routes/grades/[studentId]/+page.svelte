<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import AiSummaryCard from '$lib/components/AiSummaryCard.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { gradeFor, loadScoresForStudent, saveScore } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';
	import { loadToday } from '$lib/lesson';
	import { VOICE_NOTE_SUMMARY } from '$lib/mocks';
	import { assessments, currentCourse, scores, students } from '$lib/stores';
	import { showToast } from '$lib/toast';

	let ready = $state(false);

	onMount(() => {
		const studentId = page.params.studentId;
		void Promise.all([
			loadToday(),
			studentId ? loadScoresForStudent(studentId) : Promise.resolve()
		]).then(() => {
			ready = true;
		});
	});

	const student = $derived($students.find((s) => s.id === page.params.studentId) ?? null);
	const grade = $derived(student ? gradeFor(student.id, $scores, $assessments) : null);

	// How much of the course has actually been marked, vs. still placeholder.
	const evaluated = $derived.by(() => {
		if (!grade) return { percent: 0, remaining: 100 };
		const total = grade.components.reduce((sum, c) => sum + c.component.weight, 0);
		const done = grade.components
			.filter((c) => c.scored)
			.reduce((sum, c) => sum + c.component.weight, 0);
		const percent = total > 0 ? Math.round((done / total) * 100) : 0;
		return { percent, remaining: 100 - percent };
	});

	// Best and worst final outcomes if every unscored component came in at 100 / 0.
	const range = $derived.by(() => {
		if (!grade) return null;
		const total = grade.components.reduce((sum, c) => sum + c.component.weight, 0);
		if (total === 0) return null;
		const locked = grade.components
			.filter((c) => c.scored)
			.reduce((sum, c) => sum + c.score * c.component.weight, 0);
		const openWeight = grade.components
			.filter((c) => !c.scored)
			.reduce((sum, c) => sum + c.component.weight, 0);
		return {
			min: Math.round(locked / total),
			max: Math.round((locked + openWeight * 100) / total)
		};
	});

	function handleScoreChange(componentId: string, maxValue: number, e: Event): void {
		if (!student) return;
		const target = e.currentTarget as HTMLInputElement;
		const parsed = Number(target.value);
		if (!Number.isFinite(parsed)) return;
		const clamped = Math.min(maxValue, Math.max(0, Math.round(parsed)));
		target.value = String(clamped);
		hapticTap();
		saveScore(student.id, componentId, clamped);
		showToast('Nota guardada');
	}
</script>

<svelte:head>
	<title>{student ? `${student.firstName} ${student.lastName}` : 'Alumno'}</title>
</svelte:head>

<TopBar back="/" />

<div class="body">
	{#if ready}
		{#if student && grade}
			<p class="title">{student.firstName} {student.lastName}</p>
			<p class="subtitle">{$currentCourse?.name ?? ''} · Bimestre II</p>

			<div class="result">
				<p class="result-label">RESULTADO PARCIAL</p>
				<div class="result-head">
					<span class="tier">{grade.tier}</span>
					<span class="pct">{grade.percent}% de lo evaluado</span>
				</div>
				<div class="progress">
					<div class="progress-fill" style="width:{evaluated.percent}%"></div>
				</div>
				<p class="result-foot">
					{evaluated.percent}% del curso evaluado · falta {evaluated.remaining}%
				</p>
			</div>

			{#if range}
				<div class="range">
					<p class="range-label">Rango posible al cierre</p>
					<div class="row">
						<span class="range-min">{range.min}%</span>
						<div class="range-track"></div>
						<span class="range-max">{range.max}%</span>
					</div>
					<p class="range-note">Según cómo rinda en lo que falta</p>
				</div>
			{/if}

			<p class="eyebrow">EVALUACIONES</p>

			<div class="stack">
				{#each grade.components as c (c.component.id)}
					<div class="card row component" class:unscored={!c.scored}>
						<div class="grow">
							<p class="component-name">{c.component.label}</p>
							<p class="component-weight">Peso {c.component.weight}%</p>
						</div>
						<span class="input-wrap">
							<input
								type="number"
								class="score-input"
								min="0"
								max={c.maxValue}
								value={c.rawValue}
								onchange={(e) => handleScoreChange(c.component.id, c.maxValue, e)}
								aria-label={`Nota de ${c.component.label}, sobre ${c.maxValue}`}
							/>
							<span class="max">/ {c.maxValue}</span>
						</span>
						<span class="score">{c.score}%</span>
					</div>
				{/each}
			</div>

			<button class="btn-block ai pressable" onclick={() => showToast('Resumen aún no disponible')}>
				<Icon name="sparkles" size={16} />Generar resumen
			</button>
			<button
				class="btn-block secondary pressable"
				onclick={() => showToast('Añadir evaluación aún no disponible')}
			>
				<Icon name="plus" size={16} />Añadir evaluación
			</button>

			<AiSummaryCard
				title="Resumen de {VOICE_NOTE_SUMMARY.noteCount} notas de voz"
				bullets={VOICE_NOTE_SUMMARY.bullets}
			/>
		{:else}
			<p class="empty">Alumno no encontrado.</p>
		{/if}
	{/if}
</div>

<style>
	.title {
		margin: 0;
		font-weight: 500;
		font-size: 20px;
	}

	.subtitle {
		margin: 2px 0 var(--space-lg);
		font-size: 13px;
		color: var(--text-secondary);
	}

	.result {
		background: var(--text-primary);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.result-label {
		margin: 0 0 var(--space-sm);
		font-size: 10px;
		letter-spacing: 0.05em;
		color: var(--surface-1);
		font-family: var(--font-mono);
	}

	.result-head {
		display: flex;
		align-items: baseline;
		gap: 10px;
	}

	.tier {
		font-size: 26px;
		font-weight: 600;
		color: var(--surface-2);
	}

	.pct {
		font-size: 15px;
		color: var(--surface-1);
	}

	.progress {
		width: 100%;
		height: 6px;
		border-radius: var(--radius-sm);
		overflow: hidden;
		margin: 14px 0 var(--space-sm);
		background: rgba(255, 255, 255, 0.2);
	}

	.progress-fill {
		height: 100%;
		background: var(--surface-2);
	}

	.result-foot {
		margin: 0;
		font-size: 12px;
		color: var(--surface-1);
	}

	.range {
		background: var(--surface-1);
		border-radius: var(--radius);
		padding: var(--space-md) 14px;
		margin-bottom: 20px;
	}

	.range-label {
		margin: 0 0 6px;
		font-size: 11px;
		color: var(--text-secondary);
	}

	.range .row {
		gap: var(--space-sm);
	}

	.range-min,
	.range-max {
		font-size: 15px;
		font-weight: 500;
	}

	.range-min {
		color: var(--text-danger);
	}

	.range-max {
		color: var(--text-success);
	}

	.range-track {
		flex: 1;
		height: 4px;
		border-radius: 2px;
		background: linear-gradient(to right, var(--border-strong), var(--fill-accent));
	}

	.range-note {
		margin: 6px 0 0;
		font-size: 11px;
		color: var(--text-muted);
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-bottom: 20px;
	}

	.component {
		padding: var(--space-md) 14px;
		gap: 10px;
	}

	.component.unscored {
		border-style: dashed;
		border-color: var(--border-strong);
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.component-name {
		margin: 0;
		font-size: 14px;
	}

	.component.unscored .component-name {
		color: var(--text-muted);
	}

	.component-weight {
		margin: 0;
		font-size: 11px;
		color: var(--text-muted);
	}

	.input-wrap {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.score-input {
		width: 52px;
		font-size: 13px;
		font-weight: 500;
		color: var(--text-primary);
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: var(--space-xs) 6px;
		text-align: right;
	}

	.score-input:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.max {
		font-size: 13px;
		color: var(--text-secondary);
	}

	.score {
		font-size: 13px;
		font-weight: 500;
		min-width: 40px;
		text-align: right;
	}

	/* Assistant action — carries the accent. */
	.ai {
		background: var(--fill-accent);
		color: var(--on-accent);
		margin-bottom: var(--space-sm);
	}

	.secondary {
		background: var(--surface-2);
		color: var(--text-primary);
		border: 0.5px solid var(--border-strong);
		margin-bottom: 20px;
	}

	.empty {
		font-size: 14px;
		color: var(--text-secondary);
	}
</style>
