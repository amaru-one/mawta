<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import { addNote, removeNote, saveNote, setAttendance, setFlag } from '$lib/lesson';
	import { currentCourse, notes } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Attendance, Entry, Note, Student } from '$lib/types';
	import AttendanceControl from './AttendanceControl.svelte';
	import FlagButton from './FlagButton.svelte';
	import MicButton from './MicButton.svelte';
	import VoiceNotePlayer from './VoiceNotePlayer.svelte';

	interface Props {
		entry: Entry;
		student: Student;
	}

	let { entry, student }: Props = $props();

	let recordingNow = $state(false);
	let flash = $state(false);

	const rowNotes = $derived($notes.get(entry.id) ?? []);
	const isAbsent = $derived(entry.attendance === 'absent');

	const gradesHref = $derived(
		`/grades/${student.id}?class=${$currentCourse?.id ?? ''}` +
			`&name=${encodeURIComponent(`${student.firstName} ${student.lastName}`)}` +
			`&course=${encodeURIComponent($currentCourse?.name ?? '')}`
	);

	function flashRow(): void {
		flash = true;
		setTimeout(() => (flash = false), 250);
	}

	function handleAttendance(value: Attendance): void {
		hapticTap();
		setAttendance(student.id, value);
		flashRow();
		showToast(value === 'present' ? 'Marcado presente' : 'Marcado ausente');
	}

	function handleFlag(value: boolean): void {
		hapticTap();
		setFlag(student.id, value);
		showToast(value ? 'Alumno marcado' : 'Marca retirada');
	}

	function handleRecorded(blob: Blob, durationSec: number): void {
		void addNote(student.id, blob, durationSec);
		showToast('Nota guardada');
	}

	function handleDelete(note: Note): void {
		removeNote(note);
		showToast('Nota eliminada');
	}

	function handleSave(note: Note): void {
		hapticTap();
		saveNote(note);
		showToast('Nota guardada');
	}
</script>

<div class="card student" class:absent={isAbsent} class:recording={recordingNow} class:flash>
	<div class="row head">
		<a class="name" href={gradesHref} onclick={hapticTap}>
			{student.firstName}
			{student.lastName}
		</a>
		<AttendanceControl value={entry.attendance} onchange={handleAttendance} />
	</div>

	<div class="row controls">
		<FlagButton flagged={entry.flagged} onchange={handleFlag} />
		<MicButton
			hasNotes={rowNotes.length > 0}
			onrecorded={handleRecorded}
			onrecordingchange={(r) => (recordingNow = r)}
			disabled={!entry.attendance}
		/>
	</div>

	{#if rowNotes.length > 0}
		<div class="notes">
			{#each rowNotes as note (note.id)}
				<VoiceNotePlayer {note} ondelete={handleDelete} onsave={handleSave} />
			{/each}
		</div>
	{/if}
</div>

<style>
	.student {
		padding: 14px var(--space-lg);
		transition:
			background-color 150ms ease-out,
			box-shadow 150ms ease-out;
	}

	.student.absent {
		background: var(--bg-danger);
	}

	.student.recording {
		border-color: var(--border-strong);
	}

	.student.flash {
		box-shadow: var(--shadow-accent);
	}

	.head {
		justify-content: space-between;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.name {
		font-size: 15px;
		font-weight: 500;
		color: inherit;
		text-decoration: none;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.absent .name {
		color: var(--text-secondary);
	}

	.controls {
		gap: 14px;
	}

	.notes {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		margin-top: 10px;
	}
</style>
