package repo

import (
	"context"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
)

// Voice-note attribution (voice_notes.attribution_status).
const (
	AttributionPending    = "pending"
	AttributionOK         = "ok"
	AttributionDiscarded  = "discarded"
	AttributionConfirmed  = "confirmed"
	AttributionReassigned = "reassigned"
)

// Why a voice note was discarded (voice_notes.discard_reason).
const (
	DiscardMentionsOtherStudent = "mentions_other_student"
	DiscardUnreadable           = "unreadable"
)

// Who a redacted fragment refers to (voice_note_redactions.refers_to).
const (
	RefersToAssignedStudent = "assigned_student"
	RefersToClassmate       = "classmate"
	RefersToOtherPerson     = "other_person"
)

// VoiceNoteForRedaction is what the redaction sweep reads of a voice note.
type VoiceNoteForRedaction struct {
	ID                uuid.UUID
	StudentID         uuid.UUID
	ClassID           uuid.UUID
	TeacherID         uuid.UUID
	RecordedAt        time.Time
	Transcript        *string
	AttributionStatus string
}

// GetVoiceNoteForRedaction reads a live voice note; a discarded (deleted)
// note is pgx.ErrNoRows.
func GetVoiceNoteForRedaction(ctx context.Context, tx pgx.Tx, id uuid.UUID) (VoiceNoteForRedaction, error) {
	var v VoiceNoteForRedaction
	err := tx.QueryRow(ctx, `
		select id, student_id, class_id, teacher_id, recorded_at, transcript, attribution_status
		  from voice_notes where id = $1 and deleted_at is null
	`, id).Scan(&v.ID, &v.StudentID, &v.ClassID, &v.TeacherID, &v.RecordedAt, &v.Transcript, &v.AttributionStatus)
	return v, err
}

// StudentName is a student's names as the school recorded them.
type StudentName struct {
	ID              uuid.UUID
	GivenName       string
	PreferredName   *string
	PaternalSurname string
	MaternalSurname *string
}

// StudentNames reads the names of the given students, ordered by surname.
func StudentNames(ctx context.Context, tx pgx.Tx, ids []uuid.UUID) ([]StudentName, error) {
	rows, err := tx.Query(ctx, `
		select id, given_name, preferred_name, paternal_surname, maternal_surname
		  from students where id = any($1) and deleted_at is null
		 order by paternal_surname, maternal_surname, given_name, id
	`, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []StudentName
	for rows.Next() {
		var s StudentName
		if err := rows.Scan(&s.ID, &s.GivenName, &s.PreferredName, &s.PaternalSurname, &s.MaternalSurname); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// VoiceNoteRedaction is one replacement the sweep made in a transcript.
type VoiceNoteRedaction struct {
	VoiceNoteID      uuid.UUID
	GenerationID     uuid.UUID
	StudentID        uuid.UUID
	OriginalText     string
	StartOffset      int
	EndOffset        int
	Replacement      string
	RefersTo         string
	MatchedStudentID *uuid.UUID
}

// SupersedeVoiceNoteRedactions closes the live redaction rows of a note,
// before a new sweep writes its own.
func SupersedeVoiceNoteRedactions(ctx context.Context, tx pgx.Tx, voiceNoteID uuid.UUID) error {
	_, err := tx.Exec(ctx, `
		update voice_note_redactions set superseded_at = now()
		 where voice_note_id = $1 and superseded_at is null
	`, voiceNoteID)
	return err
}

// InsertVoiceNoteRedaction records one replacement (method model).
func InsertVoiceNoteRedaction(ctx context.Context, tx pgx.Tx, r VoiceNoteRedaction) error {
	_, err := tx.Exec(ctx, `
		insert into voice_note_redactions
		  (tenant_id, voice_note_id, generation_id, student_id, original_text,
		   start_offset, end_offset, replacement, refers_to, matched_student_id, method)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, 'model')
	`, r.VoiceNoteID, r.GenerationID, r.StudentID, r.OriginalText, r.StartOffset, r.EndOffset,
		r.Replacement, r.RefersTo, r.MatchedStudentID)
	return err
}

// SetVoiceNoteAttribution records the outcome of a sweep or of a teacher's
// decision: the redacted transcript (nil keeps none), the status and, for a
// discarded note, why.
func SetVoiceNoteAttribution(ctx context.Context, tx pgx.Tx, id uuid.UUID, redacted *string, status string, reason *string) error {
	ct, err := tx.Exec(ctx, `
		update voice_notes
		   set transcript_redacted = $2, attribution_status = $3, discard_reason = $4,
		       attribution_checked_at = now()
		 where id = $1 and deleted_at is null
	`, id, redacted, status, reason)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return pgx.ErrNoRows
	}
	return nil
}

// ReassignVoiceNote moves a note to another student and sends it back to
// pending: its redacted transcript was built around the previous student, so
// it is cleared and the sweep runs again.
func ReassignVoiceNote(ctx context.Context, tx pgx.Tx, id, studentID uuid.UUID) error {
	if err := SupersedeVoiceNoteRedactions(ctx, tx, id); err != nil {
		return err
	}
	ct, err := tx.Exec(ctx, `
		update voice_notes
		   set student_id = $2, transcript_redacted = null, attribution_status = 'pending',
		       discard_reason = null, attribution_checked_at = now()
		 where id = $1 and deleted_at is null
	`, id, studentID)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return pgx.ErrNoRows
	}
	return nil
}

// PendingVoiceNotesForStudentTerm lists the notes of a student in a class and
// term that the sweep has not processed yet: transcribed but still pending.
// Used to queue the sweep lazily for notes recorded before it existed.
func PendingVoiceNotesForStudentTerm(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) ([]uuid.UUID, error) {
	rows, err := tx.Query(ctx, `
		select vn.id
		  from voice_notes vn
		  join class_sessions cs on cs.id = vn.session_id
		 where vn.class_id = $1 and vn.student_id = $2 and cs.term_id = $3
		   and vn.deleted_at is null
		   and vn.transcription_status = 'completed'
		   and vn.attribution_status = 'pending'
	`, classID, studentID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

// ConfirmVoiceNote records that a teacher kept a note the sweep discarded for
// naming other students. Anything else cannot be confirmed: a note still
// pending has not been swept, an unreadable one has nothing to use, and a
// usable one needs no confirmation.
func ConfirmVoiceNote(ctx context.Context, tx pgx.Tx, id uuid.UUID) error {
	ct, err := tx.Exec(ctx, `
		update voice_notes
		   set attribution_status = 'confirmed', discard_reason = null, attribution_checked_at = now()
		 where id = $1 and deleted_at is null
		   and attribution_status = 'discarded' and discard_reason = 'mentions_other_student'
		   and transcript_redacted is not null
	`, id)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return db.NewAppError(http.StatusUnprocessableEntity, "not_confirmable",
			"Esta nota no se puede confirmar: solo las descartadas por nombrar a otros estudiantes.")
	}
	return nil
}

// CurrentTenantID is the tenant the transaction runs as (app.tenant_id).
func CurrentTenantID(ctx context.Context, tx pgx.Tx) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `select app.current_tenant_id()`).Scan(&id)
	return id, err
}
