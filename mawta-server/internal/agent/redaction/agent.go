// Package redaction is Mawta's name sweep over voice-note transcripts. A
// teacher speaks freely about a student and may name the student, classmates,
// relatives or other teachers, and speech-to-text misspells names; none of
// that may reach the descriptive-conclusions agent or a SIAGIE text.
//
// The sweep is done by a model, because recognising a misspelled name or a
// nickname needs context: it reads the transcript with the assigned student's
// names and the section roster, and points at every reference to a person.
// It never rewrites the transcript. The server checks each fragment against
// the transcript, replaces it ([ESTUDIANTE], [COMPAÑERO_n], [PERSONA]),
// records one voice_note_redactions row per replacement, and decides from the
// references whether the note belongs to its assigned student.
package redaction

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/repo"
)

// Name is the agent_generations.agent value of this agent.
const Name = "redaction"

// KindVoiceNote is the only thing this agent sweeps.
const KindVoiceNote = "voice_note"

// promptVersion changes whenever prompts/ change.
const promptVersion = "redaction-2026-10-09.1"

//go:embed prompts/*.md
var promptFS embed.FS

func prompt(name string) string {
	b, err := promptFS.ReadFile("prompts/" + name + ".md")
	if err != nil {
		panic("redaction: missing prompt " + name) // embedded at build time
	}
	return string(b)
}

// Input is what a sweep generation carries: only whether a teacher moved the
// note, never the transcript.
type Input struct {
	Reassigned bool `json:"reassigned"`
}

// Agent is the redaction sweep.
type Agent struct{}

// New returns the redaction agent.
func New() *Agent { return &Agent{} }

func (a *Agent) Name() string          { return Name }
func (a *Agent) PromptVersion() string { return promptVersion }

// TargetKey identifies a sweep. It includes the student, so a note moved to
// another student is swept again even while an earlier sweep is in flight.
func TargetKey(voiceNoteID, studentID uuid.UUID) string {
	return fmt.Sprintf("redaction:voice_note:%s:student:%s", voiceNoteID, studentID)
}

// Queue starts the sweep of a voice note in the caller's transaction. A note
// without a transcript yet is left alone (its transcription queues it later);
// a blank transcript is discarded as unreadable without calling the model.
func Queue(ctx context.Context, tx pgx.Tx, tenantID uuid.UUID, note repo.VoiceNoteForRedaction, requestedBy uuid.UUID, reassigned bool) error {
	if note.Transcript == nil {
		return nil
	}
	if strings.TrimSpace(*note.Transcript) == "" {
		reason := repo.DiscardUnreadable
		return repo.SetVoiceNoteAttribution(ctx, tx, note.ID, nil, repo.AttributionDiscarded, &reason)
	}
	input, _ := json.Marshal(Input{Reassigned: reassigned})
	studentID, voiceNoteID := note.StudentID, note.ID
	_, err := agent.Enqueue(ctx, tx, tenantID, repo.NewGeneration{
		Agent:       Name,
		Kind:        KindVoiceNote,
		ClassID:     note.ClassID,
		StudentID:   &studentID,
		VoiceNoteID: &voiceNoteID,
		RequestedBy: requestedBy,
		TargetKey:   TargetKey(note.ID, note.StudentID),
		Input:       input,
	})
	return err
}

// QueueAfterTranscript is the hook the transcription job runs once a
// transcript is saved: it queues the sweep, requested by the teacher who
// recorded the note.
func QueueAfterTranscript(ctx context.Context, tx pgx.Tx, voiceNoteID uuid.UUID) error {
	note, err := repo.GetVoiceNoteForRedaction(ctx, tx, voiceNoteID)
	if err != nil {
		return err
	}
	tenantID, err := repo.CurrentTenantID(ctx, tx)
	if err != nil {
		return err
	}
	return Queue(ctx, tx, tenantID, note, note.TeacherID, false)
}

var sweepTool = llm.Tool{
	Name:        "marcar_personas",
	Description: "Points at every reference to a person in the transcript. Never rewrites the transcript.",
	Properties: map[string]any{
		"fragments": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"text": map[string]any{"type": "string",
						"description": "The words exactly as they appear in the transcript, including misspellings."},
					"refers_to": map[string]any{"type": "string",
						"enum": []string{repo.RefersToAssignedStudent, repo.RefersToClassmate, repo.RefersToOtherPerson}},
					"student_key": map[string]any{"type": "string",
						"description": "For a classmate, its key (S1, S2…). Empty otherwise."},
				},
				"required": []string{"text", "refers_to", "student_key"},
			},
		},
		"unreadable": map[string]any{"type": "boolean",
			"description": "True only when the transcript is noise or has no recognisable meaning."},
	},
	Required: []string{"fragments", "unreadable"},
}

type answer struct {
	Fragments  []fragment `json:"fragments"`
	Unreadable bool       `json:"unreadable"`
}

// state is what Prepare read, handed back to Apply.
type state struct {
	VoiceNoteID uuid.UUID
	StudentID   uuid.UUID
	Transcript  string
	Reassigned  bool
	// Classmates maps each roster key the model sees to the student.
	Classmates map[string]uuid.UUID
}

const assignedKey = "S0"

func (a *Agent) Prepare(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	if gen.VoiceNoteID == nil {
		return agent.Prepared{}, fmt.Errorf("redaction: generation %s has no voice note", gen.ID)
	}
	var in Input
	_ = json.Unmarshal(gen.Input, &in)

	note, err := repo.GetVoiceNoteForRedaction(ctx, tx, *gen.VoiceNoteID)
	if err != nil {
		return agent.Prepared{}, err // a deleted note is final (pgx.ErrNoRows)
	}
	if gen.StudentID != nil && note.StudentID != *gen.StudentID {
		// Moved to another student since this sweep was queued; the move
		// queued its own sweep.
		return agent.Prepared{Result: json.RawMessage(`{"skipped":"reassigned"}`)}, nil
	}
	if note.Transcript == nil || strings.TrimSpace(*note.Transcript) == "" {
		return agent.Prepared{Result: json.RawMessage(`{"skipped":"no_transcript"}`)}, nil
	}

	roster, err := repo.RosterAsOf(ctx, tx, note.ClassID, note.RecordedAt)
	if err != nil {
		return agent.Prepared{}, err
	}
	ids := append([]uuid.UUID{note.StudentID}, roster...)
	names, err := repo.StudentNames(ctx, tx, ids)
	if err != nil {
		return agent.Prepared{}, err
	}

	st := state{VoiceNoteID: note.ID, StudentID: note.StudentID, Transcript: *note.Transcript,
		Reassigned: in.Reassigned, Classmates: map[string]uuid.UUID{}}
	var b strings.Builder
	b.WriteString("Assigned student (the note was recorded about this student):\n")
	for _, n := range names {
		if n.ID == note.StudentID {
			fmt.Fprintf(&b, "- %s: %s\n", assignedKey, describe(n))
		}
	}
	b.WriteString("\nClassmates in the same section:\n")
	k := 0
	for _, n := range names {
		if n.ID == note.StudentID {
			continue
		}
		k++
		key := fmt.Sprintf("S%d", k)
		st.Classmates[key] = n.ID
		fmt.Fprintf(&b, "- %s: %s\n", key, describe(n))
	}
	if k == 0 {
		b.WriteString("- (none)\n")
	}
	fmt.Fprintf(&b, "\n<transcript>\n%s\n</transcript>\n", st.Transcript)

	return agent.Prepared{
		Spec: &agent.Spec{
			System:    []llm.Block{{Text: prompt("redaction"), Cache: true}},
			Prompt:    b.String(),
			Tool:      sweepTool,
			MaxTokens: 2000,
		},
		State: st,
	}, nil
}

// describe lists every name a teacher might use for a student.
func describe(n repo.StudentName) string {
	parts := []string{"given name " + n.GivenName}
	if n.PreferredName != nil && strings.TrimSpace(*n.PreferredName) != "" {
		parts = append(parts, "goes by "+*n.PreferredName)
	}
	surnames := n.PaternalSurname
	if n.MaternalSurname != nil && *n.MaternalSurname != "" {
		surnames += " " + *n.MaternalSurname
	}
	parts = append(parts, "surnames "+surnames)
	return strings.Join(parts, "; ")
}

func (a *Agent) Apply(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, raw json.RawMessage) (json.RawMessage, error) {
	st := p.State.(state)
	var ans answer
	if err := json.Unmarshal(raw, &ans); err != nil {
		return nil, agent.Invalid("la respuesta no tiene el formato de la herramienta: %v", err)
	}
	for i := range ans.Fragments {
		f := &ans.Fragments[i]
		f.Text = strings.TrimSpace(f.Text)
		f.StudentKey = strings.TrimSpace(f.StudentKey)
		if f.Text == "" {
			return nil, agent.Invalid("un fragmento viene vacío")
		}
		switch f.RefersTo {
		case repo.RefersToClassmate:
			if _, ok := st.Classmates[f.StudentKey]; !ok {
				return nil, agent.Invalid("el fragmento %q es de un compañero pero student_key %q no está en la lista", f.Text, f.StudentKey)
			}
		case repo.RefersToAssignedStudent, repo.RefersToOtherPerson:
			f.StudentKey = ""
		default:
			return nil, agent.Invalid("refers_to %q no es válido", f.RefersTo)
		}
	}

	// The note may have changed while the model answered: never write a
	// sweep of a transcript or a student it no longer has.
	note, err := repo.GetVoiceNoteForRedaction(ctx, tx, st.VoiceNoteID)
	if err != nil {
		return nil, err
	}
	if note.StudentID != st.StudentID || note.Transcript == nil || *note.Transcript != st.Transcript {
		return json.RawMessage(`{"skipped":"note_changed"}`), nil
	}

	runes := []rune(st.Transcript)
	var spans []span
	if !ans.Unreadable {
		spans, err = locate(runes, ans.Fragments)
		if err != nil {
			return nil, agent.Invalid("%s", err.Error())
		}
	}
	status, reason := attribution(spans, ans.Unreadable, st.Reassigned)

	if err := repo.SupersedeVoiceNoteRedactions(ctx, tx, st.VoiceNoteID); err != nil {
		return nil, err
	}
	var redacted *string
	if !ans.Unreadable {
		text, tokens := redact(runes, spans)
		redacted = &text
		for i, s := range spans {
			row := repo.VoiceNoteRedaction{
				VoiceNoteID:  st.VoiceNoteID,
				GenerationID: gen.ID,
				StudentID:    st.StudentID,
				OriginalText: string(runes[s.start:s.end]),
				StartOffset:  s.start,
				EndOffset:    s.end,
				Replacement:  tokens[i],
				RefersTo:     s.frag.RefersTo,
			}
			if s.frag.RefersTo == repo.RefersToClassmate {
				id := st.Classmates[s.frag.StudentKey]
				row.MatchedStudentID = &id
			}
			if err := repo.InsertVoiceNoteRedaction(ctx, tx, row); err != nil {
				return nil, err
			}
		}
	}
	if err := repo.SetVoiceNoteAttribution(ctx, tx, st.VoiceNoteID, redacted, status, reason); err != nil {
		return nil, err
	}

	action := "voice_note.redacted"
	if status == repo.AttributionDiscarded {
		action = "voice_note.attribution_discarded"
	}
	payload, _ := json.Marshal(map[string]any{"attribution_status": status, "discard_reason": reason, "replacements": len(spans)})
	vid, sid, cid := st.VoiceNoteID, st.StudentID, gen.ClassID
	if err := repo.LogEvent(ctx, tx, action, "voice_note", &vid, payload, &sid, &cid, nil); err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{
		"replacements":       len(spans),
		"attribution_status": status,
		"discard_reason":     reason,
	})
}
