package repo

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// What the descriptive-conclusions agent reads about one student, one
// competency and one term. Every query is scoped by the ids the server put on
// the generation, never by anything the model asked for.

// ConclusionRequirement classifies why a conclusion is (or is not) mandatory
// for this competency, student and period (see classifyConclusionRequirement).
func ConclusionRequirement(ctx context.Context, tx pgx.Tx, classID, studentID, competencyID, termID uuid.UUID) (string, error) {
	return conclusionRequirement(ctx, tx, classID, studentID, competencyID, termID)
}

// CompetencyInClass reports whether a competency belongs to the área the
// class teaches.
func CompetencyInClass(ctx context.Context, tx pgx.Tx, classID, competencyID uuid.UUID) (bool, error) {
	var ok bool
	err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from competencies c
		    join courses co on co.subject_id = c.subject_id
		    join classes cl on cl.course_id = co.id
		   where cl.id = $1 and c.id = $2 and c.deleted_at is null)
	`, classID, competencyID).Scan(&ok)
	return ok, err
}

// LiveCompetencyLevel is the level a teacher asserted for this student,
// competency and term, or nil when there is none yet.
func LiveCompetencyLevel(ctx context.Context, tx pgx.Tx, studentID, competencyID, termID uuid.UUID) (*string, error) {
	var code string
	err := tx.QueryRow(ctx, `
		select l.code from competency_term_levels ctl
		  join grade_scale_levels l on l.id = ctl.scale_level_id
		 where ctl.student_id = $1 and ctl.competency_id = $2 and ctl.term_id = $3
		   and ctl.superseded_at is null and ctl.deleted_at is null
	`, studentID, competencyID, termID).Scan(&code)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &code, nil
}

// CompetencyBrief is a competency and its capabilities.
type CompetencyBrief struct {
	ID           uuid.UUID
	Code         string
	Name         string
	Description  *string
	Capabilities []CapabilityBrief
}

// CapabilityBrief is one capability of a competency.
type CapabilityBrief struct {
	ID   uuid.UUID
	Code string
	Name string
}

// GetCompetencyBrief reads a competency with its active capabilities.
func GetCompetencyBrief(ctx context.Context, tx pgx.Tx, competencyID uuid.UUID) (CompetencyBrief, error) {
	var c CompetencyBrief
	if err := tx.QueryRow(ctx, `
		select id, code, name, description from competencies where id = $1 and deleted_at is null
	`, competencyID).Scan(&c.ID, &c.Code, &c.Name, &c.Description); err != nil {
		return c, err
	}
	rows, err := tx.Query(ctx, `
		select id, code, name from capabilities
		 where competency_id = $1 and is_active and deleted_at is null
		 order by sort_order, code
	`, competencyID)
	if err != nil {
		return c, err
	}
	defer rows.Close()
	for rows.Next() {
		var k CapabilityBrief
		if err := rows.Scan(&k.ID, &k.Code, &k.Name); err != nil {
			return c, err
		}
		c.Capabilities = append(c.Capabilities, k)
	}
	return c, rows.Err()
}

// ConclusionEvidence is one evidence of the term that is read against a
// criterion of the competency, with this student's live score.
type ConclusionEvidence struct {
	ID          uuid.UUID
	Title       string
	Description *string
	Kind        string
	ValueScale  string
	DueAt       *time.Time
	// ScoreStatus is nil when the student has no live score yet.
	ScoreStatus *string
	RawValue    *float64
	MaxValue    *float64
	ScaleLevel  *string
	Feedback    *string
	// ExperienceID is the learning experience the evidence was planned in; nil
	// for an evidence the teacher registered by hand.
	ExperienceID *uuid.UUID
	Criteria     []ConclusionCriterion
}

// MinConclusionEvidences is the least number of graded evidences a conclusion
// can stand on, per student, competency and term. Planning warns below it too.
const MinConclusionEvidences = 2

// Graded reports whether the evidence carries a value for this student.
func (e ConclusionEvidence) Graded() bool {
	return e.ScoreStatus != nil && *e.ScoreStatus == "graded"
}

// ConclusionCriterion is a criterion of the competency an evidence is read
// against, with the capabilities it looks at.
type ConclusionCriterion struct {
	ID            uuid.UUID
	Description   string
	CapabilityIDs []uuid.UUID
}

// ListConclusionEvidence lists the published evidences of a class and term
// that apply to the student and are read against at least one criterion of
// the competency. Only that competency's criteria are attached, and the
// score's feedback is included: it is the teacher's own words about the work.
func ListConclusionEvidence(ctx context.Context, tx pgx.Tx, classID, studentID, competencyID, termID uuid.UUID) ([]ConclusionEvidence, error) {
	rows, err := tx.Query(ctx, `
		select a.id, a.title, a.description, a.kind, a.value_scale, a.due_at,
		       s.status, s.raw_value::float8, s.max_value::float8, l.code, s.feedback, pe.experience_id
		  from assessments a
		  left join scores s on s.assessment_id = a.id and s.student_id = $2
		                    and s.superseded_at is null and s.deleted_at is null
		  left join grade_scale_levels l on l.id = s.scale_level_id
		  left join planned_evidences pe on pe.id = a.planned_evidence_id and pe.deleted_at is null
		 where a.class_id = $1 and a.term_id = $4
		   and a.status in ('published', 'closed') and a.deleted_at is null
		   and (a.student_id is null or a.student_id = $2)
		   and exists (
		     select 1 from assessment_criteria ac
		       join evaluation_criteria ec on ec.id = ac.criterion_id
		      where ac.assessment_id = a.id and ec.competency_id = $3 and ec.deleted_at is null)
		 order by coalesce(a.due_at, a.created_at), a.id
	`, classID, studentID, competencyID, termID)
	if err != nil {
		return nil, err
	}
	var out []ConclusionEvidence
	index := map[uuid.UUID]int{}
	for rows.Next() {
		var e ConclusionEvidence
		if err := rows.Scan(&e.ID, &e.Title, &e.Description, &e.Kind, &e.ValueScale, &e.DueAt,
			&e.ScoreStatus, &e.RawValue, &e.MaxValue, &e.ScaleLevel, &e.Feedback, &e.ExperienceID); err != nil {
			rows.Close()
			return nil, err
		}
		index[e.ID] = len(out)
		out = append(out, e)
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(out) == 0 {
		return out, err
	}

	ids := make([]uuid.UUID, 0, len(out))
	for _, e := range out {
		ids = append(ids, e.ID)
	}
	// Capabilities come from evaluation_criterion_capabilities (N:M); a
	// criterion without rows there falls back to its own capability_id.
	crit, err := tx.Query(ctx, `
		select ac.assessment_id, ec.id, ec.description,
		       coalesce(
		         (select array_agg(ecc.capability_id order by ecc.capability_id)
		            from evaluation_criterion_capabilities ecc
		           where ecc.criterion_id = ec.id and ecc.deleted_at is null),
		         array[ec.capability_id])
		  from assessment_criteria ac
		  join evaluation_criteria ec on ec.id = ac.criterion_id
		 where ac.assessment_id = any($1) and ec.competency_id = $2 and ec.deleted_at is null
		 order by ac.assessment_id, ec.sort_order, ec.id
	`, ids, competencyID)
	if err != nil {
		return nil, err
	}
	defer crit.Close()
	for crit.Next() {
		var assessmentID uuid.UUID
		var c ConclusionCriterion
		if err := crit.Scan(&assessmentID, &c.ID, &c.Description, &c.CapabilityIDs); err != nil {
			return nil, err
		}
		i := index[assessmentID]
		out[i].Criteria = append(out[i].Criteria, c)
	}
	return out, crit.Err()
}

// ConclusionVoiceNote is a usable voice note of the student in the term, as
// the agent may read it: only the redacted transcript.
type ConclusionVoiceNote struct {
	ID                 uuid.UUID
	RecordedAt         time.Time
	SessionTopic       *string
	TranscriptRedacted string
}

// VoiceNoteCounts are the notes of a student in a term the agent does not
// read, so the teacher can be told.
type VoiceNoteCounts struct {
	Discarded int
	Pending   int
}

// ListConclusionVoiceNotes lists the student's swept, usable voice notes of
// the class in the term, oldest first, and counts the discarded ones and the
// ones not swept yet (still transcribing or waiting for the sweep).
func ListConclusionVoiceNotes(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) ([]ConclusionVoiceNote, VoiceNoteCounts, error) {
	var counts VoiceNoteCounts
	rows, err := tx.Query(ctx, `
		select vn.id, vn.recorded_at, cs.topic, vn.transcript_redacted, vn.attribution_status,
		       vn.transcription_status
		  from voice_notes vn
		  join class_sessions cs on cs.id = vn.session_id
		 where vn.class_id = $1 and vn.student_id = $2 and cs.term_id = $3
		   and vn.deleted_at is null
		 order by vn.recorded_at, vn.id
	`, classID, studentID, termID)
	if err != nil {
		return nil, counts, err
	}
	defer rows.Close()
	var out []ConclusionVoiceNote
	for rows.Next() {
		var n ConclusionVoiceNote
		var redacted *string
		var status, transcription string
		if err := rows.Scan(&n.ID, &n.RecordedAt, &n.SessionTopic, &redacted, &status, &transcription); err != nil {
			return nil, counts, err
		}
		switch {
		case status == AttributionDiscarded:
			counts.Discarded++
		case status == AttributionPending:
			// Failed or skipped transcriptions will never be swept: they are
			// not "in process", just absent.
			if transcription != "failed" && transcription != "skipped" {
				counts.Pending++
			}
		case redacted != nil && *redacted != "":
			n.TranscriptRedacted = *redacted
			out = append(out, n)
		}
	}
	return out, counts, rows.Err()
}

// DiscardedVoiceNote is a note the sweep discarded, shown to the teacher only
// when discarding it leaves too little evidence. The teacher recorded it, so
// the original transcript is shown.
type DiscardedVoiceNote struct {
	ID            uuid.UUID `json:"id"`
	RecordedAt    time.Time `json:"recorded_at"`
	DurationMs    int32     `json:"duration_ms"`
	Transcript    *string   `json:"transcript"`
	DiscardReason string    `json:"discard_reason"`
}

// ListDiscardedVoiceNotes lists the student's discarded notes in a class and
// term, newest first.
func ListDiscardedVoiceNotes(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) ([]DiscardedVoiceNote, error) {
	rows, err := tx.Query(ctx, `
		select vn.id, vn.recorded_at, vn.duration_ms, vn.transcript, vn.discard_reason
		  from voice_notes vn
		  join class_sessions cs on cs.id = vn.session_id
		 where vn.class_id = $1 and vn.student_id = $2 and cs.term_id = $3
		   and vn.deleted_at is null and vn.attribution_status = 'discarded'
		 order by vn.recorded_at desc, vn.id
	`, classID, studentID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []DiscardedVoiceNote{}
	for rows.Next() {
		var n DiscardedVoiceNote
		if err := rows.Scan(&n.ID, &n.RecordedAt, &n.DurationMs, &n.Transcript, &n.DiscardReason); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

// EarlierTermConclusion is the level and conclusion of the same competency in
// an earlier term of the same academic year.
type EarlierTermConclusion struct {
	TermName string
	Sequence int16
	Level    *string
	Body     *string
}

// ListEarlierTermConclusions lists, oldest first, the student's live level
// and conclusion for the competency in the terms before termID in the same
// academic year. A justification for consecutive C needs them.
func ListEarlierTermConclusions(ctx context.Context, tx pgx.Tx, studentID, competencyID, termID uuid.UUID) ([]EarlierTermConclusion, error) {
	rows, err := tx.Query(ctx, `
		select pt.name, pt.sequence, l.code, dc.body
		  from terms t
		  join terms pt on pt.academic_year_id = t.academic_year_id
		               and coalesce(pt.stage, '') = coalesce(t.stage, '')
		               and pt.sequence < t.sequence and pt.deleted_at is null
		  left join competency_term_levels ctl
		         on ctl.term_id = pt.id and ctl.student_id = $1 and ctl.competency_id = $2
		        and ctl.superseded_at is null and ctl.deleted_at is null
		  left join grade_scale_levels l on l.id = ctl.scale_level_id
		  left join descriptive_conclusions dc
		         on dc.term_id = pt.id and dc.student_id = $1 and dc.competency_id = $2
		        and dc.superseded_at is null and dc.deleted_at is null
		 where t.id = $3
		 order by pt.sequence
	`, studentID, competencyID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []EarlierTermConclusion
	for rows.Next() {
		var e EarlierTermConclusion
		if err := rows.Scan(&e.TermName, &e.Sequence, &e.Level, &e.Body); err != nil {
			return nil, err
		}
		if e.Level != nil || e.Body != nil {
			out = append(out, e)
		}
	}
	return out, rows.Err()
}

// RosterNames are every name of the students on a class's roster today and
// of the given student, for the final check that a proposed conclusion names
// no one.
func RosterNames(ctx context.Context, tx pgx.Tx, classID, studentID uuid.UUID, today time.Time) ([]StudentName, error) {
	ids, err := RosterAsOf(ctx, tx, classID, today)
	if err != nil {
		return nil, err
	}
	return StudentNames(ctx, tx, append(ids, studentID))
}
