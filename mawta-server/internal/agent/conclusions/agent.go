// Package conclusions is Mawta's descriptive-conclusions agent. It proposes
// the conclusión descriptiva of one student in one competency and term —
// "juicio docente basado en evidencias […] Señala avances, dificultades y
// recomendaciones" (RVM 094-2020, glossary) — from the competency's criteria
// and capabilities, the student's evidences of the term and the teacher's
// voice notes, already swept of names.
//
// It is one bounded call, like the planning agent: the server gathers all
// the material, the model answers by filling a fixed schema, and every
// avance and dificultad must cite the evidences or notes it rests on. It
// never suggests or contests the level: the level is the teacher's judgement
// and is asserted first. The proposal stays in agent_generations.result until
// the teacher saves it as a conclusion; it is never saved on their behalf.
package conclusions

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

// Name is the agent_generations.agent value of this agent.
const Name = "conclusions"

// KindConclusion is what this agent generates.
const KindConclusion = "conclusion"

// promptVersion changes whenever prompts/ change.
const promptVersion = "conclusions-2026-10-09.1"

//go:embed prompts/*.md
var promptFS embed.FS

func prompt(name string) string {
	b, err := promptFS.ReadFile("prompts/" + name + ".md")
	if err != nil {
		panic("conclusions: missing prompt " + name) // embedded at build time
	}
	return string(b)
}

// TargetKey identifies a conclusion generation: one at a time per student,
// competency and term.
func TargetKey(s Scope) string {
	return fmt.Sprintf("conclusions:student:%s:comp:%s:term:%s", s.StudentID, s.CompetencyID, s.TermID)
}

// Agent is the descriptive-conclusions agent.
type Agent struct{}

// New returns the conclusions agent.
func New() *Agent { return &Agent{} }

func (a *Agent) Name() string          { return Name }
func (a *Agent) PromptVersion() string { return promptVersion }

func pointItems(description string) map[string]any {
	return map[string]any{
		"type": "array",
		"items": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"texto":      map[string]any{"type": "string", "description": description},
				"evidencias": map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "References of the evidences it rests on (E1, E2…)."},
				"notas":      map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "References of the voice notes it rests on (N1, N2…)."},
			},
			"required": []string{"texto", "evidencias", "notas"},
		},
	}
}

var conclusionTool = llm.Tool{
	Name:        "proponer_conclusion",
	Description: "Records the proposed descriptive conclusion: progress, difficulties and recommendations, each grounded in the material.",
	Properties: map[string]any{
		"avances":                    pointItems("One sentence on something the student achieved, grounded in the cited material."),
		"dificultades":               pointItems("One sentence on something the student still finds difficult, grounded in the cited material."),
		"recomendaciones":            pointItems("One personalised, actionable recommendation to keep developing the competency."),
		"justificacion_sin_progreso": map[string]any{"type": "string", "description": "Only for C in consecutive terms: why there was no progress. Empty otherwise."},
		"apoyos_brindados":           map[string]any{"type": "string", "description": "Only for inclusion support: the supports and reasonable adjustments provided. Empty otherwise."},
		"notas_no_usadas": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"nota":   map[string]any{"type": "string"},
					"motivo": map[string]any{"type": "string", "description": "Why it was not used, e.g. it is about behaviour, not this competency."},
				},
				"required": []string{"nota", "motivo"},
			},
		},
	},
	Required: []string{"avances", "dificultades", "recomendaciones", "justificacion_sin_progreso", "apoyos_brindados", "notas_no_usadas"},
}

type point struct {
	Texto      string   `json:"texto"`
	Evidencias []string `json:"evidencias"`
	Notas      []string `json:"notas"`
}

type unusedNote struct {
	Nota   string `json:"nota"`
	Motivo string `json:"motivo"`
}

type answer struct {
	Avances                  []point      `json:"avances"`
	Dificultades             []point      `json:"dificultades"`
	Recomendaciones          []point      `json:"recomendaciones"`
	JustificacionSinProgreso string       `json:"justificacion_sin_progreso"`
	ApoyosBrindados          string       `json:"apoyos_brindados"`
	NotasNoUsadas            []unusedNote `json:"notas_no_usadas"`
}

// Point is one sentence of the proposal with the ids it rests on.
type Point struct {
	Text         string      `json:"text"`
	EvidenceIDs  []uuid.UUID `json:"evidence_ids"`
	VoiceNoteIDs []uuid.UUID `json:"voice_note_ids"`
}

// UnusedVoiceNote is a note the agent read and chose not to use, and why.
type UnusedVoiceNote struct {
	VoiceNoteID uuid.UUID `json:"voice_note_id"`
	Reason      string    `json:"reason"`
}

// Result is a completed generation's proposal (agent_generations.result).
type Result struct {
	Body                    string            `json:"body"`
	Level                   string            `json:"level"`
	Requirement             string            `json:"requirement"`
	Progress                []Point           `json:"progress"`
	Difficulties            []Point           `json:"difficulties"`
	Recommendations         []Point           `json:"recommendations"`
	NoProgressJustification string            `json:"no_progress_justification,omitempty"`
	SupportsProvided        string            `json:"supports_provided,omitempty"`
	UsedVoiceNoteIDs        []uuid.UUID       `json:"used_voice_note_ids"`
	UnusedVoiceNotes        []UnusedVoiceNote `json:"unused_voice_notes"`
	Warnings                []Warning         `json:"warnings"`
}

// state is what Prepare read, handed back to Apply.
type state struct {
	Material Material
	Refs     refs
	Names    []string
}

// ScopeOf reads a generation's scope from its columns.
func ScopeOf(gen repo.AgentGeneration) (Scope, error) {
	if gen.StudentID == nil || gen.CompetencyID == nil || gen.TermID == nil {
		return Scope{}, fmt.Errorf("conclusions: generation %s has no scope", gen.ID)
	}
	return Scope{ClassID: gen.ClassID, StudentID: *gen.StudentID, CompetencyID: *gen.CompetencyID, TermID: *gen.TermID}, nil
}

func (a *Agent) Prepare(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	scope, err := ScopeOf(gen)
	if err != nil {
		return agent.Prepared{}, err
	}
	m, err := Gather(ctx, tx, scope)
	if err != nil {
		return agent.Prepared{}, err
	}
	if err := m.Check(); err != nil {
		return agent.Prepared{}, err // final: the teacher reads why
	}
	tenantID, err := repo.CurrentTenantID(ctx, tx)
	if err != nil {
		return agent.Prepared{}, err
	}
	today, err := repo.TenantToday(ctx, tx, tenantID)
	if err != nil {
		return agent.Prepared{}, err
	}
	students, err := repo.RosterNames(ctx, tx, scope.ClassID, scope.StudentID, today)
	if err != nil {
		return agent.Prepared{}, err
	}

	text, r := render(m)
	return agent.Prepared{
		Spec: &agent.Spec{
			System:    []llm.Block{{Text: prompt("conclusion"), Cache: true}},
			Prompt:    text,
			Tool:      conclusionTool,
			MaxTokens: 3000,
		},
		State: state{Material: m, Refs: r, Names: nameWords(students)},
	}, nil
}

func (a *Agent) Apply(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, raw json.RawMessage) (json.RawMessage, error) {
	st := p.State.(state)
	m := st.Material
	var ans answer
	if err := json.Unmarshal(raw, &ans); err != nil {
		return nil, agent.Invalid("la respuesta no tiene el formato de la herramienta: %v", err)
	}

	// The level may have changed while the model wrote: a conclusion that
	// explains a level the student no longer has is worse than none.
	level, err := repo.LiveCompetencyLevel(ctx, tx, m.Scope.StudentID, m.Scope.CompetencyID, m.Scope.TermID)
	if err != nil {
		return nil, err
	}
	if level == nil || *level != *m.Level {
		return nil, db.NewAppError(http.StatusUnprocessableEntity, "level_changed",
			"El nivel de logro cambió mientras Mawta escribía. Vuelve a generar la conclusión.")
	}

	res := Result{Level: *m.Level, Requirement: m.Requirement, Warnings: m.Warnings(),
		UsedVoiceNoteIDs: []uuid.UUID{}, UnusedVoiceNotes: []UnusedVoiceNote{}}
	used := map[uuid.UUID]bool{}
	convert := func(section string, in []point, mustCite bool) ([]Point, error) {
		out := make([]Point, 0, len(in))
		for _, pt := range in {
			text := clean(pt.Texto)
			if text == "" {
				continue
			}
			if why := guard(text, st.Names); why != "" {
				return nil, agent.Invalid("%s", why)
			}
			cp := Point{Text: text, EvidenceIDs: []uuid.UUID{}, VoiceNoteIDs: []uuid.UUID{}}
			for _, ref := range pt.Evidencias {
				id, ok := st.Refs.Evidences[strings.TrimSpace(ref)]
				if !ok {
					return nil, agent.Invalid("%s cita la evidencia %q, que no existe; usa solo E1…E%d", section, ref, len(st.Refs.Evidences))
				}
				cp.EvidenceIDs = append(cp.EvidenceIDs, id)
			}
			for _, ref := range pt.Notas {
				id, ok := st.Refs.VoiceNotes[strings.TrimSpace(ref)]
				if !ok {
					return nil, agent.Invalid("%s cita la nota %q, que no existe; usa solo las referencias N entregadas", section, ref)
				}
				cp.VoiceNoteIDs = append(cp.VoiceNoteIDs, id)
				if !used[id] {
					used[id] = true
					res.UsedVoiceNoteIDs = append(res.UsedVoiceNoteIDs, id)
				}
			}
			if mustCite && len(cp.EvidenceIDs)+len(cp.VoiceNoteIDs) == 0 {
				return nil, agent.Invalid("%s «%s» no cita ninguna evidencia ni nota; cada avance y dificultad debe apoyarse en el material", section, text)
			}
			out = append(out, cp)
		}
		return out, nil
	}
	if res.Progress, err = convert("un avance", ans.Avances, true); err != nil {
		return nil, err
	}
	if res.Difficulties, err = convert("una dificultad", ans.Dificultades, true); err != nil {
		return nil, err
	}
	if res.Recommendations, err = convert("una recomendación", ans.Recomendaciones, false); err != nil {
		return nil, err
	}
	if len(res.Progress)+len(res.Difficulties) == 0 {
		return nil, agent.Invalid("la conclusión no señala ningún avance ni dificultad")
	}
	if len(res.Recommendations) == 0 {
		return nil, agent.Invalid("toda conclusión debe incluir al menos una recomendación personalizada (5.1.1.3 p.7)")
	}

	res.NoProgressJustification = clean(ans.JustificacionSinProgreso)
	res.SupportsProvided = clean(ans.ApoyosBrindados)
	if m.Requirement == "consecutive_c" && res.NoProgressJustification == "" {
		return nil, agent.Invalid("el nivel es C por segundo periodo consecutivo: justificacion_sin_progreso es obligatoria")
	}
	if m.Requirement == "inclusion_support" && res.SupportsProvided == "" {
		return nil, agent.Invalid("el estudiante tiene apoyo de inclusión: apoyos_brindados es obligatorio")
	}
	for _, extra := range []string{res.NoProgressJustification, res.SupportsProvided} {
		if why := guard(extra, st.Names); why != "" {
			return nil, agent.Invalid("%s", why)
		}
	}
	for _, u := range ans.NotasNoUsadas {
		if id, ok := st.Refs.VoiceNotes[strings.TrimSpace(u.Nota)]; ok && !used[id] {
			res.UnusedVoiceNotes = append(res.UnusedVoiceNotes, UnusedVoiceNote{VoiceNoteID: id, Reason: clean(u.Motivo)})
		}
	}

	res.Body = compose(res)
	return json.Marshal(res)
}

// compose writes the conclusion as the teacher will edit it: progress,
// difficulties, the justification or supports when the norm asks for them,
// and the recommendations, one paragraph each.
func compose(r Result) string {
	var paragraphs []string
	add := func(points []Point) {
		var texts []string
		for _, p := range points {
			texts = append(texts, sentence(p.Text))
		}
		if len(texts) > 0 {
			paragraphs = append(paragraphs, strings.Join(texts, " "))
		}
	}
	add(r.Progress)
	add(r.Difficulties)
	if r.NoProgressJustification != "" {
		paragraphs = append(paragraphs, sentence(r.NoProgressJustification))
	}
	if r.SupportsProvided != "" {
		paragraphs = append(paragraphs, sentence(r.SupportsProvided))
	}
	add(r.Recommendations)
	return strings.Join(paragraphs, "\n\n")
}

// sentence ends a text with a period when it has no closing punctuation.
func sentence(s string) string {
	if s == "" || strings.ContainsAny(s[len(s)-1:], ".!?") {
		return s
	}
	return s + "."
}

// clean trims a model string and collapses inner whitespace.
func clean(s string) string { return strings.Join(strings.Fields(s), " ") }
