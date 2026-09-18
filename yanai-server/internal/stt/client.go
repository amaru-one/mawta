// Package stt sends recorded voice-note audio to OpenAI's transcription API
// and returns the Spanish text it hears. One provider, one function — see the
// package SPEC for why there is no provider interface here.
package stt

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"time"
)

const endpoint = "https://api.openai.com/v1/audio/transcriptions"

// ErrPermanent wraps a transcription failure the worker should not retry: a
// missing API key, or a non-429 4xx from OpenAI (bad/empty/unsupported
// audio). Anything else — network errors, 429, 5xx — is returned unwrapped
// so the job's normal exponential backoff applies.
var ErrPermanent = errors.New("stt: permanent failure")

type Client struct {
	apiKey     string
	model      string
	httpClient *http.Client
}

func NewClient(apiKey, model string) *Client {
	if model == "" {
		model = "gpt-4o-mini-transcribe"
	}
	return &Client{
		apiKey:     apiKey,
		model:      model,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// Transcribe sends MP3 audio — the only format voice notes are ever stored
// in, see media.CanonicalMimeType — to OpenAI and returns the Spanish text.
func (c *Client) Transcribe(ctx context.Context, audioMP3 []byte) (string, error) {
	if c.apiKey == "" {
		return "", fmt.Errorf("%w: OPENAI_API_KEY not configured", ErrPermanent)
	}

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("file", "note.mp3")
	if err != nil {
		return "", fmt.Errorf("stt: build request: %w", err)
	}
	if _, err := part.Write(audioMP3); err != nil {
		return "", fmt.Errorf("stt: build request: %w", err)
	}
	_ = writer.WriteField("model", c.model)
	_ = writer.WriteField("language", "es")
	_ = writer.WriteField("response_format", "json")
	if err := writer.Close(); err != nil {
		return "", fmt.Errorf("stt: build request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, &body)
	if err != nil {
		return "", fmt.Errorf("stt: build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", writer.FormDataContentType())

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
		return "", fmt.Errorf("%w: openai %d: %s", ErrPermanent, resp.StatusCode, truncate(respBody, 500))
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
