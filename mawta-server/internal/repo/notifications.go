package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type NotificationEntry struct {
	ID          uuid.UUID  `json:"id"`
	Kind        string     `json:"kind"`
	Category    string     `json:"category"`
	Severity    string     `json:"severity"`
	Title       string     `json:"title"`
	Body        *string    `json:"body"`
	CreatedAt   time.Time  `json:"created_at"`
	ReadAt      *time.Time `json:"read_at"`
	DismissedAt *time.Time `json:"dismissed_at"`
	StudentName *string    `json:"student_name"`
	ClassName   *string    `json:"class_name"`
}

func ListNotifications(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID, kind string, limit int, before *time.Time) ([]NotificationEntry, error) {
	rows, err := tx.Query(ctx, `
		select n.id, n.kind, n.category, n.severity, n.title, n.body, n.created_at, n.read_at, n.dismissed_at,
		       case when s.id is not null then coalesce(s.preferred_name, s.given_name) || ' ' || s.paternal_surname end,
		       c.name
		  from notifications n
		  left join students s on s.id = n.student_id
		  left join classes c on c.id = n.class_id
		 where n.recipient_teacher_id = $1 and n.deleted_at is null
		   and ($2 = '' or n.kind = $2)
		   and ($3::timestamptz is null or n.created_at < $3)
		 order by n.created_at desc
		 limit $4
	`, teacherID, kind, before, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []NotificationEntry
	for rows.Next() {
		var n NotificationEntry
		if err := rows.Scan(&n.ID, &n.Kind, &n.Category, &n.Severity, &n.Title, &n.Body, &n.CreatedAt,
			&n.ReadAt, &n.DismissedAt, &n.StudentName, &n.ClassName); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

func MarkNotificationRead(ctx context.Context, tx pgx.Tx, notificationID, teacherID uuid.UUID) error {
	ct, err := tx.Exec(ctx, `
		update notifications set read_at = coalesce(read_at, now())
		 where id = $1 and recipient_teacher_id = $2 and deleted_at is null
	`, notificationID, teacherID)
	if err != nil {
		return err
	}
	if ct.RowsAffected() == 0 {
		return pgx.ErrNoRows
	}
	return nil
}

func MarkAllNotificationsRead(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID) (int, error) {
	ct, err := tx.Exec(ctx, `
		update notifications set read_at = now()
		 where recipient_teacher_id = $1 and read_at is null and deleted_at is null
	`, teacherID)
	if err != nil {
		return 0, err
	}
	return int(ct.RowsAffected()), nil
}
