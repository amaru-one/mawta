package conclusions

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

// MinGradedEvidences is the least evidence a conclusion can stand on: the
// teacher-asserted level plus this many distinct evidences with a live
// graded score, read against the competency's criteria in the term. Voice
// notes never count toward it: they complement, they do not ground.
const MinGradedEvidences = 2

// Scope is what one conclusion is about. It always comes from the server
// (the request path or the generation's columns), never from the model.
type Scope struct {
	ClassID      uuid.UUID
	StudentID    uuid.UUID
	CompetencyID uuid.UUID
	TermID       uuid.UUID
}

// Material is everything the agent may read for one scope.
type Material struct {
	Scope       Scope
	Level       *string
	Requirement string
	Competency  repo.CompetencyBrief
	Evidences   []repo.ConclusionEvidence
	VoiceNotes  []repo.ConclusionVoiceNote
	NoteCounts  repo.VoiceNoteCounts
	Earlier     []repo.EarlierTermConclusion
	Graded      int
}

// Gather reads the material of a scope.
func Gather(ctx context.Context, tx pgx.Tx, s Scope) (Material, error) {
	m := Material{Scope: s}
	var err error
	if m.Level, err = repo.LiveCompetencyLevel(ctx, tx, s.StudentID, s.CompetencyID, s.TermID); err != nil {
		return m, err
	}
	if m.Requirement, err = repo.ConclusionRequirement(ctx, tx, s.ClassID, s.StudentID, s.CompetencyID, s.TermID); err != nil {
		return m, err
	}
	if m.Competency, err = repo.GetCompetencyBrief(ctx, tx, s.CompetencyID); err != nil {
		return m, err
	}
	if m.Evidences, err = repo.ListConclusionEvidence(ctx, tx, s.ClassID, s.StudentID, s.CompetencyID, s.TermID); err != nil {
		return m, err
	}
	if m.VoiceNotes, m.NoteCounts, err = repo.ListConclusionVoiceNotes(ctx, tx, s.ClassID, s.StudentID, s.TermID); err != nil {
		return m, err
	}
	if m.Earlier, err = repo.ListEarlierTermConclusions(ctx, tx, s.StudentID, s.CompetencyID, s.TermID); err != nil {
		return m, err
	}
	for _, e := range m.Evidences {
		if e.Graded() {
			m.Graded++
		}
	}
	return m, nil
}

// Errors a teacher reads when a conclusion cannot be proposed.
var (
	ErrLevelRequired = db.NewAppError(http.StatusUnprocessableEntity, "level_required",
		"Primero registra el nivel de logro de esta competencia: la conclusión explica ese nivel.")
	ErrInsufficientEvidence = db.NewAppError(http.StatusUnprocessableEntity, "insufficient_evidence",
		fmt.Sprintf("Hay poca evidencia para esta competencia: Mawta necesita al menos %d evidencias valoradas. Puedes escribir la conclusión a mano.", MinGradedEvidences))
)

// Check says whether the material is enough to propose a conclusion.
func (m Material) Check() error {
	if m.Level == nil {
		return ErrLevelRequired
	}
	if m.Graded < MinGradedEvidences {
		return ErrInsufficientEvidence
	}
	return nil
}

// Warning is something the teacher should know about a proposal, frozen at
// generation time so it matches what the agent actually read.
type Warning struct {
	Code  string `json:"code"`
	Count int    `json:"count,omitempty"`
}

// Warning codes.
const (
	// Some notes were discarded but others were used: the teacher is told
	// how many, and does not see them.
	WarnVoiceNotesDiscarded = "voice_notes_discarded"
	// Every note of the student was discarded: the worst case, the only one
	// where the teacher is shown the discarded notes to move or confirm.
	WarnAllVoiceNotesDiscarded = "all_voice_notes_discarded"
	WarnVoiceNotesPending      = "voice_notes_pending"
	// No note at all: the proposal is less precise.
	WarnNoVoiceNotes = "no_voice_notes"
)

// OnlyDiscardedNotes reports the worst case: the student has voice notes in
// the term, and the sweep discarded every one of them.
func (m Material) OnlyDiscardedNotes() bool {
	return len(m.VoiceNotes) == 0 && m.NoteCounts.Discarded > 0
}

// Warnings lists what the teacher should know about this material.
func (m Material) Warnings() []Warning {
	out := []Warning{}
	switch {
	case m.OnlyDiscardedNotes():
		out = append(out, Warning{Code: WarnAllVoiceNotesDiscarded, Count: m.NoteCounts.Discarded})
	case m.NoteCounts.Discarded > 0:
		out = append(out, Warning{Code: WarnVoiceNotesDiscarded, Count: m.NoteCounts.Discarded})
	}
	if m.NoteCounts.Pending > 0 {
		out = append(out, Warning{Code: WarnVoiceNotesPending, Count: m.NoteCounts.Pending})
	}
	if len(m.VoiceNotes) == 0 && m.NoteCounts.Discarded == 0 {
		out = append(out, Warning{Code: WarnNoVoiceNotes})
	}
	return out
}

// refs are the short references the model cites (E1, N1, C1) and the ids
// they stand for. Short references are easier to copy exactly than UUIDs,
// and the model never sees an id it could carry elsewhere.
type refs struct {
	Evidences    map[string]uuid.UUID
	VoiceNotes   map[string]uuid.UUID
	Capabilities map[uuid.UUID]string
}

var requirementText = map[string]string{
	"level_c":           "The level is C, so the conclusion is mandatory.",
	"level_b":           "The level is B and, at this stage, the conclusion is mandatory.",
	"level_a":           "The level is A and, at this stage, the conclusion is mandatory.",
	"cycle_i_mandatory": "Every competency carries a conclusion at this stage.",
	"consecutive_c":     "The level is C for the second consecutive term. The conclusion is mandatory AND must justify why there was no progress (fill justificacion_sin_progreso).",
	"inclusion_support": "The student faces barriers to learning and receives inclusion support. The conclusion is mandatory every term AND must state the supports and reasonable adjustments provided (fill apoyos_brindados).",
	"optional":          "The conclusion is optional here; the teacher asked for one.",
}

// render writes the material as the user message, and the references it used.
func render(m Material) (string, refs) {
	r := refs{Evidences: map[string]uuid.UUID{}, VoiceNotes: map[string]uuid.UUID{}, Capabilities: map[uuid.UUID]string{}}
	var b strings.Builder

	fmt.Fprintf(&b, "Competency: %s — %s\n", m.Competency.Code, m.Competency.Name)
	if m.Competency.Description != nil && *m.Competency.Description != "" {
		fmt.Fprintf(&b, "Description: %s\n", *m.Competency.Description)
	}
	b.WriteString("Capabilities:\n")
	for i, c := range m.Competency.Capabilities {
		key := "C" + strconv.Itoa(i+1)
		r.Capabilities[c.ID] = key
		fmt.Fprintf(&b, "- %s: %s\n", key, c.Name)
	}
	fmt.Fprintf(&b, "\nAchievement level asserted by the teacher for this term: %s\n", *m.Level)
	fmt.Fprintf(&b, "%s\n", requirementText[m.Requirement])

	b.WriteString("\n<evidences>\n")
	for i, e := range m.Evidences {
		key := "E" + strconv.Itoa(i+1)
		r.Evidences[key] = e.ID
		fmt.Fprintf(&b, "- %s: «%s» (%s). Result for [ESTUDIANTE]: %s\n", key, e.Title, kindText(e.Kind), scoreText(e))
		if e.Description != nil && *e.Description != "" {
			fmt.Fprintf(&b, "  What it asked: %s\n", *e.Description)
		}
		for _, c := range e.Criteria {
			var caps []string
			for _, id := range c.CapabilityIDs {
				if k, ok := r.Capabilities[id]; ok {
					caps = append(caps, k)
				}
			}
			fmt.Fprintf(&b, "  Criterion: %s", c.Description)
			if len(caps) > 0 {
				fmt.Fprintf(&b, " (looks at %s)", strings.Join(caps, ", "))
			}
			b.WriteString("\n")
		}
		if e.Feedback != nil && strings.TrimSpace(*e.Feedback) != "" {
			fmt.Fprintf(&b, "  Teacher's feedback: %s\n", strings.TrimSpace(*e.Feedback))
		}
	}
	b.WriteString("</evidences>\n")

	b.WriteString("\n<voice_notes>\n")
	if len(m.VoiceNotes) == 0 {
		b.WriteString("(none)\n")
	}
	for i, n := range m.VoiceNotes {
		key := "N" + strconv.Itoa(i+1)
		r.VoiceNotes[key] = n.ID
		fmt.Fprintf(&b, "- %s (%s", key, n.RecordedAt.Format("2006-01-02"))
		if n.SessionTopic != nil && *n.SessionTopic != "" {
			fmt.Fprintf(&b, ", session «%s»", *n.SessionTopic)
		}
		fmt.Fprintf(&b, "): %s\n", n.TranscriptRedacted)
	}
	b.WriteString("</voice_notes>\n")

	if len(m.Earlier) > 0 {
		b.WriteString("\n<earlier_terms>\n")
		for _, e := range m.Earlier {
			level := "no level"
			if e.Level != nil {
				level = "level " + *e.Level
			}
			fmt.Fprintf(&b, "- %s: %s", e.TermName, level)
			if e.Body != nil && *e.Body != "" {
				fmt.Fprintf(&b, ". Conclusion: %s", *e.Body)
			}
			b.WriteString("\n")
		}
		b.WriteString("</earlier_terms>\n")
	}
	return b.String(), r
}

func kindText(kind string) string {
	if kind == "actuacion" {
		return "actuación: something the students did in front of others"
	}
	return "producción: something the students made"
}

func scoreText(e repo.ConclusionEvidence) string {
	if e.ScoreStatus == nil {
		return "not assessed yet"
	}
	switch *e.ScoreStatus {
	case "graded":
		if e.ScaleLevel != nil {
			return "level " + *e.ScaleLevel + " on this evidence"
		}
		if e.RawValue != nil && e.MaxValue != nil {
			return fmt.Sprintf("%s out of %s", trimFloat(*e.RawValue), trimFloat(*e.MaxValue))
		}
		return "assessed"
	case "not_submitted":
		return "did not submit it"
	case "absent":
		return "was absent"
	case "excused":
		return "excused"
	}
	return *e.ScoreStatus
}

func trimFloat(f float64) string { return strconv.FormatFloat(f, 'f', -1, 64) }
