package grading

import (
	"math"
	"testing"
	"time"

	"github.com/google/uuid"
)

// This package is pure — no SQL, no context, no clock — so everything here
// runs without a database. See SPEC.md: that purity is a constraint, not an
// accident, and these tests are what hold it.

const epsilon = 1e-9

func closeTo(t *testing.T, got, want float64, what string) {
	t.Helper()
	if math.Abs(got-want) > epsilon {
		t.Errorf("%s = %v, want %v", what, got, want)
	}
}

func ptr[T any](v T) *T { return &v }

// graded builds a live graded attempt worth rawValue out of maxValue.
func graded(attempt int16, rawValue, maxValue float64) Attempt {
	return Attempt{ScoreID: uuid.New(), AttemptNumber: attempt, Status: "graded", RawValue: ptr(rawValue), MaxValue: maxValue}
}

func withStatus(attempt int16, status string) Attempt {
	return Attempt{ScoreID: uuid.New(), AttemptNumber: attempt, Status: status, MaxValue: 20}
}

// one assessment in one component, so a test can speak about a single number.
func oneAssessment(componentID uuid.UUID, attempts ...Attempt) AssessmentInput {
	return AssessmentInput{AssessmentID: uuid.New(), ComponentID: componentID, WeightWithinComponent: 1, Attempts: attempts}
}

func TestResolveAssessmentRetakePolicies(t *testing.T) {
	first := graded(1, 10, 20)  // 0.50
	second := graded(2, 18, 20) // 0.90
	third := graded(3, 14, 20)  // 0.70

	cases := []struct {
		name     string
		policy   Policy
		attempts []Attempt
		want     float64
	}{
		{"best picks the highest, not the latest", Policy{RetakePolicy: "best"}, []Attempt{first, second, third}, 0.90},
		{"last picks the highest attempt_number, not the best", Policy{RetakePolicy: "last"}, []Attempt{first, second, third}, 0.70},
		{"none picks attempt 1 even when a retake scored higher", Policy{RetakePolicy: "none"}, []Attempt{first, second, third}, 0.50},
		{"capped clamps a retake down to the cap", Policy{RetakePolicy: "capped", RetakeCapNormalized: ptr(0.60)}, []Attempt{first, second}, 0.60},
		{"capped leaves a retake below the cap alone", Policy{RetakePolicy: "capped", RetakeCapNormalized: ptr(0.95)}, []Attempt{first, second}, 0.90},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := resolveAssessment(AssessmentInput{Attempts: tc.attempts}, tc.policy)
			if !got.included {
				t.Fatal("expected the assessment to be included")
			}
			closeTo(t, got.normalizedValue, tc.want, "normalizedValue")
		})
	}
}

// The cap applies to retakes only: a first attempt above the cap keeps its
// value, because there is nothing to penalise.
func TestCappedDoesNotClampAFirstAttempt(t *testing.T) {
	got := resolveAssessment(
		AssessmentInput{Attempts: []Attempt{graded(1, 20, 20)}},
		Policy{RetakePolicy: "capped", RetakeCapNormalized: ptr(0.60)},
	)
	closeTo(t, got.normalizedValue, 1.0, "a single first attempt")
}

// "none" means "the original attempt counts". When there is no attempt 1 —
// the original was superseded away — it falls back to the first candidate
// rather than returning nothing.
func TestRetakePolicyNoneFallsBackWhenAttemptOneIsMissing(t *testing.T) {
	got := resolveAssessment(
		AssessmentInput{Attempts: []Attempt{graded(2, 18, 20), graded(3, 6, 20)}},
		Policy{RetakePolicy: "none"},
	)
	if !got.included {
		t.Fatal("expected inclusion despite no attempt 1")
	}
	closeTo(t, got.normalizedValue, 0.90, "fallback to the first candidate")
}

func TestAbsentHandlingDependsOnPolicy(t *testing.T) {
	for _, tc := range []struct {
		name         string
		status       string
		absentAs     string
		wantIncluded bool
		wantValue    float64
		wantExcused  int
	}{
		{"absent counts as zero", "absent", "zero", true, 0, 0},
		{"absent counts as excused", "absent", "excused", false, 0, 1},
		{"not_submitted counts as zero", "not_submitted", "zero", true, 0, 0},
		{"not_submitted counts as excused", "not_submitted", "excused", false, 0, 1},
		{"excused is always excused", "excused", "zero", false, 0, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := resolveAssessment(
				AssessmentInput{Attempts: []Attempt{withStatus(1, tc.status)}},
				Policy{AbsentCountsAs: tc.absentAs},
			)
			if got.included != tc.wantIncluded {
				t.Errorf("included = %v, want %v", got.included, tc.wantIncluded)
			}
			if tc.wantIncluded {
				closeTo(t, got.normalizedValue, tc.wantValue, "normalizedValue")
			}
			if len(got.excusedScoreIDs) != tc.wantExcused {
				t.Errorf("excused count = %d, want %d", len(got.excusedScoreIDs), tc.wantExcused)
			}
		})
	}
}

// A "graded" row with no number, or a nonsensical max, is not a zero — it is
// nothing. Treating it as zero would silently invent a failing mark.
func TestGradedAttemptWithoutAUsableValueIsDropped(t *testing.T) {
	for _, tc := range []struct {
		name    string
		attempt Attempt
	}{
		{"nil raw value", Attempt{ScoreID: uuid.New(), AttemptNumber: 1, Status: "graded", MaxValue: 20}},
		{"zero max value", Attempt{ScoreID: uuid.New(), AttemptNumber: 1, Status: "graded", RawValue: ptr(10.0), MaxValue: 0}},
		{"negative max value", Attempt{ScoreID: uuid.New(), AttemptNumber: 1, Status: "graded", RawValue: ptr(10.0), MaxValue: -5}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := resolveAssessment(AssessmentInput{Attempts: []Attempt{tc.attempt}}, Policy{}); got.included {
				t.Error("expected the attempt to be dropped, not counted as zero")
			}
		})
	}
}

func TestComputeAggregations(t *testing.T) {
	component := uuid.New()
	weights := []ComponentWeight{{ComponentID: component, Weight: 1, IsRequired: true}}

	// 0.50, 0.90, 0.70 — deliberately unordered so "last" cannot pass by luck.
	assessments := []AssessmentInput{
		oneAssessment(component, graded(1, 10, 20)),
		oneAssessment(component, graded(1, 18, 20)),
		oneAssessment(component, graded(1, 14, 20)),
	}

	for _, tc := range []struct {
		aggregation string
		want        float64
	}{
		{"mean", 0.70},
		{"weighted_mean", 0.70}, // equal within-component weights reduce to the mean
		{"best", 0.90},
		{"sum", 2.10},
		{"", 0.70}, // unknown aggregation falls through to mean
	} {
		t.Run(tc.aggregation, func(t *testing.T) {
			weights[0].Aggregation = tc.aggregation
			got := Compute(assessments, weights, Policy{})
			closeTo(t, got.NormalizedValue, tc.want, "NormalizedValue")
		})
	}
}

func TestWeightedMeanHonoursWithinComponentWeights(t *testing.T) {
	component := uuid.New()
	assessments := []AssessmentInput{
		{AssessmentID: uuid.New(), ComponentID: component, WeightWithinComponent: 3, Attempts: []Attempt{graded(1, 20, 20)}},
		{AssessmentID: uuid.New(), ComponentID: component, WeightWithinComponent: 1, Attempts: []Attempt{graded(1, 0, 20)}},
	}
	got := Compute(assessments, []ComponentWeight{
		{ComponentID: component, Weight: 1, Aggregation: "weighted_mean", IsRequired: true},
	}, Policy{})
	closeTo(t, got.NormalizedValue, 0.75, "3:1 weighting of 1.0 and 0.0")
}

// "last" means latest by due date, and a nil DueAt is treated as oldest.
func TestLastAggregationUsesDueDate(t *testing.T) {
	component := uuid.New()
	early := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	late := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)

	assessments := []AssessmentInput{
		{AssessmentID: uuid.New(), ComponentID: component, WeightWithinComponent: 1, DueAt: &late, Attempts: []Attempt{graded(1, 12, 20)}},
		{AssessmentID: uuid.New(), ComponentID: component, WeightWithinComponent: 1, DueAt: &early, Attempts: []Attempt{graded(1, 20, 20)}},
	}
	weights := []ComponentWeight{{ComponentID: component, Weight: 1, Aggregation: "last", IsRequired: true}}

	closeTo(t, Compute(assessments, weights, Policy{}).NormalizedValue, 0.60, "latest due date wins")

	// With every DueAt nil there is no ordering to apply; the result must
	// still be one of the candidates rather than a panic or a zero.
	for i := range assessments {
		assessments[i].DueAt = nil
	}
	got := Compute(assessments, weights, Policy{}).NormalizedValue
	if math.Abs(got-0.60) > epsilon && math.Abs(got-1.0) > epsilon {
		t.Errorf("all-nil DueAt produced %v, want one of the candidate values", got)
	}
}

func TestDropLowestN(t *testing.T) {
	component := uuid.New()
	assessments := []AssessmentInput{
		oneAssessment(component, graded(1, 4, 20)),  // 0.20, the one to drop
		oneAssessment(component, graded(1, 16, 20)), // 0.80
		oneAssessment(component, graded(1, 20, 20)), // 1.00
	}

	got := Compute(assessments, []ComponentWeight{
		{ComponentID: component, Weight: 1, DropLowestN: 1, Aggregation: "mean", IsRequired: true},
	}, Policy{})

	closeTo(t, got.NormalizedValue, 0.90, "mean of the two kept")
	if n := got.Components[0].AssessmentsCounted; n != 2 {
		t.Errorf("AssessmentsCounted = %d, want 2", n)
	}
	if n := len(got.Components[0].DroppedScoreIDs); n != 1 {
		t.Errorf("DroppedScoreIDs = %d, want 1", n)
	}
}

// Dropping must never empty a component: a scheme that says "drop the lowest
// 5" against 3 assessments keeps one, it does not erase the component.
func TestDropLowestNAlwaysKeepsOne(t *testing.T) {
	component := uuid.New()
	assessments := []AssessmentInput{
		oneAssessment(component, graded(1, 4, 20)),
		oneAssessment(component, graded(1, 20, 20)),
	}
	got := Compute(assessments, []ComponentWeight{
		{ComponentID: component, Weight: 1, DropLowestN: 5, Aggregation: "mean", IsRequired: true},
	}, Policy{})

	if n := got.Components[0].AssessmentsCounted; n != 1 {
		t.Fatalf("AssessmentsCounted = %d, want 1", n)
	}
	closeTo(t, got.NormalizedValue, 1.0, "the highest survives")
}

func TestNegativeDropLowestNIsTreatedAsZero(t *testing.T) {
	component := uuid.New()
	got := Compute(
		[]AssessmentInput{oneAssessment(component, graded(1, 10, 20))},
		[]ComponentWeight{{ComponentID: component, Weight: 1, DropLowestN: -3, Aggregation: "mean", IsRequired: true}},
		Policy{},
	)
	if n := got.Components[0].AssessmentsCounted; n != 1 {
		t.Errorf("AssessmentsCounted = %d, want 1", n)
	}
}

// An ungraded optional component leaves the calculation entirely; an ungraded
// required one stays in the denominator. That difference is the whole point of
// IsRequired, and it is what BelowMinEvaluated later reads.
func TestUngradedComponentRequiredVersusOptional(t *testing.T) {
	graded_, empty := uuid.New(), uuid.New()
	assessments := []AssessmentInput{oneAssessment(graded_, graded(1, 16, 20))} // 0.80

	t.Run("optional drops out of both weights", func(t *testing.T) {
		got := Compute(assessments, []ComponentWeight{
			{ComponentID: graded_, Weight: 0.5, Aggregation: "mean", IsRequired: true},
			{ComponentID: empty, Weight: 0.5, Aggregation: "mean", IsRequired: false},
		}, Policy{})

		closeTo(t, got.TotalWeight, 0.5, "TotalWeight")
		closeTo(t, got.EvaluatedWeight, 0.5, "EvaluatedWeight")
		closeTo(t, got.NormalizedValue, 0.80, "NormalizedValue")
		if len(got.Components) != 1 {
			t.Errorf("Components = %d, want 1 (the optional one is omitted)", len(got.Components))
		}
	})

	t.Run("required stays in total weight only", func(t *testing.T) {
		got := Compute(assessments, []ComponentWeight{
			{ComponentID: graded_, Weight: 0.5, Aggregation: "mean", IsRequired: true},
			{ComponentID: empty, Weight: 0.5, Aggregation: "mean", IsRequired: true},
		}, Policy{})

		closeTo(t, got.TotalWeight, 1.0, "TotalWeight")
		closeTo(t, got.EvaluatedWeight, 0.5, "EvaluatedWeight")
		// Still 0.80: the grade divides by evaluated weight, so a term that is
		// only half marked is not reported as half failed.
		closeTo(t, got.NormalizedValue, 0.80, "NormalizedValue")
		if len(got.Components) != 2 {
			t.Fatalf("Components = %d, want 2", len(got.Components))
		}
		if got.Components[1].IsEvaluated {
			t.Error("the ungraded required component should be IsEvaluated=false")
		}
		if got.Components[1].NormalizedValue != nil {
			t.Error("an unevaluated component must carry no value")
		}
	})
}

func TestBelowMinEvaluated(t *testing.T) {
	graded_, empty := uuid.New(), uuid.New()
	assessments := []AssessmentInput{oneAssessment(graded_, graded(1, 16, 20))}
	weights := []ComponentWeight{
		{ComponentID: graded_, Weight: 0.4, Aggregation: "mean", IsRequired: true},
		{ComponentID: empty, Weight: 0.6, Aggregation: "mean", IsRequired: true},
	}

	// 0.4 of 1.0 evaluated.
	if got := Compute(assessments, weights, Policy{MinEvaluatedWeightForGrade: 0.5}); !got.BelowMinEvaluated {
		t.Error("0.4 evaluated against a 0.5 minimum should be below")
	}
	if got := Compute(assessments, weights, Policy{MinEvaluatedWeightForGrade: 0.4}); got.BelowMinEvaluated {
		t.Error("0.4 evaluated against a 0.4 minimum should not be below")
	}
}

func TestComputeWithNoAssessments(t *testing.T) {
	got := Compute(nil, []ComponentWeight{{ComponentID: uuid.New(), Weight: 1, IsRequired: false}}, Policy{MinEvaluatedWeightForGrade: 0.5})

	closeTo(t, got.NormalizedValue, 0, "NormalizedValue")
	closeTo(t, got.TotalWeight, 0, "TotalWeight")
	closeTo(t, got.EvaluatedWeight, 0, "EvaluatedWeight")
	// No weight at all means nothing to be below: the flag needs TotalWeight > 0.
	if got.BelowMinEvaluated {
		t.Error("BelowMinEvaluated should be false when there is no weight at all")
	}
}

// Excused attempts are reported per component so the UI can explain a gap,
// even when the component ends up with nothing graded.
func TestExcusedScoreIDsSurviveOntoTheComponent(t *testing.T) {
	component := uuid.New()
	got := Compute(
		[]AssessmentInput{oneAssessment(component, withStatus(1, "excused"))},
		[]ComponentWeight{{ComponentID: component, Weight: 1, Aggregation: "mean", IsRequired: true}},
		Policy{},
	)
	if len(got.Components) != 1 {
		t.Fatalf("Components = %d, want 1", len(got.Components))
	}
	if n := len(got.Components[0].ExcusedScoreIDs); n != 1 {
		t.Errorf("ExcusedScoreIDs = %d, want 1", n)
	}
	if got.Components[0].IsEvaluated {
		t.Error("a component with only an excused attempt is not evaluated")
	}
}

func TestRound(t *testing.T) {
	for _, tc := range []struct {
		name     string
		value    float64
		mode     string
		decimals int
		want     float64
	}{
		{"half_up rounds .5 away from zero", 0.125, "half_up", 2, 0.13},
		{"half_even rounds .5 to even", 0.125, "half_even", 2, 0.12},
		{"half_even leaves an odd .5 going up", 0.135, "half_even", 2, 0.14},
		{"floor truncates down", 0.129, "floor", 2, 0.12},
		{"ceil pushes up", 0.121, "ceil", 2, 0.13},
		{"none returns the value untouched", 0.123456, "none", 2, 0.123456},
		{"unknown mode falls through to half_up", 0.125, "no-such-mode", 2, 0.13},
		{"zero decimals", 0.6, "half_up", 0, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			closeTo(t, Round(tc.value, tc.mode, tc.decimals), tc.want, "Round")
		})
	}
}

// half_up is implemented as floor(x+0.5), which for negatives rounds towards
// positive infinity rather than away from zero. Grades are never negative, so
// this is harmless — but it is pinned here so a future refactor has to be a
// deliberate choice rather than an accident.
func TestRoundHalfUpOnNegativesRoundsTowardsPositive(t *testing.T) {
	closeTo(t, Round(-0.125, "half_up", 2), -0.12, "Round(-0.125)")
}
