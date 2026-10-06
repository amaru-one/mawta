// Package planning is Mawta's planning agent, the first agent of the
// multi-agent system. It proposes, from a teacher's idea and the loaded CNEB
// curriculum, a learning experience, its evaluation criteria, its planned
// evidences and a light session outline (contract
// docs/api-planificacion.md, "Generate with Mawta").
//
// It never decides: an experience proposal is returned for review and not
// saved; criteria, evidences and sessions are saved pending
// (proposed_by = mawta) until the teacher accepts or edits them. It only fills
// gaps, only cites what the database holds, never suggests achievement
// levels, and receives no student data.
package planning

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
const Name = "planning"

// What the planning agent generates (agent_generations.kind).
const (
	KindExperience = "experience"
	KindCriteria   = "criteria"
	KindEvidences  = "evidences"
	KindSessions   = "sessions"
)

// promptVersion changes whenever the instructions in prompts/ change, so a
// generation can be traced to the prompt that produced it.
const promptVersion = "planning-2026-10-06.1"

//go:embed prompts/*.md
var promptFS embed.FS

func prompt(name string) string {
	b, err := promptFS.ReadFile("prompts/" + name + ".md")
	if err != nil {
		panic("planning: missing prompt " + name) // embedded at build time
	}
	return string(b)
}

// Agent is the planning agent.
type Agent struct{}

// New returns the planning agent.
func New() *Agent { return &Agent{} }

func (a *Agent) Name() string          { return Name }
func (a *Agent) PromptVersion() string { return promptVersion }

// ExperienceInput is what a teacher sends to get an experience proposal.
type ExperienceInput struct {
	TermID        uuid.UUID   `json:"term_id"`
	IdeaText      string      `json:"idea_text"`
	CompetencyIDs []uuid.UUID `json:"competency_ids,omitempty"`
}

// CriteriaInput is what a teacher sends to get criteria for one competency.
type CriteriaInput struct {
	CompetencyID uuid.UUID `json:"competency_id"`
}

// TargetKey identifies what a generation works on, so only one generation
// per target runs at a time (agent_generations_target_key).
func TargetKey(kind string, classID uuid.UUID, experienceID *uuid.UUID, competencyID uuid.UUID) string {
	switch kind {
	case KindExperience:
		return fmt.Sprintf("planning:class:%s:experience", classID)
	case KindCriteria:
		return fmt.Sprintf("planning:exp:%s:criteria:%s", *experienceID, competencyID)
	default:
		return fmt.Sprintf("planning:exp:%s:%s", *experienceID, kind)
	}
}

func (a *Agent) Prepare(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	switch gen.Kind {
	case KindExperience:
		return prepareExperience(ctx, tx, gen)
	case KindCriteria:
		return prepareCriteria(ctx, tx, gen)
	case KindEvidences:
		return prepareEvidences(ctx, tx, gen)
	case KindSessions:
		return prepareSessions(ctx, tx, gen)
	}
	return agent.Prepared{}, unprocessable("unknown_kind", "Mawta no sabe generar eso.")
}

func (a *Agent) Apply(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, answer json.RawMessage) (json.RawMessage, error) {
	switch gen.Kind {
	case KindExperience:
		return applyExperience(ctx, tx, gen, p, answer)
	case KindCriteria:
		return applyCriteria(ctx, tx, gen, p, answer)
	case KindEvidences:
		return applyEvidences(ctx, tx, gen, p, answer)
	case KindSessions:
		return applySessions(ctx, tx, gen, p, answer)
	}
	return nil, unprocessable("unknown_kind", "Mawta no sabe generar eso.")
}

// system builds the stable, cacheable instructions of a call: the common
// rules, the task, and the class context that repeats across calls.
func system(task, context string) []llm.Block {
	blocks := []llm.Block{{Text: prompt("common") + "\n\n" + prompt(task), Cache: context == ""}}
	if context != "" {
		blocks = append(blocks, llm.Block{Text: context, Cache: true})
	}
	return blocks
}

func unprocessable(code, message string) error {
	return db.NewAppError(http.StatusUnprocessableEntity, code, message)
}

// decode parses the model's answer; a malformed answer is invalid, which
// earns the model one repair attempt.
func decode(answer json.RawMessage, v any) error {
	if err := json.Unmarshal(answer, v); err != nil {
		return agent.Invalid("la respuesta no tiene el formato de la herramienta: %v", err)
	}
	return nil
}

func result(v any) (json.RawMessage, error) {
	b, err := json.Marshal(v)
	return json.RawMessage(b), err
}

func experienceID(gen repo.AgentGeneration) (uuid.UUID, error) {
	if gen.ExperienceID == nil {
		return uuid.Nil, unprocessable("bad_request", "esta generación necesita una experiencia")
	}
	return *gen.ExperienceID, nil
}

// clean trims a model string and collapses inner whitespace.
func clean(s string) string { return strings.Join(strings.Fields(s), " ") }
