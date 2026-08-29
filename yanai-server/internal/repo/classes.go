package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type ClassInfo struct {
	ID        uuid.UUID
	Name      string
	SectionID uuid.UUID
	IsTutoria bool
}

func GetClassInfo(ctx context.Context, tx pgx.Tx, classID uuid.UUID) (ClassInfo, error) {
	var c ClassInfo
	err := tx.QueryRow(ctx, `
		select c.id, c.name, c.section_id, s.is_tutoria
		  from classes c
		  join courses co on co.id = c.course_id
		  join subjects s on s.id = co.subject_id
		 where c.id = $1 and c.deleted_at is null
	`, classID).Scan(&c.ID, &c.Name, &c.SectionID, &c.IsTutoria)
	return c, err
}

type DashboardStats struct {
	NotasRegNumerator   int      `json:"scored"`
	NotasRegDenominator int      `json:"expected"`
	AsistenciaPct       *float64 `json:"asistencia_pct"`
}

type LevelCount struct {
	Code  string `json:"code"`
	Count int    `json:"count"`
}

type GradesPendingAssessment struct {
	AssessmentID uuid.UUID `json:"assessment_id"`
	Title        string    `json:"title"`
	Missing      int       `json:"missing"`
}

type AttendanceUnmarkedSession struct {
	SessionID   uuid.UUID `json:"session_id"`
	SessionDate string    `json:"session_date"`
}

// ComponentProgress is one component's share of the grade registration for a
// class: how many of the expected scores are in, and that as a 0-1 ratio.
// Pct is null when nothing is due yet, which is distinct from "due but none
// registered" (Expected > 0, Pct 0).
type ComponentProgress struct {
	ComponentID uuid.UUID `json:"component_id"`
	Code        string    `json:"code"`
	Name        string    `json:"name"`
	Scored      int       `json:"scored"`
	Expected    int       `json:"expected"`
	Pct         *float64  `json:"pct"`
}

type SessionSummary struct {
	SessionID        uuid.UUID `json:"session_id"`
	SessionDate      string    `json:"session_date"`
	ScheduledStartAt time.Time `json:"scheduled_start_at"`
	ScheduledEndAt   time.Time `json:"scheduled_end_at"`
	Topic            *string   `json:"topic"`
	Status           string    `json:"status"`
	PresentCount     *int      `json:"present_count,omitempty"`
	RosterCount      *int      `json:"roster_count,omitempty"`
	MissingGrades    *int      `json:"missing_grades,omitempty"`
	HasComments      *bool     `json:"has_comments,omitempty"`
}

type ClassDashboard struct {
	ClassID            uuid.UUID                   `json:"class_id"`
	Name               string                      `json:"name"`
	IsTutoria          bool                        `json:"is_tutoria"`
	RosterCount        int                         `json:"roster_count"`
	SessionsPerWeek    int                         `json:"sessions_per_week"`
	TermID             uuid.UUID                   `json:"term_id"`
	NextSession        *SessionSummary             `json:"next_session"`
	Stats              DashboardStats              `json:"stats"`
	Progress           []ComponentProgress         `json:"progress"`
	Distribution       []LevelCount                `json:"distribution"`
	GradesPending      []GradesPendingAssessment   `json:"grades_pending"`
	AttendanceUnmarked []AttendanceUnmarkedSession `json:"attendance_unmarked"`
	Upcoming           []SessionSummary            `json:"upcoming"`
	Past               []SessionSummary            `json:"past"`
}

func GetClassDashboard(ctx context.Context, tx pgx.Tx, classID uuid.UUID, term Term, today time.Time) (ClassDashboard, error) {
	var d ClassDashboard
	class, err := GetClassInfo(ctx, tx, classID)
	if err != nil {
		return d, err
	}
	d.ClassID = class.ID
	d.Name = class.Name
	d.IsTutoria = class.IsTutoria
	d.TermID = term.ID

	roster, err := RosterAsOf(ctx, tx, classID, today)
	if err != nil {
		return d, err
	}
	d.RosterCount = len(roster)

	if err := tx.QueryRow(ctx, `
		select count(*) from class_schedules
		 where class_id = $1 and effective_from <= $2
		   and (effective_to is null or effective_to > $2)
		   and deleted_at is null
	`, classID, today).Scan(&d.SessionsPerWeek); err != nil {
		return d, err
	}

	// next_session: today's scheduled/in_progress session.
	var ns SessionSummary
	var nsFound bool
	var nsDate time.Time
	err = tx.QueryRow(ctx, `
		select id, session_date, scheduled_start_at, scheduled_end_at, topic, status
		  from class_sessions
		 where class_id = $1 and session_date = $2 and status in ('scheduled','in_progress')
		   and deleted_at is null
		 order by scheduled_start_at limit 1
	`, classID, today).Scan(&ns.SessionID, &nsDate, &ns.ScheduledStartAt, &ns.ScheduledEndAt, &ns.Topic, &ns.Status)
	if err == nil {
		ns.SessionDate = nsDate.Format("2006-01-02")
		nsFound = true
	} else if err != pgx.ErrNoRows {
		return d, err
	}
	if nsFound {
		d.NextSession = &ns
	}

	// stats: notas registradas.
	// A per-student assessment (assessments.student_id) counts once, for its
	// own student — not once per student on the roster, which is what the
	// plain cross join would do.
	err = tx.QueryRow(ctx, `
		with due as (
		  select id, student_id from assessments
		   where class_id = $1 and term_id = $2 and status = 'published'
		     and deleted_at is null
		),
		roster_ids as (select unnest($3::uuid[]) as student_id),
		expected as (
		  select d.id, r.student_id
		    from due d cross join roster_ids r
		   where d.student_id is null or d.student_id = r.student_id
		)
		select
		  (select count(*) from expected) as denom,
		  (select count(*) from expected e
		     where exists (
		       select 1 from scores s
		        where s.assessment_id = e.id and s.student_id = e.student_id
		          and s.superseded_at is null and s.deleted_at is null
		     )) as scored
	`, classID, term.ID, roster).Scan(&d.Stats.NotasRegDenominator, &d.Stats.NotasRegNumerator)
	if err != nil {
		return d, err
	}

	// stats: asistencia % over the term.
	var present, total int
	err = tx.QueryRow(ctx, `
		select count(*) filter (where status in ('present','late')), count(*)
		  from attendance_records
		 where class_id = $1 and session_date between $2 and $3 and deleted_at is null
	`, classID, term.StartsOn, term.EndsOn).Scan(&present, &total)
	if err != nil {
		return d, err
	}
	if total > 0 {
		pct := float64(present) / float64(total)
		d.Stats.AsistenciaPct = &pct
	}

	// distribution (skip for tutoría).
	if !class.IsTutoria {
		rows, err := tx.Query(ctx, `
			select l.code, l.ordinal, count(*)
			  from competency_term_levels ctl
			  join grade_scale_levels l on l.id = ctl.scale_level_id
			 where ctl.class_id = $1 and ctl.term_id = $2
			   and ctl.superseded_at is null and ctl.deleted_at is null
			 group by l.code, l.ordinal
			 order by l.ordinal desc
		`, classID, term.ID)
		if err != nil {
			return d, err
		}
		for rows.Next() {
			var lc LevelCount
			var ordinal int
			if err := rows.Scan(&lc.Code, &ordinal, &lc.Count); err != nil {
				rows.Close()
				return d, err
			}
			d.Distribution = append(d.Distribution, lc)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return d, err
		}
	}

	// progress: how much of the grade registration is done, per component of the
	// class's effective scheme. expected = one cell per (assessment, student it
	// applies to) — the whole roster for a class-wide assessment, one student for
	// a per-student one; scored = how many of those have a live score.
	// Components with no published assessment yet report expected = 0, which the
	// panel renders as an empty ring.
	if !class.IsTutoria {
		rows, err := tx.Query(ctx, `
			with due as (
			  select a.id, a.component_id, a.student_id from assessments a
			   where a.class_id = $1 and a.term_id = $2 and a.status = 'published'
			     and a.deleted_at is null
			),
			roster_ids as (select unnest($3::uuid[]) as student_id),
			expected as (
			  select d.id, d.component_id, r.student_id
			    from due d cross join roster_ids r
			   where d.student_id is null or d.student_id = r.student_id
			)
			select gc.id, gc.code, gc.name,
			       (select count(*) from expected e where e.component_id = gc.id) as expected,
			       (select count(*) from expected e
			         where e.component_id = gc.id
			           and exists (
			             select 1 from scores s
			              where s.assessment_id = e.id and s.student_id = e.student_id
			                and s.superseded_at is null and s.deleted_at is null
			           )) as scored
			  from grading_components gc
			  join class_effective_grading_schemes ceg on ceg.scheme_id = gc.scheme_id
			 where ceg.class_id = $1 and ceg.term_id = $2 and gc.deleted_at is null
			 order by gc.sort_order
		`, classID, term.ID, roster)
		if err != nil {
			return d, err
		}
		for rows.Next() {
			var cp ComponentProgress
			if err := rows.Scan(&cp.ComponentID, &cp.Code, &cp.Name, &cp.Expected, &cp.Scored); err != nil {
				rows.Close()
				return d, err
			}
			if cp.Expected > 0 {
				pct := float64(cp.Scored) / float64(cp.Expected)
				cp.Pct = &pct
			}
			d.Progress = append(d.Progress, cp)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return d, err
		}
	}

	// pendientes: grades pending.
	rows, err := tx.Query(ctx, `
		select a.id, a.title, count(*) as missing
		  from assessments a
		  cross join unnest($3::uuid[]) as r(student_id)
		  left join scores s on s.assessment_id = a.id and s.student_id = r.student_id
		                     and s.superseded_at is null and s.deleted_at is null
		 where a.class_id = $1 and a.term_id = $2 and a.status = 'published'
		   and a.due_at is not null and a.due_at <= now() and a.deleted_at is null
		   and (a.student_id is null or a.student_id = r.student_id)
		   and s.id is null
		 group by a.id, a.title
		 having count(*) > 0
		 order by a.title
	`, classID, term.ID, roster)
	if err != nil {
		return d, err
	}
	for rows.Next() {
		var g GradesPendingAssessment
		if err := rows.Scan(&g.AssessmentID, &g.Title, &g.Missing); err != nil {
			rows.Close()
			return d, err
		}
		d.GradesPending = append(d.GradesPending, g)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return d, err
	}

	// pendientes: attendance unmarked.
	rows, err = tx.Query(ctx, `
		select id, session_date from class_sessions
		 where class_id = $1 and attendance_taken_at is null
		   and status in ('in_progress','completed') and deleted_at is null
		 order by session_date desc
	`, classID)
	if err != nil {
		return d, err
	}
	for rows.Next() {
		var au AttendanceUnmarkedSession
		var sd time.Time
		if err := rows.Scan(&au.SessionID, &sd); err != nil {
			rows.Close()
			return d, err
		}
		au.SessionDate = sd.Format("2006-01-02")
		d.AttendanceUnmarked = append(d.AttendanceUnmarked, au)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return d, err
	}

	upcoming, err := ListSessions(ctx, tx, classID, today, "upcoming", 10)
	if err != nil {
		return d, err
	}
	d.Upcoming = upcoming

	past, err := ListSessions(ctx, tx, classID, today, "past", 10)
	if err != nil {
		return d, err
	}
	d.Past = past

	return d, nil
}

// ListSessions returns upcoming (session_date > d, ascending) or past
// (session_date < d, descending) sessions for a class — d itself is
// today's session, surfaced separately as next_session. Past rows carry
// attendance and pending-grade chips.
func ListSessions(ctx context.Context, tx pgx.Tx, classID uuid.UUID, d time.Time, dir string, limit int) ([]SessionSummary, error) {
	var query string
	if dir == "past" {
		query = `
			select cs.id, cs.session_date, cs.scheduled_start_at, cs.scheduled_end_at, cs.topic, cs.status,
			       att.present_count, att.roster_count, coalesce(pg.missing, 0),
			       exists (
			         select 1 from voice_notes vn
			          where vn.session_id = cs.id and vn.status = 'saved'
			       ) as has_comments
			  from class_sessions cs
			  cross join lateral (
			    select
			      (select count(*) from attendance_records ar
			        where ar.session_id = cs.id and ar.status in ('present','late') and ar.deleted_at is null) as present_count,
			      (select count(*) from section_memberships sm
			         join classes c on c.section_id = sm.section_id
			        where c.id = cs.class_id
			          and sm.joined_on <= cs.session_date
			          and (sm.left_on is null or sm.left_on > cs.session_date)
			          and sm.deleted_at is null) as roster_count
			  ) att
			  left join lateral (
			    select count(*) as missing
			      from assessments a
			      join classes c on c.id = a.class_id
			      join section_memberships sm on sm.section_id = c.section_id
			       and sm.joined_on <= cs.session_date
			       and (sm.left_on is null or sm.left_on > cs.session_date)
			       and sm.deleted_at is null
			      left join scores s on s.assessment_id = a.id and s.student_id = sm.student_id
			                         and s.superseded_at is null and s.deleted_at is null
			     where a.session_id = cs.id and a.status = 'published' and a.deleted_at is null
			       and (a.student_id is null or a.student_id = sm.student_id)
			       and s.id is null
			  ) pg on true
			 where cs.class_id = $1 and cs.session_date < $2 and cs.deleted_at is null
			 order by cs.session_date desc, cs.scheduled_start_at desc
			 limit $3
		`
	} else {
		query = `
			select cs.id, cs.session_date, cs.scheduled_start_at, cs.scheduled_end_at, cs.topic, cs.status,
			       null::int, null::int, null::int, null::bool
			  from class_sessions cs
			 where cs.class_id = $1 and cs.session_date > $2 and cs.deleted_at is null
			 order by cs.session_date asc, cs.scheduled_start_at asc
			 limit $3
		`
	}

	rows, err := tx.Query(ctx, query, classID, d, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []SessionSummary
	for rows.Next() {
		var s SessionSummary
		var sd time.Time
		if err := rows.Scan(&s.SessionID, &sd, &s.ScheduledStartAt, &s.ScheduledEndAt, &s.Topic, &s.Status,
			&s.PresentCount, &s.RosterCount, &s.MissingGrades, &s.HasComments); err != nil {
			return nil, err
		}
		s.SessionDate = sd.Format("2006-01-02")
		out = append(out, s)
	}
	return out, rows.Err()
}
