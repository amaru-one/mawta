package handlers

import (
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5"

	"yanai-server/internal/repo"
)

// RetentionSweep is a non-destructive stub: it counts records past their
// retention date and logs the count. Actual anonymisation runs through
// privacy.deletion_requests, out of scope for this stage.
func RetentionSweep(ctx context.Context, tx pgx.Tx, _ []byte) error {
	var studentsDue, voiceNotesDue int
	if err := tx.QueryRow(ctx, `
		select count(*) from students
		 where retention_until is not null and retention_until <= current_date
		   and anonymized_at is null and deleted_at is null
	`).Scan(&studentsDue); err != nil {
		return err
	}
	if err := tx.QueryRow(ctx, `
		select count(*) from voice_notes
		 where retention_until is not null and retention_until <= current_date
		   and purged_at is null and deleted_at is null
	`).Scan(&voiceNotesDue); err != nil {
		return err
	}

	payload, _ := json.Marshal(map[string]any{"students_due": studentsDue, "voice_notes_due": voiceNotesDue})
	return repo.LogJobEvent(ctx, tx, "retention.sweep_report", "tenant", nil, nil, nil, payload)
}
