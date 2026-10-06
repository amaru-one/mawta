package llm

import "testing"

// Structured outputs require every object of the schema to be closed
// (additionalProperties: false), nested ones included, and the agents'
// schemas must not be modified by the client.
func TestStrictSchemaClosesEveryObject(t *testing.T) {
	item := map[string]any{
		"type":       "object",
		"properties": map[string]any{"name": map[string]any{"type": "string"}},
	}
	in := map[string]any{
		"type": "object",
		"properties": map[string]any{
			"title": map[string]any{"type": "string"},
			"items": map[string]any{"type": "array", "items": item},
		},
		"required": []string{"title"},
	}
	out := strictSchema(in)

	if out["additionalProperties"] != false {
		t.Error("the root object is not closed")
	}
	nested := out["properties"].(map[string]any)["items"].(map[string]any)["items"].(map[string]any)
	if nested["additionalProperties"] != false {
		t.Error("an object inside an array is not closed")
	}
	if _, touched := item["additionalProperties"]; touched {
		t.Error("strictSchema modified the caller's schema")
	}
	if _, touched := in["additionalProperties"]; touched {
		t.Error("strictSchema modified the caller's root schema")
	}
	if out["properties"].(map[string]any)["title"].(map[string]any)["type"] != "string" {
		t.Error("a scalar property was changed")
	}
}

func TestPricesEstimateCost(t *testing.T) {
	p := Prices{InputPerMTok: 3, OutputPerMTok: 15, CacheReadPerMTok: 0.3}
	got := p.Cost(Usage{InputTokens: 1_000_000, OutputTokens: 100_000, CacheReadTokens: 1_000_000})
	if want := 3 + 1.5 + 0.3; got < want-1e-9 || got > want+1e-9 {
		t.Errorf("cost = %v, want %v", got, want)
	}
	if (Prices{}).Known() {
		t.Error("no prices configured means an unknown cost")
	}
}
