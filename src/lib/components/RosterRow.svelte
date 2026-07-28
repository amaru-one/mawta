<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import {
		addNote,
		noteDurations,
		removeNote,
		setAttendance,
		setParticipation,
		setTookAssessment
	} from '$lib/lesson';
	import { notes } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Attendance, Entry, Note, Participation, Student } from '$lib/types';
	import AttendanceControl from './AttendanceControl.svelte';
	import MicButton from './MicButton.svelte';
	import ParticipationControl from './ParticipationControl.svelte';
	import VoiceNotePlayer from './VoiceNotePlayer.svelte';

	interface Props {
		entry: Entry;
		student: Student;
		showAssessment: boolean;
	}

	let { entry, student, showAssessment }: Props = $props();

	let recordingNow = $state(false);
	let flash = $state(false);

	const rowNotes = $derived($notes.get(entry.id) ?? []);
	const isAbsent = $derived(entry.attendance === 'absent');
	const initials = $derived(`${student.firstName[0] ?? ''}${student.lastName[0] ?? ''}`);

	function flashRow(): void {
		flash = true;
		setTimeout(() => (flash = false), 250);
	}

	function handleAttendance(value: Attendance): void {
		hapticTap();
		void setAttendance(student.id, value);
		flashRow();
		showToast(value === 'present' ? 'Marked present' : 'Marked absent');
	}

	function handleParticipation(value: Participation): void {
		hapticTap();
		void setParticipation(student.id, value);
		showToast('Participation updated');
	}

	function handleTook(): void {
		hapticTap();
		void setTookAssessment(student.id, !entry.tookAssessment);
	}

	function handleRecorded(blob: Blob, durationSec: number): void {
		void addNote(student.id, blob, durationSec);
		showToast('Note saved');
	}

	function handleDelete(note: Note): void {
		const undo = removeNote(note);
		showToast('Note deleted', { onUndo: undo.restore });
	}

	function handleSave(note: Note): void {
		hapticTap();
		showToast('Note saved');
	}
</script>

<div
	class="row"
	class:absent={isAbsent}
	class:has-notes={rowNotes.length > 0}
	class:recording={recordingNow}
	class:flash
>
	<div class="main">
		<span class="avatar" style:background={student.avatar ?? 'var(--primary)'}>
			{initials}
		</span>
		<div class="who">
			<span class="name">{student.firstName} {student.lastName}</span>
			{#if rowNotes.length > 0}
				<span class="context">
					{rowNotes.length}
					{rowNotes.length === 1 ? 'note' : 'notes'}{#if rowNotes[0].transcript}
						· {rowNotes[0].transcript.split(' ').slice(0, 4).join(' ')}…{/if}
				</span>
			{/if}
		</div>

		<div class="controls">
			{#if showAssessment}
				<button
					class="took pressable"
					class:on={entry.tookAssessment === true}
					onclick={handleTook}
					aria-pressed={entry.tookAssessment === true}
					aria-label="Took the assessment"
				>
					{entry.tookAssessment ? 'took it ✓' : 'took it?'}
				</button>
			{/if}
			<AttendanceControl value={entry.attendance} onchange={handleAttendance} />
			<ParticipationControl
				value={entry.participation}
				disabled={isAbsent}
				onchange={handleParticipation}
			/>
			<MicButton
				hasNotes={rowNotes.length > 0}
				onrecorded={handleRecorded}
				onrecordingchange={(r) => (recordingNow = r)}
				disabled={!entry.attendance}
			/>
		</div>
	</div>

	{#if rowNotes.length > 0}
		<div class="notes">
			{#each rowNotes as note (note.id)}
				<VoiceNotePlayer
					{note}
					knownDuration={$noteDurations.get(note.id)}
					ondelete={handleDelete}
					onsave={handleSave}
				/>
			{/each}
		</div>
	{/if}
</div>

<style>
	.row {
		background: var(--neutral-50);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-lg);
		border-left: 3px solid transparent;
		transition:
			background-color 150ms ease-out,
			border-color 150ms ease-out,
			box-shadow 150ms ease-out;
	}

	.row:hover {
		box-shadow: var(--shadow-sm);
	}

	.row.has-notes {
		border-left-color: var(--primary-light);
	}

	.row.recording {
		border-left-color: var(--primary);
	}

	.row.absent {
		background: var(--action-delete-light);
		border-left-color: var(--action-delete);
	}

	.row.flash {
		box-shadow: var(--shadow-primary);
	}

	.main {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		min-height: 56px;
	}

	.avatar {
		width: 36px;
		height: 36px;
		min-width: 36px;
		border-radius: 50%;
		color: white;
		font-size: 13px;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		letter-spacing: 0.3px;
	}

	.absent .avatar {
		filter: saturate(0.5);
		opacity: 0.7;
	}

	.who {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}

	.name {
		font-size: 16px;
		font-weight: 500;
		line-height: 24px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.absent .name {
		color: var(--neutral-600);
	}

	.context {
		font-size: 12px;
		line-height: 16px;
		color: var(--neutral-600);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.controls {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-shrink: 0;
	}

	.took {
		font-size: 12px;
		font-weight: 700;
		padding: var(--space-xs) var(--space-sm);
		min-height: 32px;
		border-radius: var(--radius-sm);
		background: var(--neutral-200);
		color: var(--neutral-600);
	}

	.took.on {
		background: var(--primary-light);
		color: var(--primary-dark);
	}

	.notes {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		padding: var(--space-xs) 0 var(--space-sm) calc(36px + var(--space-md));
	}

	@media (max-width: 480px) {
		.row {
			padding: var(--space-sm) var(--space-md);
		}

		.main {
			flex-wrap: wrap;
			row-gap: var(--space-xs);
		}

		.who {
			flex: 1 1 40%;
		}

		.controls {
			gap: var(--space-sm);
			margin-left: auto;
		}

		.notes {
			padding-left: var(--space-sm);
		}
	}

	@media (max-width: 900px) {
		.name {
			font-size: 16px;
		}
	}

	@media (min-width: 901px) {
		.name {
			font-size: 14px;
			line-height: 20px;
		}
	}
</style>
