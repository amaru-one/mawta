<script lang="ts">
	import { scale } from 'svelte/transition';
	import type { AssessmentKind, PracticeScoreCreateDto } from '$lib/api/dto';

	interface Props {
		onsubmit: (data: PracticeScoreCreateDto) => void;
		oncancel: () => void;
	}

	let { onsubmit, oncancel }: Props = $props();

	const kindOptions: { value: AssessmentKind; label: string }[] = [
		{ value: 'quiz', label: 'Quiz' },
		{ value: 'examen', label: 'Examen' },
		{ value: 'practica', label: 'Práctica' },
		{ value: 'tarea', label: 'Tarea' },
		{ value: 'proyecto', label: 'Proyecto' },
		{ value: 'exposicion', label: 'Exposición' },
		{ value: 'participacion', label: 'Participación' },
		{ value: 'rubrica', label: 'Rúbrica' },
		{ value: 'otro', label: 'Otro' },
	];

	let title = $state('');
	let kind = $state<AssessmentKind>('otro');
	let rawValue = $state('');
	let maxValue = $state('10');
	let note = $state('');

	const titleId = `add-practice-score-${Math.random().toString(36).slice(2, 8)}`;

	const canSubmit = $derived(
		title.trim() !== '' && Number.isFinite(Number(rawValue)) && Number(maxValue) > 0
	);

	function handleSubmit(e: Event): void {
		e.preventDefault();
		if (!canSubmit) return;
		onsubmit({
			title: title.trim(),
			kind,
			raw_value: Number(rawValue),
			max_value: Number(maxValue),
			note: note.trim() === '' ? null : note.trim(),
		});
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && oncancel()} />

<div
	class="dialog"
	in:scale={{ start: 0.95, duration: 150 }}
	out:scale={{ start: 0.95, duration: 150 }}
	role="dialog"
	aria-modal="true"
	aria-labelledby={titleId}
>
	<button class="backdrop" onclick={oncancel} aria-label="Cerrar diálogo" tabindex="-1"></button>
	<form class="content" onsubmit={handleSubmit}>
		<p class="title" id={titleId}>Añadir evaluación</p>
		<p class="hint">Se guarda como nota personal — no afecta el promedio oficial.</p>

		<label class="field">
			<span>Título</span>
			<input type="text" bind:value={title} placeholder="Quiz práctica 3" required />
		</label>

		<label class="field">
			<span>Tipo</span>
			<select bind:value={kind}>
				{#each kindOptions as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
		</label>

		<div class="row-fields">
			<label class="field score">
				<span>Nota</span>
				<input type="number" bind:value={rawValue} step="0.01" required />
			</label>
			<span class="slash">/</span>
			<label class="field score">
				<span>Sobre</span>
				<input type="number" bind:value={maxValue} step="0.01" min="0.01" required />
			</label>
		</div>

		<label class="field">
			<span>Nota interna (opcional)</span>
			<textarea bind:value={note} rows="2" placeholder="Comentario para ti mismo"></textarea>
		</label>

		<div class="actions">
			<button type="button" class="cancel pressable" onclick={oncancel}>Cancelar</button>
			<button type="submit" class="confirm pressable" disabled={!canSubmit}>Guardar</button>
		</div>
	</form>
</div>

<style>
	.dialog {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 2000;
		padding: var(--space-lg);
	}

	.backdrop {
		position: absolute;
		inset: 0;
		background: rgba(22, 24, 58, 0.55);
		border: none;
		cursor: pointer;
	}

	.content {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		background: var(--surface-2);
		border-radius: var(--radius-lg);
		padding: var(--space-xl);
		width: 100%;
		max-width: 360px;
		max-height: 85vh;
		overflow-y: auto;
		box-shadow: var(--shadow-lg);
	}

	.title {
		margin: 0;
		font-size: 16px;
		font-weight: 500;
	}

	.hint {
		margin: -6px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.field input,
	.field select,
	.field textarea {
		font-size: 14px;
		color: var(--text-primary);
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: var(--space-sm) 10px;
		font-family: inherit;
		resize: vertical;
	}

	.field input:focus,
	.field select:focus,
	.field textarea:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.row-fields {
		display: flex;
		align-items: flex-end;
		gap: var(--space-sm);
	}

	.score {
		flex: 1;
	}

	.slash {
		padding-bottom: 10px;
		color: var(--text-muted);
	}

	.actions {
		display: flex;
		gap: var(--space-md);
		justify-content: flex-end;
		margin-top: var(--space-sm);
	}

	.cancel,
	.confirm {
		padding: 10px var(--space-lg);
		min-height: 36px;
		border-radius: var(--radius-md);
		font-size: 14px;
		font-weight: 500;
	}

	.cancel {
		background: var(--surface-1);
		color: var(--text-primary);
	}

	.confirm {
		background: var(--fill-accent);
		color: var(--on-accent);
	}

	.confirm:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
