package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// GetSessionMeta returns the class and calendar date of a session — the
// minimum needed to compute its roster.
func GetSessionMeta(ctx context.Context, tx pgx.Tx, sessionID uuid.UUID) (classID uuid.UUID, sessionDate time.Time, err error) {
	err = tx.QueryRow(ctx, `
		select class_id, session_date from class_sessions where id = $1 and deleted_at is null
	`, sessionID).Scan(&classID, &sessionDate)
	return
}

// UpsertAttendance records or updates one student's attendance for a
// session. Denormalized columns (class_id, session_date) are never
// supplied — the sync_denormalised trigger fills them.
func UpsertAttendance(ctx context.Context, tx pgx.Tx, sessionID, studentID, teacherID uuid.UUID, status string, minutesLate *int16, note *string) error {
	_, err := tx.Exec(ctx, `
		insert into attendance_records (tenant_id, session_id, student_id, status, minutes_late, note, source, recorded_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, 'manual', $6)
		on conflict (session_id, student_id) where deleted_at is null
		do update set status = excluded.status, minutes_late = excluded.minutes_late,
		              note = excluded.note, source = 'manual',
		              recorded_by_id = excluded.recorded_by_id, recorded_at = now()
	`, sessionID, studentID, status, minutesLate, note, teacherID)
	return err
}

// MarkAllPresent bulk-inserts a 'present' row for every roster student who
// has no attendance row yet for this session, without clobbering explicit
// marks already taken.
func MarkAllPresent(ctx context.Context, tx pgx.Tx, sessionID, classID, teacherID uuid.UUID, sessionDate time.Time) (int, error) {
	ct, err := tx.Exec(ctx, `
		insert into attendance_records (tenant_id, session_id, student_id, status, source, recorded_by_id)
		select app.current_tenant_id(), $1, sm.student_id, 'present', 'bulk', $2
		  from section_memberships sm
		  join classes c on c.section_id = sm.section_id
		 where c.id = $3
		   and sm.joined_on <= $4 and (sm.left_on is null or sm.left_on > $4) and sm.deleted_at is null
		on conflict (session_id, student_id) where deleted_at is null do nothing
	`, sessionID, teacherID, classID, sessionDate)
	if err != nil {
		return 0, err
	}
	return int(ct.RowsAffected()), nil
}

// MaybeStampAttendanceTaken sets attendance_taken_at/_by once every roster
// student as of the session date has an attendance row.
func MaybeStampAttendanceTaken(ctx context.Context, tx pgx.Tx, sessionID, teacherID uuid.UUID) error {
	_, err := tx.Exec(ctx, `
		update class_sessions cs
		   set attendance_taken_at = now(), attendance_taken_by_id = $2
		 where cs.id = $1
		   and cs.attendance_taken_at is null
		   and cs.deleted_at is null
		   and (select count(*) from attendance_records ar where ar.session_id = cs.id and ar.deleted_at is null)
		       >= (select count(*) from section_memberships sm
		             join classes c on c.section_id = sm.section_id
		            where c.id = cs.class_id
		              and sm.joined_on <= cs.session_date
		              and (sm.left_on is null or sm.left_on > cs.session_date)
		              and sm.deleted_at is null)
	`, sessionID, teacherID)
	return err
}
