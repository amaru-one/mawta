package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func CreateVoiceNote(ctx context.Context, tx pgx.Tx, sessionID, studentID, classID, teacherID uuid.UUID, durationMs int32, audio []byte, mimeType *string, byteSize *int64) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id,
		                          duration_ms, audio, mime_type, byte_size,
		                          transcription_status)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8,
		        'pending')
		returning id
	`, sessionID, studentID, classID, teacherID, durationMs, audio, mimeType, byteSize).Scan(&id)
	return id, err
}

type VoiceNoteFile struct {
	Audio      []byte
	StorageKey *string
	MimeType   *string
}

func GetVoiceNoteFile(ctx context.Context, tx pgx.Tx, id uuid.UUID) (VoiceNoteFile, error) {
	var f VoiceNoteFile
	err := tx.QueryRow(ctx, `
		select audio, storage_key, mime_type from voice_notes where id = $1 and deleted_at is null
	`, id).Scan(&f.Audio, &f.StorageKey, &f.MimeType)
	return f, err
}

func VoiceNoteExists(ctx context.Context, tx pgx.Tx, id uuid.UUID) error {
	var exists bool
	err := tx.QueryRow(ctx, `
		select exists (select 1 from voice_notes where id = $1 and deleted_at is null)
	`, id).Scan(&exists)
	if err != nil {
		return err
	}
	if !exists {
		return pgx.ErrNoRows
	}
	return nil
}

func DeleteVoiceNote(ctx context.Context, tx pgx.Tx, id uuid.UUID) error {
	ct, err := tx.Exec(ctx, `
		update voice_notes set deleted_at = now() where id = $1 and deleted_at is null
	`, id)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return pgx.ErrNoRows
	}
	return nil
}

func SetVoiceNoteTranscript(ctx context.Context, tx pgx.Tx, id uuid.UUID, transcript string) error {
	ct, err := tx.Exec(ctx, `
		update voice_notes set transcript = $2, transcription_status = 'completed'
		 where id = $1 and deleted_at is null
	`, id, transcript)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return pgx.ErrNoRows
	}
	return nil
}

func MarkVoiceNoteTranscriptionFailed(ctx context.Context, tx pgx.Tx, id uuid.UUID) error {
	ct, err := tx.Exec(ctx, `
		update voice_notes set transcription_status = 'failed' where id = $1 and deleted_at is null
	`, id)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return pgx.ErrNoRows
	}
	return nil
}
