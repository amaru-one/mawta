package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type PracticeScoreEntry struct {
	ID         uuid.UUID `json:"id"`
	Title      string    `json:"title"`
	Kind       string    `json:"kind"`
	RawValue   float64   `json:"raw_value"`
	MaxValue   float64   `json:"max_value"`
	Note       *string   `json:"note"`
	RecordedAt time.Time `json:"recorded_at"`
}

func CreatePracticeScore(ctx context.Context, tx pgx.Tx, classID, studentID, termID, teacherID uuid.UUID, title, kind string, rawValue, maxValue float64, note *string) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into practice_scores (tenant_id, student_id, class_id, term_id, title, kind,
		                              raw_value, max_value, note, recorded_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9)
		returning id
	`, studentID, classID, termID, title, kind, rawValue, maxValue, note, teacherID).Scan(&id)
	return id, err
}

// DeletePracticeScore soft-deletes the row and returns its student/class so
// the caller can log the event — the row itself carries no other context
// once deleted.
func DeletePracticeScore(ctx context.Context, tx pgx.Tx, id uuid.UUID) (studentID, classID uuid.UUID, err error) {
	err = tx.QueryRow(ctx, `
		update practice_scores set deleted_at = now()
		 where id = $1 and deleted_at is null
		returning student_id, class_id
	`, id).Scan(&studentID, &classID)
	return
}

func listPracticeScores(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) ([]PracticeScoreEntry, error) {
	rows, err := tx.Query(ctx, `
		select id, title, kind, raw_value, max_value, note, recorded_at
		  from practice_scores
		 where class_id = $1 and student_id = $2 and term_id = $3 and deleted_at is null
		 order by recorded_at desc
	`, classID, studentID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var entries []PracticeScoreEntry
	for rows.Next() {
		var e PracticeScoreEntry
		if err := rows.Scan(&e.ID, &e.Title, &e.Kind, &e.RawValue, &e.MaxValue, &e.Note, &e.RecordedAt); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}
