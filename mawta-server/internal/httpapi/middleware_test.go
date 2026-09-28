package httpapi

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
)

func TestRoutePatternWithChiRoute(t *testing.T) {
	r := chi.NewRouter()
	r.Get("/api/v1/classes/{classID}/students", func(w http.ResponseWriter, r *http.Request) {
		pattern := routePattern(r)
		w.Header().Set("X-Route", pattern)
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest("GET", "/api/v1/classes/abc-123/students", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	got := w.Header().Get("X-Route")
	want := "/api/v1/classes/{classID}/students"
	if got != want {
		t.Errorf("routePattern = %q, want %q", got, want)
	}
}

func TestRoutePatternFallbackOn404(t *testing.T) {
	r := chi.NewRouter()
	r.Get("/api/v1/known", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	r.NotFound(func(w http.ResponseWriter, r *http.Request) {
		pattern := routePattern(r)
		w.Header().Set("X-Route", pattern)
		w.WriteHeader(http.StatusNotFound)
	})

	req := httptest.NewRequest("GET", "/api/v1/unknown/path", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	got := w.Header().Get("X-Route")
	want := "/api/v1/unknown/path"
	if got != want {
		t.Errorf("routePattern on 404 = %q, want %q", got, want)
	}
}

func TestRequestLoggerOutputsStructuredFields(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))

	r := chi.NewRouter()
	r.Use(requestID)
	r.Use(requestLogger(logger))
	r.Get("/api/v1/test", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest("GET", "/api/v1/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	line := strings.TrimSpace(buf.String())
	if line == "" {
		t.Fatal("expected log output, got empty")
	}
	var entry map[string]any
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("log output is not valid JSON: %v\n%s", err, line)
	}

	// Verify correlation fields
	for _, key := range []string{"request_id", "method", "route", "status", "duration_ms"} {
		if _, ok := entry[key]; !ok {
			t.Errorf("missing field %q in log entry", key)
		}
	}
	if entry["method"] != "GET" {
		t.Errorf("method = %v, want GET", entry["method"])
	}
	if entry["route"] != "/api/v1/test" {
		t.Errorf("route = %v, want /api/v1/test", entry["route"])
	}
	if entry["status"] != float64(200) {
		t.Errorf("status = %v, want 200", entry["status"])
	}
}

func TestRequestLoggerPropagatesXRequestID(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))

	r := chi.NewRouter()
	r.Use(requestID)
	r.Use(requestLogger(logger))
	r.Get("/api/v1/test", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest("GET", "/api/v1/test", nil)
	req.Header.Set("X-Request-ID", "custom-req-id")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	// Response header should propagate
	if got := w.Header().Get("X-Request-ID"); got != "custom-req-id" {
		t.Errorf("X-Request-ID response header = %q, want %q", got, "custom-req-id")
	}

	// Log entry should contain the same request_id
	var entry map[string]any
	line := strings.TrimSpace(buf.String())
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if entry["request_id"] != "custom-req-id" {
		t.Errorf("request_id in log = %v, want %q", entry["request_id"], "custom-req-id")
	}
}

func TestRequestLoggerRoutePatternWithParams(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))

	r := chi.NewRouter()
	r.Use(requestID)
	r.Use(requestLogger(logger))
	r.Get("/api/v1/classes/{classID}/students", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest("GET", "/api/v1/classes/abc/students", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	var entry map[string]any
	line := strings.TrimSpace(buf.String())
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatalf("parse: %v", err)
	}
	// Route should be the pattern, not the actual path with param values
	if entry["route"] != "/api/v1/classes/{classID}/students" {
		t.Errorf("route = %v, want /api/v1/classes/{classID}/students", entry["route"])
	}
}
