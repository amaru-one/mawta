package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// UpsertObservation upserts one student's observation note for a session and
// reconciles their behavior flags to exactly flagTypeIDs (soft-deleting
// removed ones, inserting missing ones).
func UpsertObservation(ctx context.Context, tx pgx.Tx, sessionID, studentID, teacherID uuid.UUID, note *string, flagTypeIDs []uuid.UUID) error {
	var observationID uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into session_observations (tenant_id, session_id, student_id, note, recorded_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4)
		on conflict (session_id, student_id) where deleted_at is null
		do update set note = excluded.note,
		              recorded_by_id = excluded.recorded_by_id, recorded_at = now()
		returning id
	`, sessionID, studentID, note, teacherID).Scan(&observationID)
	if err != nil {
		return err
	}

	if flagTypeIDs == nil {
		flagTypeIDs = []uuid.UUID{}
	}

	if _, err := tx.Exec(ctx, `
		update session_observation_flags
		   set deleted_at = now()
		 where observation_id = $1 and flag_type_id <> all($2::uuid[]) and deleted_at is null
	`, observationID, flagTypeIDs); err != nil {
		return err
	}

	if len(flagTypeIDs) > 0 {
		if _, err := tx.Exec(ctx, `
			insert into session_observation_flags (tenant_id, observation_id, flag_type_id)
			select app.current_tenant_id(), $1, ft
			  from unnest($2::uuid[]) as ft
			on conflict (observation_id, flag_type_id) where deleted_at is null do nothing
		`, observationID, flagTypeIDs); err != nil {
			return err
		}
	}

	return nil
}
