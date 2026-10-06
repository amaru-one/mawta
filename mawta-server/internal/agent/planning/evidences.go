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

type evidencesState struct {
	ExperienceID uuid.UUID
}

var evidenceKinds = map[string]bool{"produccion": true, "actuacion": true, "prueba_escrita": true}

var evidencesTool = llm.Tool{
	Name:        "proponer_evidencias",
	Description: "Registra las evidencias propuestas para observar los criterios que todavía no tienen evidencia.",
	Properties: map[string]any{
		"evidences": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"name":          map[string]any{"type": "string", "description": "Nombre corto y concreto de la evidencia."},
					"kind":          map[string]any{"type": "string", "enum": []string{"produccion", "actuacion", "prueba_escrita"}},
					"criterion_ids": map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "Ids de los criterios que observa."},
				},
				"required": []string{"name", "kind", "criterion_ids"},
			},
		},
	},
	Required: []string{"evidences"},
}

// observedCriteria are the criteria some evidence of the experience already
// observes, pending proposals included.
func observedCriteria(exp repo.Experience) map[uuid.UUID]bool {
	out := map[uuid.UUID]bool{}
	for _, e := range exp.Evidences {
		for _, id := range e.CriterionIDs {
			out[id] = true
		}
	}
	return out
}

func prepareEvidences(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	expID, err := experienceID(gen)
	if err != nil {
		return agent.Prepared{}, err
	}
	exp, err := repo.GetExperience(ctx, tx, expID)
	if err != nil {
		return agent.Prepared{}, err
	}
	if len(exp.Criteria) == 0 {
		return agent.Prepared{}, unprocessable("no_criteria",
			"Primero define los criterios: las evidencias se proponen a partir de ellos.")
	}
	observed := observedCriteria(exp)
	pending := 0
	for _, c := range exp.Criteria {
		if !observed[c.ID] {
			pending++
		}
	}
	if pending == 0 {
		r, err := result(map[string]any{"evidence_ids": []uuid.UUID{}})
		return agent.Prepared{Result: r}, err
	}

	competency := map[uuid.UUID]string{}
	for _, c := range exp.Competencies {
		competency[c.ID] = c.Name
	}
	var pr strings.Builder
	fmt.Fprintf(&pr, "Experiencia: %s\nSituación: %s\n\nCriterios de la experiencia:\n", exp.Title, deref(exp.SituationText))
	for _, c := range exp.Criteria {
		mark := "ya tiene evidencia"
		if !observed[c.ID] {
			mark = "SIN EVIDENCIA"
		}
		fmt.Fprintf(&pr, "- id=%s [%s] %s (%s)\n", c.ID, competency[c.CompetencyID], c.Description, mark)
	}
	if len(exp.Evidences) > 0 {
		pr.WriteString("\nEvidencias que ya existen (no las repitas):\n")
		for _, e := range exp.Evidences {
			fmt.Fprintf(&pr, "- %s (%s)\n", e.Name, e.Kind)
		}
	}

	return agent.Prepared{
		Spec: &agent.Spec{
			System:    system("evidences", ""),
			Prompt:    pr.String(),
			Tool:      evidencesTool,
			MaxTokens: 3000,
		},
		State: evidencesState{ExperienceID: expID},
	}, nil
}

func applyEvidences(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, answer json.RawMessage) (json.RawMessage, error) {
	st := p.State.(evidencesState)
	var a struct {
		Evidences []struct {
			Name         string   `json:"name"`
			Kind         string   `json:"kind"`
			CriterionIDs []string `json:"criterion_ids"`
		} `json:"evidences"`
	}
	if err := decode(answer, &a); err != nil {
		return nil, err
	}
	exp, err := repo.GetExperience(ctx, tx, st.ExperienceID)
	if err != nil {
		return nil, err
	}
	inExperience := map[uuid.UUID]bool{}
	for _, c := range exp.Criteria {
		inExperience[c.ID] = true
	}
	observed := observedCriteria(exp)
	seenName := map[string]bool{}
	for _, e := range exp.Evidences {
		seenName[strings.ToLower(clean(e.Name))] = true
	}

	ids := []uuid.UUID{}
	var reasons []string
	for i, e := range a.Evidences {
		name := clean(e.Name)
		kind := strings.TrimSpace(e.Kind)
		if name == "" || seenName[strings.ToLower(name)] {
			reasons = append(reasons, fmt.Sprintf("evidencia %d: nombre vacío o repetido", i+1))
			continue
		}
		if !evidenceKinds[kind] {
			reasons = append(reasons, fmt.Sprintf("evidencia %d: kind debe ser produccion, actuacion o prueba_escrita", i+1))
			continue
		}
		var criterionIDs []uuid.UUID
		fillsGap := false
		seen := map[uuid.UUID]bool{}
		for _, s := range e.CriterionIDs {
			id, err := uuid.Parse(strings.TrimSpace(s))
			if err != nil || !inExperience[id] || seen[id] {
				continue
			}
			seen[id] = true
			criterionIDs = append(criterionIDs, id)
			if !observed[id] {
				fillsGap = true
			}
		}
		if len(criterionIDs) == 0 || !fillsGap {
			reasons = append(reasons, fmt.Sprintf("evidencia %d: debe observar al menos un criterio SIN EVIDENCIA de la lista", i+1))
			continue
		}
		id, err := repo.ProposeEvidence(ctx, tx, st.ExperienceID, repo.EvidenceInput{
			Name: name, Kind: kind, CriterionIDs: criterionIDs,
		})
		if err != nil {
			var appErr *db.AppError
			if errors.As(err, &appErr) && appErr.Status < 500 {
				reasons = append(reasons, fmt.Sprintf("evidencia %d: %s", i+1, appErr.Message))
				continue
			}
			return nil, err
		}
		ids = append(ids, id)
		seenName[strings.ToLower(name)] = true
		for _, cid := range criterionIDs {
			observed[cid] = true
		}
	}
	if len(ids) == 0 {
		if len(reasons) == 0 {
			return nil, agent.Invalid("la lista evidences vino vacía, pero hay criterios sin evidencia")
		}
		return nil, agent.Invalid("ninguna evidencia se pudo usar: %s", strings.Join(reasons, "; "))
	}
	return result(map[string]any{"evidence_ids": ids})
}
