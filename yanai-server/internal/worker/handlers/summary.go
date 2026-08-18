package handlers

import (
	"context"
	"encoding/json"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/repo"
)

type summaryPayload struct {
	StudentID uuid.UUID  `json:"student_id"`
	ClassID   *uuid.UUID `json:"class_id"`
	TermID    *uuid.UUID `json:"term_id"`
}

type savedNote struct {
	ID         uuid.UUID
	Transcript *string
}

// NoteSummaryGenerate builds a deterministic extractive summary from a
// student's saved voice notes — no AI provider this stage. Bullets are the
// first sentence of each transcript, newest first, capped at 5; notes with
// no transcript contribute one trailing "N sin transcribir" bullet.
func NoteSummaryGenerate(ctx context.Context, tx pgx.Tx, jobID int64, payload []byte) error {
	var p summaryPayload
	if err := json.Unmarshal(payload, &p); err != nil {
		return err
	}

	if _, err := tx.Exec(ctx, `
		update note_summaries set status = 'stale'
		 where student_id = $1 and class_id is not distinct from $2 and term_id is not distinct from $3
		   and status in ('ready','generating') and deleted_at is null
	`, p.StudentID, p.ClassID, p.TermID); err != nil {
		return err
	}

	var summaryID uuid.UUID
	if err := tx.QueryRow(ctx, `
		insert into note_summaries (tenant_id, student_id, class_id, term_id, scope, status)
		values (app.current_tenant_id(), $1, $2, $3, $4, 'generating')
		returning id
	`, p.StudentID, p.ClassID, p.TermID, summaryScope(p)).Scan(&summaryID); err != nil {
		return err
	}

	query := `
		select vn.id, vn.transcript
		  from voice_notes vn
		 where vn.student_id = $1 and vn.status = 'saved' and vn.deleted_at is null`
	args := []any{p.StudentID}
	if p.ClassID != nil {
		query += ` and vn.class_id = $2`
		args = append(args, *p.ClassID)
	}
	query += ` order by vn.recorded_at desc`

	rows, err := tx.Query(ctx, query, args...)
	if err != nil {
		return err
	}
	var notes []savedNote
	for rows.Next() {
		var n savedNote
		if err := rows.Scan(&n.ID, &n.Transcript); err != nil {
			rows.Close()
			return err
		}
		notes = append(notes, n)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}

	if len(notes) == 0 {
		_, err := tx.Exec(ctx, `
			update note_summaries set status = 'failed', error_detail = 'sin notas de voz guardadas', generated_at = now()
			 where id = $1
		`, summaryID)
		return err
	}

	var bullets []string
	untranscribed := 0
	for _, n := range notes {
		if n.Transcript == nil || strings.TrimSpace(*n.Transcript) == "" {
			untranscribed++
			continue
		}
		if len(bullets) < 5 {
			bullets = append(bullets, firstSentence(*n.Transcript))
		}
	}
	if untranscribed > 0 && len(bullets) < 5 {
		bullets = append(bullets, pluralNotesBullet(untranscribed))
	}
	bulletsJSON, _ := json.Marshal(bullets)

	if _, err := tx.Exec(ctx, `
		update note_summaries
		   set bullets = $2, notes_count = $3, model = 'extractive-stub-v1',
		       status = 'ready', generated_at = now(), generated_by_job_id = $4
		 where id = $1
	`, summaryID, bulletsJSON, len(notes), jobID); err != nil {
		return err
	}

	for _, n := range notes {
		if _, err := tx.Exec(ctx, `
			insert into note_summary_sources (tenant_id, summary_id, voice_note_id)
			values (app.current_tenant_id(), $1, $2)
		`, summaryID, n.ID); err != nil {
			return err
		}
	}

	sid := summaryID
	return repo.LogJobEvent(ctx, tx, "note_summary.generated", "note_summary", &sid, &p.StudentID, p.ClassID, nil)
}

func summaryScope(p summaryPayload) string {
	if p.ClassID != nil && p.TermID != nil {
		return "student_class_term"
	}
	return "student_term"
}

func firstSentence(transcript string) string {
	s := strings.TrimSpace(transcript)
	for _, sep := range []string{".", "\n"} {
		if idx := strings.Index(s, sep); idx > 0 {
			s = strings.TrimSpace(s[:idx])
			break
		}
	}
	const max = 140
	if len(s) > max {
		s = strings.TrimSpace(s[:max])
	}
	return s
}

func pluralNotesBullet(n int) string {
	if n == 1 {
		return "1 nota sin transcribir"
	}
	return strconv.Itoa(n) + " notas sin transcribir"
}
