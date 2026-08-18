// Package grading implements the grade.recompute math: turning a student's
// live scores into a normalized (0-1) grade, band, and per-component
// breakdown. Pure computation, no SQL — the worker handler loads inputs and
// writes the result.
//
// Implemented: component weights, drop_lowest_n, aggregation
// (mean/weighted_mean/best/last/sum), retake resolution (none/best/last/
// capped), min_evaluated_weight_for_grade, and rounding modes.
//
// Out of scope for this stage: late penalties (scores.late_days /
// late_penalty_pct_per_day are ignored) and per-competency grades.
package grading

import (
	"math"
	"sort"
	"time"

	"github.com/google/uuid"
)

type Attempt struct {
	ScoreID             uuid.UUID
	AttemptNumber       int16
	Status              string // graded | excused | absent | not_submitted
	RawValue            *float64
	MaxValue            float64
	RetakeCapNormalized *float64 // from retake_authorizations, if this attempt used one
}

type AssessmentInput struct {
	AssessmentID          uuid.UUID
	ComponentID           uuid.UUID
	WeightWithinComponent float64
	DueAt                 *time.Time
	Attempts              []Attempt // all live attempts, any attempt_number
}

type ComponentWeight struct {
	ComponentID uuid.UUID
	Weight      float64
	DropLowestN int
	Aggregation string // mean | weighted_mean | best | last | sum
	IsRequired  bool
}

type Policy struct {
	AbsentCountsAs             string // zero | excused
	RetakePolicy               string // none | best | last | capped
	RetakeCapNormalized        *float64
	MinEvaluatedWeightForGrade float64
	RoundingMode               string // half_up | half_even | floor | ceil | none
	RoundingDecimals           int
}

type ComponentResult struct {
	ComponentID        uuid.UUID
	WeightApplied      float64
	IsEvaluated        bool
	NormalizedValue    *float64
	AssessmentsCounted int
	CountedScoreIDs    []uuid.UUID
	DroppedScoreIDs    []uuid.UUID
	ExcusedScoreIDs    []uuid.UUID
}

type Result struct {
	NormalizedValue        float64
	TotalWeight            float64
	EvaluatedWeight        float64
	ProjectedMinNormalized float64
	ProjectedMaxNormalized float64
	BelowMinEvaluated      bool
	Components             []ComponentResult
}

type assessmentOutcome struct {
	assessmentID          uuid.UUID
	weightWithinComponent float64
	dueAt                 *time.Time
	included              bool
	normalizedValue       float64
	scoreID               uuid.UUID
	excusedScoreIDs       []uuid.UUID
}

// resolveAssessment collapses one assessment's live attempts into a single
// outcome per the scheme version's retake policy.
func resolveAssessment(a AssessmentInput, policy Policy) assessmentOutcome {
	out := assessmentOutcome{assessmentID: a.AssessmentID, weightWithinComponent: a.WeightWithinComponent, dueAt: a.DueAt}

	type candidate struct {
		scoreID       uuid.UUID
		attemptNumber int16
		value         float64
		cap           *float64
	}
	var candidates []candidate

	for _, at := range a.Attempts {
		switch at.Status {
		case "excused":
			out.excusedScoreIDs = append(out.excusedScoreIDs, at.ScoreID)
		case "absent", "not_submitted":
			if policy.AbsentCountsAs == "excused" {
				out.excusedScoreIDs = append(out.excusedScoreIDs, at.ScoreID)
			} else {
				candidates = append(candidates, candidate{at.ScoreID, at.AttemptNumber, 0, at.RetakeCapNormalized})
			}
		case "graded":
			if at.RawValue != nil && at.MaxValue > 0 {
				candidates = append(candidates, candidate{at.ScoreID, at.AttemptNumber, *at.RawValue / at.MaxValue, at.RetakeCapNormalized})
			}
		}
	}

	if len(candidates) == 0 {
		out.included = false
		return out
	}

	var chosen candidate
	switch {
	case len(candidates) == 1:
		chosen = candidates[0]
	case policy.RetakePolicy == "last":
		chosen = candidates[0]
		for _, c := range candidates {
			if c.attemptNumber > chosen.attemptNumber {
				chosen = c
			}
		}
	case policy.RetakePolicy == "none":
		chosen = candidates[0]
		for _, c := range candidates {
			if c.attemptNumber == 1 {
				chosen = c
				break
			}
		}
	default: // "best" and "capped" both start from the best candidate
		chosen = candidates[0]
		for _, c := range candidates {
			if c.value > chosen.value {
				chosen = c
			}
		}
	}

	value := chosen.value
	if policy.RetakePolicy == "capped" && chosen.attemptNumber > 1 {
		cap := policy.RetakeCapNormalized
		if chosen.cap != nil {
			cap = chosen.cap
		}
		if cap != nil && value > *cap {
			value = *cap
		}
	}

	out.included = true
	out.normalizedValue = value
	out.scoreID = chosen.scoreID
	return out
}

// Compute aggregates resolved assessment outcomes into component results
// and a final normalized grade.
func Compute(assessments []AssessmentInput, weights []ComponentWeight, policy Policy) Result {
	byComponent := make(map[uuid.UUID][]assessmentOutcome)
	for _, a := range assessments {
		byComponent[a.ComponentID] = append(byComponent[a.ComponentID], resolveAssessment(a, policy))
	}

	var result Result
	var achieved float64

	for _, w := range weights {
		outcomes := byComponent[w.ComponentID]

		cr := ComponentResult{ComponentID: w.ComponentID}

		var included []assessmentOutcome
		for _, o := range outcomes {
			cr.ExcusedScoreIDs = append(cr.ExcusedScoreIDs, o.excusedScoreIDs...)
			if o.included {
				included = append(included, o)
			}
		}

		if len(included) == 0 {
			if !w.IsRequired {
				// Optional component with nothing to grade: drops out of both
				// total and evaluated weight entirely.
				continue
			}
			cr.WeightApplied = w.Weight
			cr.IsEvaluated = false
			result.TotalWeight += w.Weight
			result.Components = append(result.Components, cr)
			continue
		}

		sort.Slice(included, func(i, j int) bool { return included[i].normalizedValue < included[j].normalizedValue })
		dropN := w.DropLowestN
		if dropN > len(included)-1 {
			dropN = len(included) - 1 // always keep at least one
		}
		if dropN < 0 {
			dropN = 0
		}
		dropped := included[:dropN]
		kept := included[dropN:]
		for _, d := range dropped {
			cr.DroppedScoreIDs = append(cr.DroppedScoreIDs, d.scoreID)
		}

		var normalized float64
		switch w.Aggregation {
		case "best":
			normalized = kept[0].normalizedValue
			for _, o := range kept {
				if o.normalizedValue > normalized {
					normalized = o.normalizedValue
				}
			}
		case "last":
			best := kept[0]
			for _, o := range kept {
				if o.dueAt != nil && (best.dueAt == nil || o.dueAt.After(*best.dueAt)) {
					best = o
				}
			}
			normalized = best.normalizedValue
		case "sum":
			for _, o := range kept {
				normalized += o.normalizedValue
			}
		case "weighted_mean":
			var num, den float64
			for _, o := range kept {
				num += o.normalizedValue * o.weightWithinComponent
				den += o.weightWithinComponent
			}
			if den > 0 {
				normalized = num / den
			}
		default: // "mean"
			var sum float64
			for _, o := range kept {
				sum += o.normalizedValue
			}
			normalized = sum / float64(len(kept))
		}

		for _, o := range kept {
			cr.CountedScoreIDs = append(cr.CountedScoreIDs, o.scoreID)
		}

		cr.WeightApplied = w.Weight
		cr.IsEvaluated = true
		nv := normalized
		cr.NormalizedValue = &nv
		cr.AssessmentsCounted = len(kept)

		result.TotalWeight += w.Weight
		result.EvaluatedWeight += w.Weight
		achieved += w.Weight * normalized

		result.Components = append(result.Components, cr)
	}

	if result.EvaluatedWeight > 0 {
		result.NormalizedValue = achieved / result.EvaluatedWeight
	}
	result.ProjectedMinNormalized = achieved
	result.ProjectedMaxNormalized = achieved + (result.TotalWeight - result.EvaluatedWeight)
	if result.ProjectedMaxNormalized > result.TotalWeight {
		result.ProjectedMaxNormalized = result.TotalWeight
	}
	result.BelowMinEvaluated = result.TotalWeight > 0 && result.EvaluatedWeight/result.TotalWeight < policy.MinEvaluatedWeightForGrade

	return result
}

// Round applies a scheme version's rounding policy.
func Round(value float64, mode string, decimals int) float64 {
	mult := math.Pow(10, float64(decimals))
	scaled := value * mult
	var rounded float64
	switch mode {
	case "floor":
		rounded = math.Floor(scaled)
	case "ceil":
		rounded = math.Ceil(scaled)
	case "half_even":
		rounded = math.RoundToEven(scaled)
	case "none":
		return value
	default: // half_up
		rounded = math.Floor(scaled + 0.5)
	}
	return rounded / mult
}
