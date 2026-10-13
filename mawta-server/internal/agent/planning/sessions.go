package planning

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

type sessionsState struct {
	ExperienceID uuid.UUID
}

var sessionsTool = llm.Tool{
	Name:        "proponer_sesiones",
	Description: "Registra el esquema ligero de sesiones propuesto para las fechas de clase sin sesión.",
	Properties: map[string]any{
		"sessions": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"date":                map[string]any{"type": "string", "description": "Una de las fechas vacías, YYYY-MM-DD."},
					"title":               map[string]any{"type": "string", "description": "Título corto de la sesión (máximo 8 palabras)."},
					"topics":              map[string]any{"type": "string", "description": "Temas de la sesión, en una línea."},
					"planned_evidence_id": map[string]any{"type": "string", "description": "Id (uuid) de la evidencia que se recoge en esta sesión, copiado de la lista de evidencias sin sesión; cadena vacía si la sesión no lleva evidencia."},
				},
				"required": []string{"date", "title", "topics", "planned_evidence_id"},
			},
		},
	},
	Required: []string{"sessions"},
}

var weekdays = [...]string{"domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"}

// emptyDates are the experience's class dates without a session entry.
func emptyDates(exp repo.Experience) []string {
	taken := map[string]bool{}
	for _, s := range exp.Sessions {
		taken[s.Date] = true
	}
	var out []string
	for _, d := range exp.ClassDates {
		if !taken[d] {
			out = append(out, d)
		}
	}
	return out
}

func prepareSessions(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	expID, err := experienceID(gen)
	if err != nil {
		return agent.Prepared{}, err
	}
	exp, err := repo.GetExperience(ctx, tx, expID)
	if err != nil {
		return agent.Prepared{}, err
	}
	empty := emptyDates(exp)
	if len(empty) == 0 {
		r, err := result(map[string]any{"session_dates": []string{}})
		return agent.Prepared{Result: r}, err
	}

	performances := map[uuid.UUID]string{}
	cur, err := repo.GetCurriculum(ctx, tx, gen.ClassID)
	if err != nil {
		return agent.Prepared{}, err
	}
	for _, c := range cur.Competencies {
		for _, p := range c.Performances {
			performances[p.ID] = p.Text
		}
	}

	var pr strings.Builder
	fmt.Fprintf(&pr, "Experiencia: %s (del %s al %s)\nSituación: %s\n%s\n", exp.Title, exp.StartsOn, exp.EndsOn, deref(exp.SituationText), contextLine(exp.ContextText))
	pr.WriteString("Criterios y los desempeños que aterrizan (fuente de los temas):\n")
	for _, c := range exp.Criteria {
		fmt.Fprintf(&pr, "- %s", c.Description)
		if c.PerformanceID != nil && performances[*c.PerformanceID] != "" {
			fmt.Fprintf(&pr, " — desempeño: %s", performances[*c.PerformanceID])
		}
		pr.WriteString("\n")
	}
	if len(exp.Sessions) > 0 {
		pr.WriteString("\nSesiones que ya existen (no las cambies):\n")
		for _, s := range exp.Sessions {
			fmt.Fprintf(&pr, "- %s: %s\n", s.Date, s.Title)
		}
	}
	unplaced := 0
	for _, e := range exp.Evidences {
		if e.SessionDate == nil {
			if unplaced == 0 {
				pr.WriteString("\nEvidencias sin sesión (ubícalas):\n")
			}
			unplaced++
			fmt.Fprintf(&pr, "- id=%s %s (%s)\n", e.ID, e.Name, e.Kind)
		}
	}
	pr.WriteString("\nFechas de clase vacías (propón una sesión para cada una):\n")
	for _, d := range empty {
		day, _ := time.Parse(dateLayout, d)
		fmt.Fprintf(&pr, "- %s (%s)\n", d, weekdays[day.Weekday()])
	}

	return agent.Prepared{
		Spec: &agent.Spec{
			System:    system("sessions", ""),
			Prompt:    pr.String(),
			Tool:      sessionsTool,
			MaxTokens: 6000,
		},
		State: sessionsState{ExperienceID: expID},
	}, nil
}

func applySessions(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, answer json.RawMessage) (json.RawMessage, error) {
	st := p.State.(sessionsState)
	var a struct {
		Sessions []struct {
			Date              string `json:"date"`
			Title             string `json:"title"`
			Topics            string `json:"topics"`
			PlannedEvidenceID string `json:"planned_evidence_id"`
		} `json:"sessions"`
	}
	if err := decode(answer, &a); err != nil {
		return nil, err
	}
	exp, err := repo.GetExperience(ctx, tx, st.ExperienceID)
	if err != nil {
		return nil, err
	}
	empty := map[string]bool{}
	for _, d := range emptyDates(exp) {
		empty[d] = true
	}
	unplaced := map[uuid.UUID]bool{}
	for _, e := range exp.Evidences {
		if e.SessionDate == nil {
			unplaced[e.ID] = true
		}
	}

	dates := []string{}
	var reasons []string
	for i, s := range a.Sessions {
		date := strings.TrimSpace(s.Date)
		title := clean(s.Title)
		if !empty[date] {
			reasons = append(reasons, fmt.Sprintf("sesión %d: %q no es una de las fechas vacías", i+1, date))
			continue
		}
		if title == "" {
			reasons = append(reasons, fmt.Sprintf("sesión %d: título vacío", i+1))
			continue
		}
		day, _ := time.Parse(dateLayout, date)
		topics := clean(s.Topics)
		var evidence *uuid.UUID
		if id, err := uuid.Parse(strings.TrimSpace(s.PlannedEvidenceID)); err == nil && unplaced[id] {
			evidence = &id
		}
		in := repo.SessionInput{Title: title, PlannedEvidenceID: evidence}
		if topics != "" {
			in.Topics = &topics
		}
		inserted, err := repo.ProposeSessionEntry(ctx, tx, st.ExperienceID, day, in)
		if err != nil {
			var appErr *db.AppError
			if errors.As(err, &appErr) && appErr.Status < 500 {
				reasons = append(reasons, fmt.Sprintf("sesión %d: %s", i+1, appErr.Message))
				continue
			}
			return nil, err
		}
		if !inserted {
			continue // the teacher filled this date meanwhile
		}
		dates = append(dates, date)
		empty[date] = false
		if evidence != nil {
			unplaced[*evidence] = false
		}
	}
	if len(dates) == 0 {
		if len(reasons) == 0 {
			return nil, agent.Invalid("la lista sessions vino vacía, pero hay fechas de clase sin sesión")
		}
		return nil, agent.Invalid("ninguna sesión se pudo usar: %s", strings.Join(reasons, "; "))
	}
	return result(map[string]any{"session_dates": dates})
}
