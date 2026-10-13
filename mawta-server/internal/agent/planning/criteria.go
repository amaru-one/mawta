package planning

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

type criteriaState struct {
	ExperienceID uuid.UUID
	CompetencyID uuid.UUID
	Capabilities map[uuid.UUID]bool
	Performances map[uuid.UUID]bool
}

var criteriaTool = llm.Tool{
	Name:        "proponer_criterios",
	Description: "Registra los criterios de evaluación propuestos para las capacidades que todavía no tienen criterio.",
	Properties: map[string]any{
		"criteria": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"description":    map[string]any{"type": "string", "description": "El criterio: una oración en tercera persona que empieza con un verbo en presente."},
					"capability_ids": map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "Ids de las capacidades que mira el criterio."},
					"performance_id": map[string]any{"type": "string", "description": "Id del desempeño del grado que el criterio aterriza."},
				},
				"required": []string{"description", "capability_ids", "performance_id"},
			},
		},
	},
	Required: []string{"criteria"},
}

func prepareCriteria(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	expID, err := experienceID(gen)
	if err != nil {
		return agent.Prepared{}, err
	}
	var in CriteriaInput
	if err := json.Unmarshal(gen.Input, &in); err != nil {
		return agent.Prepared{}, unprocessable("bad_request", "el pedido de criterios no es válido")
	}
	exp, err := repo.GetExperience(ctx, tx, expID)
	if err != nil {
		return agent.Prepared{}, err
	}
	var compName string
	for _, c := range exp.Competencies {
		if c.ID == in.CompetencyID {
			compName = c.Name
		}
	}
	if compName == "" {
		return agent.Prepared{}, unprocessable("competency_not_in_experience", "esa competencia no está en esta experiencia")
	}
	cur, err := repo.GetCurriculum(ctx, tx, gen.ClassID)
	if err != nil {
		return agent.Prepared{}, err
	}
	var comp *repo.CurriculumCompetency
	for i := range cur.Competencies {
		if cur.Competencies[i].ID == in.CompetencyID {
			comp = &cur.Competencies[i]
		}
	}
	if comp == nil || len(comp.Performances) == 0 {
		return agent.Prepared{}, unprocessable("no_performances",
			"Esta competencia no tiene desempeños cargados para el grado; escribe los criterios a mano.")
	}

	covered := coveredCapabilities(exp, in.CompetencyID)
	st := criteriaState{ExperienceID: expID, CompetencyID: in.CompetencyID,
		Capabilities: map[uuid.UUID]bool{}, Performances: map[uuid.UUID]bool{}}
	var gaps []repo.CurriculumCapability
	for _, cap := range comp.Capabilities {
		st.Capabilities[cap.ID] = true
		if !covered[cap.ID] {
			gaps = append(gaps, cap)
		}
	}
	if len(gaps) == 0 {
		r, err := result(map[string]any{"criteria_ids": []uuid.UUID{}})
		return agent.Prepared{Result: r}, err
	}
	for _, p := range comp.Performances {
		st.Performances[p.ID] = true
	}

	var pr strings.Builder
	fmt.Fprintf(&pr, "Experiencia: %s\nSituación: %s\n%s\n", exp.Title, deref(exp.SituationText), contextLine(exp.ContextText))
	fmt.Fprintf(&pr, "Competencia: %s\n\nCapacidades:\n", compName)
	for _, cap := range comp.Capabilities {
		mark := "ya tiene criterio"
		if !covered[cap.ID] {
			mark = "SIN CRITERIO"
		}
		fmt.Fprintf(&pr, "- id=%s %s (%s)\n", cap.ID, cap.Name, mark)
	}
	fmt.Fprintf(&pr, "\nDesempeños del grado %s para esta competencia:\n", cur.Grade.Code)
	for _, p := range comp.Performances {
		fmt.Fprintf(&pr, "- id=%s %s\n", p.ID, p.Text)
	}
	if existing := existingCriteria(exp, in.CompetencyID); len(existing) > 0 {
		pr.WriteString("\nCriterios que ya existen para esta competencia (no los repitas):\n")
		for _, d := range existing {
			fmt.Fprintf(&pr, "- %s\n", d)
		}
	}

	return agent.Prepared{
		Spec: &agent.Spec{
			System:    system("criteria", ""),
			Prompt:    pr.String(),
			Tool:      criteriaTool,
			MaxTokens: 4000,
		},
		State: st,
	}, nil
}

// coveredCapabilities are the capabilities of a competency that some
// criterion of the experience already looks at, pending proposals included:
// the agent fills gaps only.
func coveredCapabilities(exp repo.Experience, competencyID uuid.UUID) map[uuid.UUID]bool {
	out := map[uuid.UUID]bool{}
	for _, c := range exp.Criteria {
		if c.CompetencyID != competencyID {
			continue
		}
		for _, id := range c.CapabilityIDs {
			out[id] = true
		}
	}
	return out
}

func existingCriteria(exp repo.Experience, competencyID uuid.UUID) []string {
	var out []string
	for _, c := range exp.Criteria {
		if c.CompetencyID == competencyID {
			out = append(out, c.Description)
		}
	}
	return out
}

func applyCriteria(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, answer json.RawMessage) (json.RawMessage, error) {
	st := p.State.(criteriaState)
	var a struct {
		Criteria []struct {
			Description   string   `json:"description"`
			CapabilityIDs []string `json:"capability_ids"`
			PerformanceID string   `json:"performance_id"`
		} `json:"criteria"`
	}
	if err := decode(answer, &a); err != nil {
		return nil, err
	}

	// Coverage is re-read inside this transaction: the teacher may have
	// written criteria while the model was thinking.
	exp, err := repo.GetExperience(ctx, tx, st.ExperienceID)
	if err != nil {
		return nil, err
	}
	covered := coveredCapabilities(exp, st.CompetencyID)
	seenText := map[string]bool{}
	for _, d := range existingCriteria(exp, st.CompetencyID) {
		seenText[strings.ToLower(clean(d))] = true
	}

	ids := []uuid.UUID{}
	var reasons []string
	for i, c := range a.Criteria {
		description := clean(c.Description)
		if description == "" || seenText[strings.ToLower(description)] {
			reasons = append(reasons, fmt.Sprintf("criterio %d: descripción vacía o repetida", i+1))
			continue
		}
		performanceID, err := uuid.Parse(strings.TrimSpace(c.PerformanceID))
		if err != nil || !st.Performances[performanceID] {
			reasons = append(reasons, fmt.Sprintf("criterio %d: performance_id no es un desempeño de la lista", i+1))
			continue
		}
		var capabilityIDs []uuid.UUID
		fillsGap := false
		for _, s := range c.CapabilityIDs {
			id, err := uuid.Parse(strings.TrimSpace(s))
			if err != nil || !st.Capabilities[id] {
				continue
			}
			capabilityIDs = append(capabilityIDs, id)
			if !covered[id] {
				fillsGap = true
			}
		}
		if len(capabilityIDs) == 0 || !fillsGap {
			reasons = append(reasons, fmt.Sprintf("criterio %d: debe mirar al menos una capacidad SIN CRITERIO de la lista", i+1))
			continue
		}

		id, err := repo.ProposeCriterion(ctx, tx, st.ExperienceID, repo.CriterionInput{
			CompetencyID:  st.CompetencyID,
			Description:   description,
			CapabilityIDs: capabilityIDs,
			PerformanceID: performanceID,
		})
		if err != nil {
			var appErr *db.AppError
			if errors.As(err, &appErr) && appErr.Status < 500 {
				reasons = append(reasons, fmt.Sprintf("criterio %d: %s", i+1, appErr.Message))
				continue
			}
			return nil, err
		}
		ids = append(ids, id)
		seenText[strings.ToLower(description)] = true
		for _, cid := range capabilityIDs {
			covered[cid] = true
		}
	}
	if len(ids) == 0 && len(a.Criteria) > 0 {
		return nil, agent.Invalid("ningún criterio se pudo usar: %s", strings.Join(reasons, "; "))
	}
	if len(ids) == 0 {
		return nil, agent.Invalid("la lista criteria vino vacía, pero hay capacidades sin criterio")
	}
	return result(map[string]any{"criteria_ids": ids})
}

func deref(s *string) string {
	if s == nil {
		return "(sin situación redactada)"
	}
	return *s
}

// contextLine states the teacher's event or context for a planning prompt. When
// there is none it says so outright, so the agent has no room to invent an event.
func contextLine(text *string) string {
	if text != nil && strings.TrimSpace(*text) != "" {
		return "Contexto del docente: " + strings.TrimSpace(*text) + "\n"
	}
	return "Contexto del docente: ninguno. No incluyas ningún evento, feria, aniversario, campaña ni actividad social.\n"
}
