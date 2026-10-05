package db_test

import (
	"fmt"
	"net/http"
	"testing"

	"github.com/jackc/pgx/v5/pgconn"

	"mawta-server/internal/db"
)

// A violation of a named domain constraint keeps its stable code however it
// reaches MapError: the repo prevalidates these, so the constraint only fires
// when two requests race past that check.
func TestMapErrorTranslatesNamedConstraints(t *testing.T) {
	cases := []struct {
		pgCode, constraint string
		status             int
		code               string
	}{
		{"23P01", "learning_experiences_no_overlap", http.StatusConflict, "experience_overlap"},
		{"23505", "session_outline_entries_date_key", http.StatusConflict, "session_date_taken"},
		// Any other constraint still maps by SQLSTATE class.
		{"23505", "some_other_key", http.StatusConflict, "unique_violation"},
		{"23P01", "class_schedules_no_overlap", http.StatusConflict, "exclusion_violation"},
	}
	for _, tc := range cases {
		err := fmt.Errorf("wrapped: %w", &pgconn.PgError{Code: tc.pgCode, ConstraintName: tc.constraint, Message: "raw"})
		got := db.MapError(err)
		if got.Status != tc.status || got.Code != tc.code {
			t.Errorf("%s: got %d %q, want %d %q", tc.constraint, got.Status, got.Code, tc.status, tc.code)
		}
	}

	// The table entry is not shared: changing one answer leaves the next intact.
	db.MapError(&pgconn.PgError{Code: "23P01", ConstraintName: "learning_experiences_no_overlap"}).Message = "changed"
	if got := db.MapError(&pgconn.PgError{Code: "23P01", ConstraintName: "learning_experiences_no_overlap"}); got.Message == "changed" {
		t.Error("MapError handed out its table entry by reference")
	}
}
