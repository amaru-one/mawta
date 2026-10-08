<script lang="ts">
	import { Button, ButtonRow, Dialog, Field } from '$lib/design-system';
	import type { AssessmentKind, PracticeScoreCreateDto } from '$lib/api/dto';

	interface Props {
		onsubmit: (data: PracticeScoreCreateDto) => void;
		oncancel: () => void;
	}

	let { onsubmit, oncancel }: Props = $props();

	const kindOptions: { value: AssessmentKind; label: string }[] = [
		{ value: 'examen', label: 'Examen' },
		{ value: 'practica', label: 'Práctica' },
		{ value: 'tarea', label: 'Tarea' },
		{ value: 'proyecto', label: 'Proyecto' },
		{ value: 'exposicion', label: 'Exposición' },
		{ value: 'participacion', label: 'Participación' },
		{ value: 'otro', label: 'Otro' },
	];

	let title = $state('');
	let kind = $state<AssessmentKind>('otro');
	let rawValue = $state<number | undefined>();
	let maxValue = $state<number | undefined>(10);
	let note = $state('');

	let open = $state(true);

	const canSubmit = $derived(
		title.trim() !== '' &&
			rawValue !== undefined &&
			Number.isFinite(rawValue) &&
			Number(maxValue) > 0
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

<Dialog
	bind:open
	title="Añadir evaluación"
	description="Se guarda como nota personal; no afecta el promedio oficial."
	onclose={oncancel}
>
	<form onsubmit={handleSubmit}>
		<Field label="Título" bind:value={title} placeholder="Práctica 3" required />
		<Field label="Tipo" kind="select" bind:value={kind} options={kindOptions} />
		<div class="scores">
			<Field label="Nota" type="number" bind:value={rawValue} step="0.01" required /><Field
				label="Sobre"
				type="number"
				bind:value={maxValue}
				step="0.01"
				min="0.01"
				required
			/>
		</div>
		<Field
			label="Nota interna (opcional)"
			kind="textarea"
			bind:value={note}
			rows={2}
			placeholder="Comentario para ti mismo"
		/>
		<ButtonRow
			><Button onclick={() => (open = false)}>Cancelar</Button><Button
				type="submit"
				variant="primary"
				disabled={!canSubmit}>Guardar</Button
			></ButtonRow
		>
	</form>
</Dialog>

<style>
	form {
		display: grid;
		gap: var(--mw-space-4);
	}
	.scores {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--mw-space-3);
	}
</style>
