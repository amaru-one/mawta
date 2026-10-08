package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type SessionHeader struct {
	SessionID        uuid.UUID `json:"session_id"`
	ClassID          uuid.UUID `json:"class_id"`
	ClassName        string    `json:"class_name"`
	TermID           uuid.UUID `json:"term_id"`
	Topic            *string   `json:"topic"`
	SessionDate      string    `json:"session_date"`
	Status           string    `json:"status"`
	AttendanceMarked int       `json:"attendance_marked"`
	AttendanceTotal  int       `json:"attendance_total"`
}

type VoiceNoteRef struct {
	ID         uuid.UUID `json:"id"`
	DurationMs int32     `json:"duration_ms"`
	Transcript *string   `json:"transcript"`
}

type RosterEntry struct {
	StudentID        uuid.UUID      `json:"student_id"`
	Name             string         `json:"name"`
	AttendanceStatus *string        `json:"attendance_status"`
	VoiceNotes       []VoiceNoteRef `json:"voice_notes"`
}

type SessionRoster struct {
	Header SessionHeader `json:"header"`
	Roster []RosterEntry `json:"roster"`
}

func GetSessionHeader(ctx context.Context, tx pgx.Tx, sessionID uuid.UUID) (SessionHeader, error) {
	var h SessionHeader
	var sd time.Time
	err := tx.QueryRow(ctx, `
		select cs.id, cs.class_id, c.name, cs.term_id, cs.topic, cs.session_date, cs.status
		  from class_sessions cs
		  join classes c on c.id = cs.class_id
		 where cs.id = $1 and cs.deleted_at is null
	`, sessionID).Scan(&h.SessionID, &h.ClassID, &h.ClassName, &h.TermID, &h.Topic, &sd, &h.Status)
	if err != nil {
		return h, err
	}
	h.SessionDate = sd.Format("2006-01-02")

	roster, err := RosterAsOf(ctx, tx, h.ClassID, sd)
	if err != nil {
		return h, err
	}
	h.AttendanceTotal = len(roster)

	if err := tx.QueryRow(ctx, `
		select count(*) from attendance_records where session_id = $1 and deleted_at is null
	`, sessionID).Scan(&h.AttendanceMarked); err != nil {
		return h, err
	}

	return h, nil
}

// GetSessionRoster returns the full roster-as-of-session_date for a lesson
// screen, optionally filtered by a name substring using the exact trgm
// index expression. Returns the roster and the ordered student ids, so the
// caller can log student.read events in the same transaction.
func GetSessionRoster(ctx context.Context, tx pgx.Tx, sessionID, classID uuid.UUID, sessionDate time.Time, q string) ([]RosterEntry, []uuid.UUID, error) {
	rows, err := tx.Query(ctx, `
		select st.id,
		       coalesce(st.preferred_name, st.given_name) || ' ' || st.paternal_surname as name,
		       ar.status
		  from section_memberships sm
		  join classes c on c.section_id = sm.section_id and c.id = $1
		  join students st on st.id = sm.student_id and st.deleted_at is null
		  left join attendance_records ar on ar.session_id = $2 and ar.student_id = st.id and ar.deleted_at is null
		 where sm.joined_on <= $3 and (sm.left_on is null or sm.left_on > $3) and sm.deleted_at is null
		   and ($4 = '' or (coalesce(st.given_name,'') || ' ' || coalesce(st.paternal_surname,'') || ' ' || coalesce(st.maternal_surname,'')) ilike '%' || $4 || '%')
		 order by st.paternal_surname, st.given_name
	`, classID, sessionID, sessionDate, q)
	if err != nil {
		return nil, nil, err
	}

	var roster []RosterEntry
	var studentIDs []uuid.UUID
	for rows.Next() {
		var e RosterEntry
		if err := rows.Scan(&e.StudentID, &e.Name, &e.AttendanceStatus); err != nil {
			rows.Close()
			return nil, nil, err
		}
		roster = append(roster, e)
		studentIDs = append(studentIDs, e.StudentID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}

	notesByStudent := make(map[uuid.UUID][]VoiceNoteRef)
	vrows, err := tx.Query(ctx, `
		select student_id, id, duration_ms, transcript
		  from voice_notes
		 where session_id = $1 and deleted_at is null
		 order by recorded_at
	`, sessionID)
	if err != nil {
		return nil, nil, err
	}
	for vrows.Next() {
		var sid uuid.UUID
		var v VoiceNoteRef
		if err := vrows.Scan(&sid, &v.ID, &v.DurationMs, &v.Transcript); err != nil {
			vrows.Close()
			return nil, nil, err
		}
		notesByStudent[sid] = append(notesByStudent[sid], v)
	}
	vrows.Close()
	if err := vrows.Err(); err != nil {
		return nil, nil, err
	}

	for i := range roster {
		roster[i].VoiceNotes = notesByStudent[roster[i].StudentID]
	}

	return roster, studentIDs, nil
}
