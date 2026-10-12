package agent

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

// DefaultDeadline is how long a generation may take before it is shown as
// failed (agent_generations.deadline_at).
const DefaultDeadline = 5 * time.Minute

// Enqueue records a generation and queues the job that runs it, in the
// caller's transaction, or returns the one already in flight for the same
// target. Both the API ("✦ Generar con Mawta") and the worker (a voice note
// that finished transcribing queues its redaction sweep) start generations
// through here. in.Agent, in.RequestedBy and the target must be set; a zero
// Deadline means DefaultDeadline.
func Enqueue(ctx context.Context, tx pgx.Tx, tenantID uuid.UUID, in repo.NewGeneration) (repo.AgentGeneration, error) {
	if in.Deadline == 0 {
		in.Deadline = DefaultDeadline
	}
	g, created, err := repo.CreateGeneration(ctx, tx, in)
	if err != nil || !created {
		return g, err
	}
	payload, _ := json.Marshal(JobPayload{GenerationID: g.ID})
	if err := repo.EnqueueJobWithAttempts(ctx, tx, tenantID, JobKind, 2, payload,
		JobKind+":"+g.ID.String(), MaxAttempts); err != nil {
		return g, err
	}
	eventPayload, _ := json.Marshal(map[string]string{"agent": g.Agent, "kind": g.Kind})
	id, classID := g.ID, g.ClassID
	return g, repo.LogEvent(ctx, tx, "agent.generation.requested", "agent_generation", &id, eventPayload, g.StudentID, &classID, nil)
}
