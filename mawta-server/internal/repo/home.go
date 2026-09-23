package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// TenantToday returns "today" as a date in the tenant's IANA timezone —
// the only place a local calendar day is defined in this schema.
func TenantToday(ctx context.Context, tx pgx.Tx, tenantID uuid.UUID) (time.Time, error) {
	var d time.Time
	err := tx.QueryRow(ctx, `select (now() at time zone tn.timezone)::date from tenants tn where tn.id = $1`, tenantID).Scan(&d)
	return d, err
}

type HomeClass struct {
	ClassID   uuid.UUID `json:"class_id"`
	Name      string    `json:"name"`
	IconKey   *string   `json:"icon_key"`
	IsTutoria bool      `json:"is_tutoria"`
}

type HomeTodayEntry struct {
	HomeClass
	SessionID        *uuid.UUID `json:"session_id"`
	ScheduledStartAt *time.Time `json:"scheduled_start_at"`
	ScheduledEndAt   *time.Time `json:"scheduled_end_at"`
	Status           *string    `json:"status"`
	Room             *string    `json:"room"`
	Topic            *string    `json:"topic"`
}

// One dated session elsewhere in the week. Unlike HomeTodayEntry every field is
// present: these rows exist because a class_sessions row does.
type HomeWeekSession struct {
	HomeClass
	SessionID        uuid.UUID `json:"session_id"`
	ScheduledStartAt time.Time `json:"scheduled_start_at"`
	ScheduledEndAt   time.Time `json:"scheduled_end_at"`
	Status           string    `json:"status"`
	Room             *string   `json:"room"`
	Topic            *string   `json:"topic"`
}

type HomeWeekDay struct {
	Date     string            `json:"date"`
	Weekday  int16             `json:"weekday"`
	Sessions []HomeWeekSession `json:"sessions"`
}

type HomeResponse struct {
	Date  string           `json:"date"`
	Today []HomeTodayEntry `json:"today"`
	Week  []HomeWeekDay    `json:"week"`
}

// myClasses returns the teacher's active classes as of date d.
func myClasses(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID, d time.Time) ([]HomeClass, error) {
	rows, err := tx.Query(ctx, `
		select distinct c.id, c.name, s.icon_key, s.is_tutoria
		  from class_teachers ct
		  join classes c on c.id = ct.class_id and c.deleted_at is null and c.status = 'active'
		  join courses co on co.id = c.course_id
		  join subjects s on s.id = co.subject_id
		 where ct.teacher_id = $1
		   and ct.starts_on <= $2
		   and (ct.ends_on is null or ct.ends_on >= $2)
		   and ct.deleted_at is null
		 order by c.name
	`, teacherID, d)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []HomeClass
	for rows.Next() {
		var hc HomeClass
		if err := rows.Scan(&hc.ClassID, &hc.Name, &hc.IconKey, &hc.IsTutoria); err != nil {
			return nil, err
		}
		out = append(out, hc)
	}
	return out, rows.Err()
}

func GetHome(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID, d time.Time) (HomeResponse, error) {
	resp := HomeResponse{Date: d.Format("2006-01-02")}

	classes, err := myClasses(ctx, tx, teacherID, d)
	if err != nil {
		return resp, err
	}
	if len(classes) == 0 {
		return resp, nil
	}

	classIDs := make([]uuid.UUID, len(classes))
	byID := make(map[uuid.UUID]HomeClass, len(classes))
	for i, c := range classes {
		classIDs[i] = c.ClassID
		byID[c.ClassID] = c
	}

	// Status is deliberately not filtered: home shows the day as it stands,
	// cancelled and finished sessions included. The client renders those states,
	// it does not hide them.
	rows, err := tx.Query(ctx, `
		select class_id, id, scheduled_start_at, scheduled_end_at, status, room, topic
		  from class_sessions
		 where class_id = any($1) and session_date = $2 and deleted_at is null
		 order by scheduled_start_at
	`, classIDs, d)
	if err != nil {
		return resp, err
	}
	for rows.Next() {
		var classID, sessionID uuid.UUID
		var start, end time.Time
		var status string
		var room, topic *string
		if err := rows.Scan(&classID, &sessionID, &start, &end, &status, &room, &topic); err != nil {
			rows.Close()
			return resp, err
		}
		resp.Today = append(resp.Today, HomeTodayEntry{
			HomeClass: byID[classID], SessionID: &sessionID,
			ScheduledStartAt: &start, ScheduledEndAt: &end, Status: &status,
			Room: room, Topic: topic,
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return resp, err
	}

	// The rest of the ISO week (date_trunc('week') starts Monday, which is the
	// weekday convention the schema uses throughout) as concrete dated sessions
	// rather than the recurring class_schedules pattern. A class that
	// also meets today appears in both buckets — the week is an agenda of days,
	// not a list of classes the teacher has not seen yet.
	rows, err = tx.Query(ctx, `
		select cs.class_id, cs.id, cs.session_date,
		       extract(isodow from cs.session_date)::smallint,
		       cs.scheduled_start_at, cs.scheduled_end_at, cs.status, cs.room, cs.topic
		  from class_sessions cs
		 where cs.class_id = any($1)
		   and cs.deleted_at is null
		   and cs.session_date >= date_trunc('week', $2::date)::date
		   and cs.session_date <  date_trunc('week', $2::date)::date + 7
		   and cs.session_date <> $2
		 order by cs.session_date, cs.scheduled_start_at
	`, classIDs, d)
	if err != nil {
		return resp, err
	}
	defer rows.Close()

	for rows.Next() {
		var classID uuid.UUID
		var date time.Time
		var weekday int16
		var s HomeWeekSession
		if err := rows.Scan(&classID, &s.SessionID, &date, &weekday,
			&s.ScheduledStartAt, &s.ScheduledEndAt, &s.Status, &s.Room, &s.Topic); err != nil {
			return resp, err
		}
		s.HomeClass = byID[classID]

		// Rows arrive ordered by date, so a new day is always the last one.
		day := date.Format("2006-01-02")
		if n := len(resp.Week); n == 0 || resp.Week[n-1].Date != day {
			resp.Week = append(resp.Week, HomeWeekDay{Date: day, Weekday: weekday})
		}
		last := &resp.Week[len(resp.Week)-1]
		last.Sessions = append(last.Sessions, s)
	}
	if err := rows.Err(); err != nil {
		return resp, err
	}
	return resp, nil
}
