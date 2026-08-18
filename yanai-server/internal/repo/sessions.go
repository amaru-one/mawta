package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type SessionHeader struct {
	SessionID          uuid.UUID `json:"session_id"`
	ClassID            uuid.UUID `json:"class_id"`
	ClassName          string    `json:"class_name"`
	TermID             uuid.UUID `json:"term_id"`
	Topic              *string   `json:"topic"`
	SessionDate        string    `json:"session_date"`
	Status             string    `json:"status"`
	SectionAverageCode *string   `json:"section_average_code"`
	AttendanceMarked   int       `json:"attendance_marked"`
	AttendanceTotal    int       `json:"attendance_total"`
}

type FlagRef struct {
	ID         uuid.UUID `json:"id"`
	Code       string    `json:"code"`
	Label      string    `json:"label"`
	Severity   string    `json:"severity"`
	IsPositive bool      `json:"is_positive"`
}

type VoiceNoteRef struct {
	ID                  uuid.UUID `json:"id"`
	DurationMs          int32     `json:"duration_ms"`
	Status              string    `json:"status"`
	TranscriptionStatus string    `json:"transcription_status"`
	Transcript          *string   `json:"transcript"`
}

type RosterEntry struct {
	StudentID          uuid.UUID      `json:"student_id"`
	Name               string         `json:"name"`
	LevelCode          *string        `json:"level_code"`
	PreviousLevelCode  *string        `json:"previous_level_code"`
	Trend              *string        `json:"trend"`
	AttendanceStatus   *string        `json:"attendance_status"`
	ParticipationLevel *int16         `json:"participation_level"`
	ObservationNote    *string        `json:"observation_note"`
	Flags              []FlagRef      `json:"flags"`
	VoiceNotes         []VoiceNoteRef `json:"voice_notes"`
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

	if h.TermID != uuid.Nil {
		var avg *float64
		if err := tx.QueryRow(ctx, `
			select avg(normalized_value) from computed_grades
			 where class_id = $1 and term_id = $2 and scope = 'term_partial'
			   and superseded_at is null and deleted_at is null
		`, h.ClassID, h.TermID).Scan(&avg); err != nil {
			return h, err
		}
		if avg != nil {
			var code string
			err := tx.QueryRow(ctx, `
				select l.code
				  from class_effective_grading_schemes ceg
				  join grading_schemes gsch on gsch.id = ceg.scheme_id
				  join grade_scale_levels l on l.scale_id = gsch.scale_id
				 where ceg.class_id = $1 and ceg.term_id = $2
				   and $3 >= l.min_normalized and ($3 < l.max_normalized or l.max_normalized = 1)
				   and l.deleted_at is null
			`, h.ClassID, h.TermID, *avg).Scan(&code)
			if err == nil {
				h.SectionAverageCode = &code
			} else if err != pgx.ErrNoRows {
				return h, err
			}
		}
	}

	return h, nil
}

// GetSessionRoster returns the full roster-as-of-session_date for a lesson
// screen, optionally filtered by a name substring using the exact trgm
// index expression. Returns the roster and the ordered student ids, so the
// caller can log student.read events in the same transaction.
func GetSessionRoster(ctx context.Context, tx pgx.Tx, sessionID, classID uuid.UUID, sessionDate time.Time, termID uuid.UUID, q string) ([]RosterEntry, []uuid.UUID, error) {
	rows, err := tx.Query(ctx, `
		select st.id,
		       coalesce(st.preferred_name, st.given_name) || ' ' || st.paternal_surname as name,
		       lvl.code, prevlvl.code, cg.trend,
		       ar.status, so.id, so.participation_level, so.note
		  from section_memberships sm
		  join classes c on c.section_id = sm.section_id and c.id = $1
		  join students st on st.id = sm.student_id and st.deleted_at is null
		  left join computed_grades cg on cg.student_id = st.id and cg.class_id = $1 and cg.term_id = $2
		                               and cg.superseded_at is null and cg.deleted_at is null
		  left join grade_scale_levels lvl on lvl.id = cg.scale_level_id
		  left join grade_scale_levels prevlvl on prevlvl.id = cg.previous_scale_level_id
		  left join attendance_records ar on ar.session_id = $3 and ar.student_id = st.id and ar.deleted_at is null
		  left join session_observations so on so.session_id = $3 and so.student_id = st.id and so.deleted_at is null
		 where sm.joined_on <= $4 and (sm.left_on is null or sm.left_on > $4) and sm.deleted_at is null
		   and ($5 = '' or (coalesce(st.given_name,'') || ' ' || coalesce(st.paternal_surname,'') || ' ' || coalesce(st.maternal_surname,'')) ilike '%' || $5 || '%')
		 order by st.paternal_surname, st.given_name
	`, classID, termID, sessionID, sessionDate, q)
	if err != nil {
		return nil, nil, err
	}

	var roster []RosterEntry
	var studentIDs []uuid.UUID
	obsByStudent := make(map[uuid.UUID]uuid.UUID)
	var obsIDs []uuid.UUID
	for rows.Next() {
		var e RosterEntry
		var obsID *uuid.UUID
		if err := rows.Scan(&e.StudentID, &e.Name, &e.LevelCode, &e.PreviousLevelCode, &e.Trend,
			&e.AttendanceStatus, &obsID, &e.ParticipationLevel, &e.ObservationNote); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if obsID != nil {
			obsByStudent[e.StudentID] = *obsID
			obsIDs = append(obsIDs, *obsID)
		}
		roster = append(roster, e)
		studentIDs = append(studentIDs, e.StudentID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}

	flagsByObs := make(map[uuid.UUID][]FlagRef)
	if len(obsIDs) > 0 {
		frows, err := tx.Query(ctx, `
			select sof.observation_id, bft.id, bft.code, bft.label, bft.severity, bft.is_positive
			  from session_observation_flags sof
			  join behavior_flag_types bft on bft.id = sof.flag_type_id
			 where sof.observation_id = any($1) and sof.deleted_at is null
		`, obsIDs)
		if err != nil {
			return nil, nil, err
		}
		for frows.Next() {
			var obsID uuid.UUID
			var f FlagRef
			if err := frows.Scan(&obsID, &f.ID, &f.Code, &f.Label, &f.Severity, &f.IsPositive); err != nil {
				frows.Close()
				return nil, nil, err
			}
			flagsByObs[obsID] = append(flagsByObs[obsID], f)
		}
		frows.Close()
		if err := frows.Err(); err != nil {
			return nil, nil, err
		}
	}

	notesByStudent := make(map[uuid.UUID][]VoiceNoteRef)
	vrows, err := tx.Query(ctx, `
		select student_id, id, duration_ms, status, transcription_status, transcript
		  from voice_notes
		 where session_id = $1 and status in ('draft','saved') and deleted_at is null
		 order by recorded_at
	`, sessionID)
	if err != nil {
		return nil, nil, err
	}
	for vrows.Next() {
		var sid uuid.UUID
		var v VoiceNoteRef
		if err := vrows.Scan(&sid, &v.ID, &v.DurationMs, &v.Status, &v.TranscriptionStatus, &v.Transcript); err != nil {
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
		if obsID, ok := obsByStudent[roster[i].StudentID]; ok {
			roster[i].Flags = flagsByObs[obsID]
		}
		roster[i].VoiceNotes = notesByStudent[roster[i].StudentID]
	}

	return roster, studentIDs, nil
}
