package repo

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
)

// AgentGeneration is one "✦ Generar con Mawta" request and its outcome
// (agent_generations). The agents share this table: Agent says which
// one serves the request and Kind what it generates.
type AgentGeneration struct {
	ID           uuid.UUID
	Agent        string
	Kind         string
	ClassID      uuid.UUID
	ExperienceID *uuid.UUID
	StudentID    *uuid.UUID
	CompetencyID *uuid.UUID
	TermID       *uuid.UUID
	VoiceNoteID  *uuid.UUID
	RequestedBy  uuid.UUID
	TargetKey    string
	Status       string
	Input        json.RawMessage
	Result       json.RawMessage
	Error        *string
	Attempts     int16
	DeadlineAt   time.Time
	CreatedAt    time.Time
	FinishedAt   *time.Time
}

// Generation statuses.
const (
	GenerationPending   = "pending"
	GenerationRunning   = "running"
	GenerationCompleted = "completed"
	GenerationFailed    = "failed"
)

// ExpiredGenerationMessage is what a teacher reads when a generation ran past
// its deadline without finishing (a worker that died, a queue that stalled).
const ExpiredGenerationMessage = "Mawta tardó demasiado en responder. Intenta de nuevo o escríbelo a mano."

// Expired reports whether an unfinished generation is past its deadline.
// The API shows such a generation as failed and the worker never starts it.
func (g AgentGeneration) Expired(now time.Time) bool {
	return (g.Status == GenerationPending || g.Status == GenerationRunning) && now.After(g.DeadlineAt)
}

const generationColumns = `
	id, agent, kind, class_id, experience_id, student_id, competency_id, term_id, voice_note_id,
	requested_by, target_key, status, input, result, error, attempts, deadline_at, created_at, finished_at`

func scanGeneration(row pgx.Row) (AgentGeneration, error) {
	var g AgentGeneration
	var input, result []byte
	err := row.Scan(&g.ID, &g.Agent, &g.Kind, &g.ClassID, &g.ExperienceID,
		&g.StudentID, &g.CompetencyID, &g.TermID, &g.VoiceNoteID, &g.RequestedBy, &g.TargetKey,
		&g.Status, &input, &result, &g.Error, &g.Attempts, &g.DeadlineAt, &g.CreatedAt, &g.FinishedAt)
	if err != nil {
		return g, err
	}
	g.Input = json.RawMessage(input)
	if result != nil {
		g.Result = json.RawMessage(result)
	}
	return g, nil
}

// NewGeneration is what a request to an agent carries. The scope columns
// (student, competency, term, voice note) are set by the agents that work on
// one student; planning leaves them nil.
type NewGeneration struct {
	Agent        string
	Kind         string
	ClassID      uuid.UUID
	ExperienceID *uuid.UUID
	StudentID    *uuid.UUID
	CompetencyID *uuid.UUID
	TermID       *uuid.UUID
	VoiceNoteID  *uuid.UUID
	RequestedBy  uuid.UUID
	TargetKey    string
	Input        json.RawMessage
	Deadline     time.Duration
}

// CreateGeneration records a request, or returns the one already in flight
// for the same target (agent_generations_target_key): asking twice for the
// same thing while it runs never starts a second generation. created reports
// whether a new row was written, so the caller only enqueues a job for it.
func CreateGeneration(ctx context.Context, tx pgx.Tx, in NewGeneration) (g AgentGeneration, created bool, err error) {
	input := in.Input
	if len(input) == 0 {
		input = json.RawMessage(`{}`)
	}
	g, err = scanGeneration(tx.QueryRow(ctx, `
		insert into agent_generations
		  (tenant_id, agent, kind, class_id, experience_id, student_id, competency_id, term_id, voice_note_id,
		   requested_by, target_key, input, deadline_at)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
		        now() + make_interval(secs => $12))
		on conflict (tenant_id, target_key) where status in ('pending', 'running') do nothing
		returning `+generationColumns,
		in.Agent, in.Kind, in.ClassID, in.ExperienceID, in.StudentID, in.CompetencyID, in.TermID, in.VoiceNoteID,
		in.RequestedBy, in.TargetKey, []byte(input), in.Deadline.Seconds()))
	if err == nil {
		return g, true, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return g, false, err
	}
	g, err = scanGeneration(tx.QueryRow(ctx, `
		select `+generationColumns+` from agent_generations
		 where target_key = $1 and status in ('pending', 'running')
	`, in.TargetKey))
	return g, false, err
}

// GetGeneration reads one generation. RLS hides other schools' rows, which
// surface as not_found.
func GetGeneration(ctx context.Context, tx pgx.Tx, id uuid.UUID) (AgentGeneration, error) {
	g, err := scanGeneration(tx.QueryRow(ctx, `select `+generationColumns+` from agent_generations where id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return g, db.NewAppError(http.StatusNotFound, "not_found", "no se encontró la generación")
	}
	return g, err
}

// StartGeneration claims a generation for one attempt: it locks the row,
// moves it to running and counts the attempt. ok is false when there is
// nothing to do — the generation already finished, or it is past its
// deadline (then it is marked failed here, so it never runs late).
func StartGeneration(ctx context.Context, tx pgx.Tx, id uuid.UUID) (g AgentGeneration, ok bool, err error) {
	g, err = scanGeneration(tx.QueryRow(ctx, `select `+generationColumns+` from agent_generations where id = $1 for update`, id))
	if err != nil {
		return g, false, err
	}
	if g.Status != GenerationPending && g.Status != GenerationRunning {
		return g, false, nil
	}
	if g.Expired(time.Now()) {
		return g, false, FailGeneration(ctx, tx, id, ExpiredGenerationMessage, "deadline passed before the attempt started", Usage{})
	}
	g, err = scanGeneration(tx.QueryRow(ctx, `
		update agent_generations
		   set status = 'running', attempts = attempts + 1, started_at = coalesce(started_at, now())
		 where id = $1
		returning `+generationColumns, id))
	return g, err == nil, err
}

// Usage is what the model calls of one attempt cost. It is added to the
// generation's totals, so retries are counted too.
type Usage struct {
	Model            string
	PromptVersion    string
	InputTokens      int64
	OutputTokens     int64
	CacheReadTokens  int64
	CacheWriteTokens int64
	CostUSD          float64
}

const addUsage = `
	model = coalesce(nullif($2, ''), model),
	prompt_version = coalesce(nullif($3, ''), prompt_version),
	input_tokens = input_tokens + $4,
	output_tokens = output_tokens + $5,
	cache_read_tokens = cache_read_tokens + $6,
	cache_write_tokens = cache_write_tokens + $7,
	cost_usd = cost_usd + $8`

func usageArgs(u Usage) []any {
	return []any{u.Model, u.PromptVersion, u.InputTokens, u.OutputTokens, u.CacheReadTokens, u.CacheWriteTokens, u.CostUSD}
}

// RecordGenerationUsage adds an attempt's usage without finishing the
// generation: a transient failure that will be retried still cost money.
func RecordGenerationUsage(ctx context.Context, tx pgx.Tx, id uuid.UUID, u Usage) error {
	_, err := tx.Exec(ctx, `update agent_generations set `+addUsage+` where id = $1`,
		append([]any{id}, usageArgs(u)...)...)
	return err
}

// CompleteGeneration records the result of a finished generation.
func CompleteGeneration(ctx context.Context, tx pgx.Tx, id uuid.UUID, result json.RawMessage, u Usage) error {
	_, err := tx.Exec(ctx, `
		update agent_generations
		   set status = 'completed', result = $9, error = null, error_detail = null, finished_at = now(), `+addUsage+`
		 where id = $1
	`, append(append([]any{id}, usageArgs(u)...), []byte(result))...)
	return err
}

// FailGeneration records a failed generation. message is for the teacher and
// goes out in the API; detail is for support and never does.
func FailGeneration(ctx context.Context, tx pgx.Tx, id uuid.UUID, message, detail string, u Usage) error {
	_, err := tx.Exec(ctx, `
		update agent_generations
		   set status = 'failed', error = $9, error_detail = nullif($10, ''), finished_at = now(), `+addUsage+`
		 where id = $1
	`, append(append([]any{id}, usageArgs(u)...), message, detail)...)
	return err
}

// LatestConclusionGeneration is the most recent conclusions generation for a
// student, competency and term, so a proposal survives a page reload. ok is
// false when there is none.
func LatestConclusionGeneration(ctx context.Context, tx pgx.Tx, studentID, competencyID, termID uuid.UUID) (g AgentGeneration, ok bool, err error) {
	g, err = scanGeneration(tx.QueryRow(ctx, `
		select `+generationColumns+` from agent_generations
		 where agent = 'conclusions' and student_id = $1 and competency_id = $2 and term_id = $3
		 order by created_at desc
		 limit 1
	`, studentID, competencyID, termID))
	if errors.Is(err, pgx.ErrNoRows) {
		return g, false, nil
	}
	return g, err == nil, err
}
