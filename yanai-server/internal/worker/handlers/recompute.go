package handlers

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"sort"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/domain"
	"yanai-server/internal/grading"
)

type recomputePayload struct {
	ClassID   uuid.UUID  `json:"class_id"`
	TermID    uuid.UUID  `json:"term_id"`
	StudentID *uuid.UUID `json:"student_id"`
}

// GradeRecompute recomputes one or more students' term_partial grade for a
// class, per internal/grading. Skips students with no live scores, and
// skips writing when the inputs digest is unchanged from the live row.
func GradeRecompute(ctx context.Context, tx pgx.Tx, jobID int64, payload []byte) error {
	var p recomputePayload
	if err := json.Unmarshal(payload, &p); err != nil {
		return err
	}

	targets := []uuid.UUID{}
	if p.StudentID != nil {
		targets = append(targets, *p.StudentID)
	} else {
		rows, err := tx.Query(ctx, `
			select distinct student_id from scores
			 where class_id = $1 and term_id = $2 and superseded_at is null and deleted_at is null
		`, p.ClassID, p.TermID)
		if err != nil {
			return err
		}
		for rows.Next() {
			var sid uuid.UUID
			if err := rows.Scan(&sid); err != nil {
				rows.Close()
				return err
			}
			targets = append(targets, sid)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
	}

	for _, studentID := range targets {
		if _, err := recomputeOne(ctx, tx, jobID, p.ClassID, p.TermID, studentID); err != nil {
			return err
		}
	}
	return nil
}

// recomputeOne returns whether it wrote a new computed_grades row; false
// means nothing material changed.
func recomputeOne(ctx context.Context, tx pgx.Tx, jobID int64, classID, termID, studentID uuid.UUID) (bool, error) {
	var scoreCount int
	if err := tx.QueryRow(ctx, `
		select count(*) from scores
		 where class_id = $1 and term_id = $2 and student_id = $3
		   and superseded_at is null and deleted_at is null
	`, classID, termID, studentID).Scan(&scoreCount); err != nil {
		return false, err
	}
	if scoreCount == 0 {
		return false, nil
	}

	var schemeID, schemeVersionID uuid.UUID
	if err := tx.QueryRow(ctx, `
		select scheme_id, scheme_version_id from class_effective_grading_schemes
		 where class_id = $1 and term_id = $2
	`, classID, termID).Scan(&schemeID, &schemeVersionID); err != nil {
		return false, err
	}
	if schemeVersionID == uuid.Nil {
		return false, nil // no published version in effect for this term; nothing to compute
	}

	var policy grading.Policy
	var scaleID uuid.UUID
	if err := tx.QueryRow(ctx, `
		select rounding_mode, rounding_decimals, absent_counts_as, retake_policy,
		       retake_cap_normalized, min_evaluated_weight_for_grade
		  from grading_scheme_versions where id = $1
	`, schemeVersionID).Scan(&policy.RoundingMode, &policy.RoundingDecimals, &policy.AbsentCountsAs,
		&policy.RetakePolicy, &policy.RetakeCapNormalized, &policy.MinEvaluatedWeightForGrade); err != nil {
		return false, err
	}
	var scaleKind string
	var scaleMin, scaleMax float64
	var scaleDecimals int
	if err := tx.QueryRow(ctx, `
		select sc.id, sc.kind, sc.min_value, sc.max_value, sc.decimals
		  from grading_schemes gs join grade_scales sc on sc.id = gs.scale_id
		 where gs.id = $1
	`, schemeID).Scan(&scaleID, &scaleKind, &scaleMin, &scaleMax, &scaleDecimals); err != nil {
		return false, err
	}

	wrows, err := tx.Query(ctx, `
		select component_id, weight, drop_lowest_n, aggregation, is_required
		  from grading_scheme_component_weights
		 where scheme_version_id = $1 and deleted_at is null
	`, schemeVersionID)
	if err != nil {
		return false, err
	}
	var weights []grading.ComponentWeight
	for wrows.Next() {
		var w grading.ComponentWeight
		if err := wrows.Scan(&w.ComponentID, &w.Weight, &w.DropLowestN, &w.Aggregation, &w.IsRequired); err != nil {
			wrows.Close()
			return false, err
		}
		weights = append(weights, w)
	}
	wrows.Close()
	if err := wrows.Err(); err != nil {
		return false, err
	}

	arows, err := tx.Query(ctx, `
		select a.id, a.component_id, a.weight_within_component, a.due_at,
		       s.id, s.attempt_number, s.status, s.raw_value, s.max_value
		  from assessments a
		  join scores s on s.assessment_id = a.id and s.student_id = $3
		                and s.superseded_at is null and s.deleted_at is null
		 where a.class_id = $1 and a.term_id = $2 and a.status = 'published' and a.deleted_at is null
		   -- The school's own average only. Evidence flagged out of it still
		   -- informs the official judgement, which is the teacher's nivel de logro
		   -- per competencia and never passes through here.
		   and a.counts_toward_internal
		   -- Only a numeric piece has anything a weighted average can use. A
		   -- letter is not a small number: converting one into the average is the
		   -- arithmetic RVM 094-2020 refuses, and an unvalued piece has no value
		   -- at all. The API already forces counts_toward_internal off for both,
		   -- so this is the same rule stated where it is relied on — and it is
		   -- what keeps the not-null scan of s.max_value below safe.
		   and a.value_scale = 'numeric'
		 order by a.id, s.attempt_number
	`, classID, termID, studentID)
	if err != nil {
		return false, err
	}
	byAssessment := make(map[uuid.UUID]*grading.AssessmentInput)
	var order []uuid.UUID
	var scoreIDs []string
	for arows.Next() {
		var assessmentID, componentID uuid.UUID
		var weightWithinComponent float64
		var dueAt *time.Time
		var att grading.Attempt
		if err := arows.Scan(&assessmentID, &componentID, &weightWithinComponent, &dueAt,
			&att.ScoreID, &att.AttemptNumber, &att.Status, &att.RawValue, &att.MaxValue); err != nil {
			arows.Close()
			return false, err
		}
		ai, ok := byAssessment[assessmentID]
		if !ok {
			ai = &grading.AssessmentInput{AssessmentID: assessmentID, ComponentID: componentID, WeightWithinComponent: weightWithinComponent, DueAt: dueAt}
			byAssessment[assessmentID] = ai
			order = append(order, assessmentID)
		}
		ai.Attempts = append(ai.Attempts, att)
		scoreIDs = append(scoreIDs, att.ScoreID.String())
	}
	arows.Close()
	if err := arows.Err(); err != nil {
		return false, err
	}
	var assessments []grading.AssessmentInput
	for _, id := range order {
		assessments = append(assessments, *byAssessment[id])
	}

	result := grading.Compute(assessments, weights, policy)

	sort.Strings(scoreIDs)
	digestInput := schemeVersionID.String() + "|" + joinStrings(scoreIDs, ",")
	sum := sha256.Sum256([]byte(digestInput))
	digest := hex.EncodeToString(sum[:])

	var liveID uuid.UUID
	var liveDigest *string
	var livePrevLevelID *uuid.UUID
	var livePrevNormalized *float64
	err = tx.QueryRow(ctx, `
		select id, inputs_digest, scale_level_id, normalized_value from computed_grades
		 where student_id = $1 and class_id = $2 and term_id = $3
		   and superseded_at is null and deleted_at is null
	`, studentID, classID, termID).Scan(&liveID, &liveDigest, &livePrevLevelID, &livePrevNormalized)
	hasLive := err == nil
	if err != nil && err != pgx.ErrNoRows {
		return false, err
	}
	if hasLive && liveDigest != nil && *liveDigest == digest {
		return false, nil // nothing material changed
	}

	var scaleLevelID *uuid.UUID
	var displayValue *string
	if !result.BelowMinEvaluated {
		var levelID uuid.UUID
		var code string
		err := tx.QueryRow(ctx, `
			select id, code from grade_scale_levels
			 where scale_id = $1 and deleted_at is null
			   and $2 >= min_normalized and ($2 < max_normalized or max_normalized = 1)
		`, scaleID, result.NormalizedValue).Scan(&levelID, &code)
		if err == nil {
			scaleLevelID = &levelID
			if scaleKind == domain.ScaleOrdinal {
				displayValue = &code
			}
		} else if err != pgx.ErrNoRows {
			return false, err
		}
		if scaleKind != domain.ScaleOrdinal {
			v := grading.Round(scaleMin+result.NormalizedValue*(scaleMax-scaleMin), policy.RoundingMode, scaleDecimals)
			s := strconv.FormatFloat(v, 'f', scaleDecimals, 64)
			displayValue = &s
		}
	}

	var trend *string
	var prevLevelID *uuid.UUID
	var prevNormalized *float64
	if hasLive {
		prevLevelID = livePrevLevelID
		prevNormalized = livePrevNormalized
		t := domain.TrendFlat
		if *livePrevNormalized < result.NormalizedValue {
			t = domain.TrendUp
		} else if *livePrevNormalized > result.NormalizedValue {
			t = domain.TrendDown
		}
		trend = &t
	}

	if hasLive {
		if _, err := tx.Exec(ctx, `update computed_grades set superseded_at = now() where id = $1`, liveID); err != nil {
			return false, err
		}
	}

	var supersedesID *uuid.UUID
	if hasLive {
		supersedesID = &liveID
	}

	var newID uuid.UUID
	if err := tx.QueryRow(ctx, `
		insert into computed_grades (
			tenant_id, student_id, class_id, term_id, scheme_version_id, scale_id, scope,
			normalized_value, normalization_method, scale_level_id, display_value,
			total_weight, evaluated_weight,
			previous_scale_level_id, previous_normalized_value, trend,
			scores_counted, inputs_digest, computed_by_job_id, supersedes_id
		) values (
			app.current_tenant_id(), $1, $2, $3, $4, $5, $6,
			$7, 'ratio_of_evaluated', $8, $9,
			$10, $11,
			$12, $13, $14,
			$15, $16, $17, $18
		) returning id
	`, studentID, classID, termID, schemeVersionID, scaleID, domain.ScopeTermPartial,
		result.NormalizedValue, scaleLevelID, displayValue,
		result.TotalWeight, result.EvaluatedWeight,
		prevLevelID, prevNormalized, trend,
		scoreCount, digest, jobID, supersedesID,
	).Scan(&newID); err != nil {
		return false, err
	}

	for _, cr := range result.Components {
		if _, err := tx.Exec(ctx, `
			insert into computed_grade_components (
				tenant_id, computed_grade_id, component_id, weight_applied, is_evaluated,
				normalized_value, display_value, assessments_counted,
				counted_score_ids, dropped_score_ids, excused_score_ids
			) values (
				app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10
			)
		`, newID, cr.ComponentID, cr.WeightApplied, cr.IsEvaluated,
			cr.NormalizedValue, componentDisplayValue(cr, scaleKind), cr.AssessmentsCounted,
			uuidStrings(cr.CountedScoreIDs), uuidStrings(cr.DroppedScoreIDs), uuidStrings(cr.ExcusedScoreIDs),
		); err != nil {
			return false, err
		}
	}

	return true, nil
}

func componentDisplayValue(cr grading.ComponentResult, scaleKind string) *string {
	if cr.NormalizedValue == nil {
		return nil
	}
	s := strconv.FormatFloat(*cr.NormalizedValue*100, 'f', 0, 64) + "%"
	return &s
}

func uuidStrings(ids []uuid.UUID) []uuid.UUID {
	if ids == nil {
		return []uuid.UUID{}
	}
	return ids
}

func joinStrings(ss []string, sep string) string {
	out := ""
	for i, s := range ss {
		if i > 0 {
			out += sep
		}
		out += s
	}
	return out
}
