// Package stt sends recorded voice-note audio to OpenRouter's dedicated
// speech-to-text endpoint and returns the Spanish text it hears. One
// provider, one function — see the package SPEC for why there is no
// provider interface here.
package stt

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

const endpoint = "https://openrouter.ai/api/v1/audio/transcriptions"

// ErrPermanent wraps a transcription failure the worker should not retry: a
// missing API key, or a non-429 4xx from OpenRouter (bad/empty/unsupported
// audio, unknown model). Anything else — network errors, 429, 5xx — is
// returned unwrapped so the job's normal exponential backoff applies.
var ErrPermanent = errors.New("stt: permanent failure")

type Client struct {
	apiKey     string
	model      string
	httpClient *http.Client
}

func NewClient(apiKey, model string) *Client {
	if model == "" {
		model = "openai/whisper-large-v3"
	}
	return &Client{
		apiKey:     apiKey,
		model:      model,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

type sttRequest struct {
	Model      string     `json:"model"`
	InputAudio inputAudio `json:"input_audio"`
	Language   string     `json:"language"`
}

type inputAudio struct {
	Data   string `json:"data"`
	Format string `json:"format"`
}

// Transcribe sends MP3 audio — the only format voice notes are ever stored
// in, see media.CanonicalMimeType — to OpenRouter and returns the Spanish
// text.
func (c *Client) Transcribe(ctx context.Context, audioMP3 []byte) (string, error) {
	if c.apiKey == "" {
		return "", fmt.Errorf("%w: TRANSCRIBE_OPENROUTER_API_KEY not configured", ErrPermanent)
	}

	reqBody := sttRequest{
		Model: c.model,
		InputAudio: inputAudio{
			Data:   base64.StdEncoding.EncodeToString(audioMP3),
			Format: "mp3",
		},
		Language: "es",
	}
	encoded, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("stt: build request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(encoded))
	if err != nil {
		return "", fmt.Errorf("stt: build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("stt: request: %w", err) // network error: transient
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("stt: read response: %w", err)
	}

	if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
		return "", fmt.Errorf("stt: transient error %d: %s", resp.StatusCode, truncate(respBody, 500))
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("%w: openrouter %d: %s", ErrPermanent, resp.StatusCode, truncate(respBody, 500))
	}

	var parsed struct {
		Text string `json:"text"`
	}
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		return "", fmt.Errorf("stt: decode response: %w", err)
	}
	return parsed.Text, nil
}

func truncate(b []byte, n int) string {
	if len(b) <= n {
		return string(b)
	}
	return string(b[:n])
}
