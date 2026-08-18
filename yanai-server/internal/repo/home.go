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
}

type ScheduleSlot struct {
	Weekday  int16  `json:"weekday"`
	StartsAt string `json:"starts_at"`
	EndsAt   string `json:"ends_at"`
}

type HomeWeekEntry struct {
	HomeClass
	Slots []ScheduleSlot `json:"slots"`
}

type HomeResponse struct {
	Date  string           `json:"date"`
	Today []HomeTodayEntry `json:"today"`
	Week  []HomeWeekEntry  `json:"week"`
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

	rows, err := tx.Query(ctx, `
		select class_id, id, scheduled_start_at, scheduled_end_at, status
		  from class_sessions
		 where class_id = any($1) and session_date = $2 and deleted_at is null
		 order by scheduled_start_at
	`, classIDs, d)
	if err != nil {
		return resp, err
	}
	todaySeen := make(map[uuid.UUID]bool)
	for rows.Next() {
		var classID, sessionID uuid.UUID
		var start, end time.Time
		var status string
		if err := rows.Scan(&classID, &sessionID, &start, &end, &status); err != nil {
			rows.Close()
			return resp, err
		}
		resp.Today = append(resp.Today, HomeTodayEntry{
			HomeClass: byID[classID], SessionID: &sessionID,
			ScheduledStartAt: &start, ScheduledEndAt: &end, Status: &status,
		})
		todaySeen[classID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return resp, err
	}

	var remaining []uuid.UUID
	for _, id := range classIDs {
		if !todaySeen[id] {
			remaining = append(remaining, id)
		}
	}
	if len(remaining) == 0 {
		return resp, nil
	}

	rows, err = tx.Query(ctx, `
		select class_id, weekday, to_char(starts_at, 'HH24:MI'), to_char(ends_at, 'HH24:MI')
		  from class_schedules
		 where class_id = any($1)
		   and effective_from <= $2
		   and (effective_to is null or effective_to > $2)
		   and deleted_at is null
		 order by class_id, weekday, starts_at
	`, remaining, d)
	if err != nil {
		return resp, err
	}
	defer rows.Close()

	weekByClass := make(map[uuid.UUID]*HomeWeekEntry)
	var order []uuid.UUID
	for rows.Next() {
		var classID uuid.UUID
		var slot ScheduleSlot
		if err := rows.Scan(&classID, &slot.Weekday, &slot.StartsAt, &slot.EndsAt); err != nil {
			return resp, err
		}
		entry, ok := weekByClass[classID]
		if !ok {
			hc := byID[classID]
			entry = &HomeWeekEntry{HomeClass: hc}
			weekByClass[classID] = entry
			order = append(order, classID)
		}
		entry.Slots = append(entry.Slots, slot)
	}
	if err := rows.Err(); err != nil {
		return resp, err
	}
	for _, id := range order {
		resp.Week = append(resp.Week, *weekByClass[id])
	}
	return resp, nil
}

type ClassSearchResult struct {
	ClassID uuid.UUID `json:"class_id"`
	Name    string    `json:"name"`
}

// SearchClasses matches the "Buscar por clase" box using the classes.name
// trgm index.
func SearchClasses(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID, q string) ([]ClassSearchResult, error) {
	rows, err := tx.Query(ctx, `
		select distinct c.id, c.name
		  from classes c
		  join class_teachers ct on ct.class_id = c.id and ct.deleted_at is null
		 where ct.teacher_id = $1
		   and c.deleted_at is null
		   and c.name ilike '%' || $2 || '%'
		 order by c.name
		 limit 20
	`, teacherID, q)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []ClassSearchResult
	for rows.Next() {
		var c ClassSearchResult
		if err := rows.Scan(&c.ClassID, &c.Name); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
