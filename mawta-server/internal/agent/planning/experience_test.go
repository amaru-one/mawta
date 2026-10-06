package planning

import (
	"testing"
	"time"

	"mawta-server/internal/repo"
)

func day(s string) time.Time {
	d, err := time.Parse(dateLayout, s)
	if err != nil {
		panic(err)
	}
	return d
}

func win(from, to string) window {
	return window{FreeWindow: repo.FreeWindow{StartsOn: from, EndsOn: to, ClassDates: 4}, from: day(from), to: day(to)}
}

// The model picks the dates; the server only guarantees they can be saved:
// inside one free window (no overlap, inside the term), keeping the
// requested length as far as the window allows.
func TestFitDates(t *testing.T) {
	windows := []window{win("2026-06-01", "2026-06-19"), win("2026-07-06", "2026-07-31")}
	cases := []struct {
		name, start, end, wantStart, wantEnd string
	}{
		{"inside a window is kept", "2026-06-08", "2026-06-19", "2026-06-08", "2026-06-19"},
		{"crossing a busy stretch is cut at the window end", "2026-06-15", "2026-06-26", "2026-06-15", "2026-06-19"},
		{"inside a busy stretch moves to the end of the nearest earlier window", "2026-06-24", "2026-07-07", "2026-06-06", "2026-06-19"},
		{"before the term moves to the start of the first window", "2026-05-04", "2026-05-15", "2026-06-01", "2026-06-12"},
		{"after the last window moves to its end", "2026-08-10", "2026-08-21", "2026-07-20", "2026-07-31"},
		{"a reversed range keeps its start with a two-week default", "2026-07-20", "2026-07-10", "2026-07-20", "2026-07-31"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			s, e, ok := fitDates(windows, day(c.start), day(c.end))
			if !ok {
				t.Fatal("fitDates reported no window")
			}
			if got := s.Format(dateLayout) + " " + e.Format(dateLayout); got != c.wantStart+" "+c.wantEnd {
				t.Errorf("got %s, want %s %s", got, c.wantStart, c.wantEnd)
			}
			fits := false
			for _, w := range windows {
				fits = fits || (!s.Before(w.from) && !e.After(w.to))
			}
			if !fits {
				t.Errorf("%s..%s is not inside a free window", s.Format(dateLayout), e.Format(dateLayout))
			}
		})
	}

	if _, _, ok := fitDates(nil, day("2026-06-01"), day("2026-06-10")); ok {
		t.Error("with no free window there is nothing to fit")
	}
}
