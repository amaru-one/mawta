<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import type { Tier } from '$lib/grades';
	import { addNote, removeNote, saveNote, setAttendance, setFlag, setParticipation } from '$lib/lesson';
	import { currentCourse, notes } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Attendance, Entry, Note, Participation, Student } from '$lib/types';
	import AttendanceControl from './AttendanceControl.svelte';
	import FlagButton from './FlagButton.svelte';
	import LevelBadge from './LevelBadge.svelte';
	import MicButton from './MicButton.svelte';
	import ParticipationControl from './ParticipationControl.svelte';
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

	const TIERS = ['AD', 'A', 'B', 'C'] as const;
	const tier = $derived(
		TIERS.includes(entry.levelCode as Tier) ? (entry.levelCode as Tier) : null
	);
	const previousTier = $derived(
		entry.trend !== null && entry.trend !== 'flat' ? entry.previousLevelCode : null
	);

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

	function handleParticipation(value: Participation): void {
		hapticTap();
		setParticipation(student.id, value);
		showToast('Participación actualizada');
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
		<div class="row marks">
			{#if previousTier}
				<span class="trend" class:up={entry.trend === 'up'}>{previousTier} →</span>
			{/if}
			{#if tier}
				<LevelBadge {tier} />
			{/if}
			<AttendanceControl value={entry.attendance} onchange={handleAttendance} />
		</div>
	</div>

	<div class="row controls">
		<ParticipationControl
			value={entry.participation}
			disabled={isAbsent}
			onchange={handleParticipation}
		/>
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

	.marks {
		gap: var(--space-sm);
		flex-shrink: 0;
	}

	/* A drop in tier is the plain signal; a rise borrows the accent. */
	.trend {
		font-size: 11px;
		color: var(--text-danger);
	}

	.trend.up {
		color: var(--text-accent);
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
