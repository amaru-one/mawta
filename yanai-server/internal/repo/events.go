package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// LogEvent calls the schema's app.log_event(...) writer, which fills
// tenant/actor/request_id from the session GUCs.
func LogEvent(ctx context.Context, tx pgx.Tx, action, entityType string, entityID *uuid.UUID, payload []byte, studentID, classID, sessionID *uuid.UUID) error {
	if payload == nil {
		payload = []byte("{}")
	}
	_, err := tx.Exec(ctx, `select app.log_event($1, $2, $3, $4, $5, $6, $7)`,
		action, entityType, entityID, payload, studentID, classID, sessionID)
	return err
}

// LogJobEvent writes an event with actor_type='job', for actions taken by
// the background worker rather than an interactive request (app.log_event
// always stamps actor_type='user', which is wrong for these).
func LogJobEvent(ctx context.Context, tx pgx.Tx, action, entityType string, entityID, studentID, classID *uuid.UUID, payload []byte) error {
	if payload == nil {
		payload = []byte("{}")
	}
	_, err := tx.Exec(ctx, `
		insert into events (tenant_id, actor_type, action, entity_type, entity_id, student_id, class_id, payload)
		values (app.current_tenant_id(), 'job', $1, $2, $3, $4, $5, $6)
	`, action, entityType, entityID, studentID, classID, payload)
	return err
}

// LogStudentReads bulk-inserts student.read events for every student id in
// a roster/search response, in the same transaction as the read. Every read
// that returns identifiable student rows must produce one of these.
func LogStudentReads(ctx context.Context, tx pgx.Tx, studentIDs []uuid.UUID, teacherID uuid.UUID, classID, sessionID *uuid.UUID) error {
	if len(studentIDs) == 0 {
		return nil
	}
	_, err := tx.Exec(ctx, `
		insert into events (tenant_id, actor_id, actor_teacher_id, action, entity_type, entity_id,
		                     student_id, class_id, session_id, payload, request_id)
		select app.current_tenant_id(), app.current_actor_id(), $2, 'student.read', 'student', sid,
		       sid, $3, $4, '{}'::jsonb, nullif(current_setting('app.request_id', true), '')
		  from unnest($1::uuid[]) as sid
	`, studentIDs, teacherID, classID, sessionID)
	return err
}
