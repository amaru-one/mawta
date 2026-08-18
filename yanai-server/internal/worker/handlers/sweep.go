package handlers

import (
	"context"

	"github.com/jackc/pgx/v5"
)

// NotificationSweep writes two kinds of reminder, both deduped on
// (recipient_teacher_id, dedupe_key) so a condition the teacher has already
// seen never re-notifies: attendance_unmarked (sessions with no attendance
// taken in the last 7 days) and grades_pending (published, due assessments
// with students still missing a live score).
func NotificationSweep(ctx context.Context, tx pgx.Tx, _ []byte) error {
	if _, err := tx.Exec(ctx, `
		insert into notifications (tenant_id, recipient_teacher_id, kind, category, title, body,
		                            session_id, class_id, source, dedupe_key, expires_at)
		select app.current_tenant_id(), ct.teacher_id, 'reminder', 'attendance_unmarked',
		       'Asistencia sin marcar — ' || c.name,
		       'Clase de ' || to_char(cs.session_date, 'DD Mon'),
		       cs.id, cs.class_id, 'system', 'attendance_unmarked:' || cs.id, now() + interval '7 days'
		  from class_sessions cs
		  join classes c on c.id = cs.class_id
		  join class_teachers ct on ct.class_id = cs.class_id and ct.role = 'titular' and ct.deleted_at is null
		   and ct.starts_on <= cs.session_date and (ct.ends_on is null or ct.ends_on >= cs.session_date)
		 where cs.attendance_taken_at is null and cs.status in ('in_progress','completed')
		   and cs.deleted_at is null and cs.session_date >= current_date - 7
		on conflict (recipient_teacher_id, dedupe_key) where dedupe_key is not null and deleted_at is null
		do nothing
	`); err != nil {
		return err
	}

	if _, err := tx.Exec(ctx, `
		insert into notifications (tenant_id, recipient_teacher_id, kind, category, title, body,
		                            assessment_id, class_id, source, dedupe_key)
		select app.current_tenant_id(), ct.teacher_id, 'reminder', 'grades_pending',
		       pending.missing || ' notas pendientes — ' || c.name, pending.title,
		       pending.id, pending.class_id, 'system', 'grades_pending:' || pending.id
		  from (
		    select a.id, a.class_id, a.title, count(*) as missing
		      from assessments a
		      join classes c2 on c2.id = a.class_id
		      join section_memberships sm on sm.section_id = c2.section_id
		       and sm.joined_on <= current_date and (sm.left_on is null or sm.left_on > current_date)
		       and sm.deleted_at is null
		      left join scores s on s.assessment_id = a.id and s.student_id = sm.student_id
		                         and s.superseded_at is null and s.deleted_at is null
		     where a.status = 'published' and a.due_at is not null and a.due_at <= now()
		       and a.deleted_at is null and s.id is null
		     group by a.id, a.class_id, a.title
		    having count(*) > 0
		  ) pending
		  join classes c on c.id = pending.class_id
		  join class_teachers ct on ct.class_id = pending.class_id and ct.role = 'titular' and ct.deleted_at is null
		   and ct.starts_on <= current_date and (ct.ends_on is null or ct.ends_on >= current_date)
		on conflict (recipient_teacher_id, dedupe_key) where dedupe_key is not null and deleted_at is null
		do nothing
	`); err != nil {
		return err
	}

	return nil
}
