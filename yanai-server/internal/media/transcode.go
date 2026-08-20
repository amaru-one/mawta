// Package media normalizes browser-recorded audio into one canonical format.
//
// Chrome's MediaRecorder produces audio/webm;codecs=opus; Safari, which has
// no WebM support at all (decoding included), produces audio/mp4. A note
// recorded in one browser is therefore silently undecodable in the other.
// Transcoding every upload to MP3 — decodable by every major browser's
// <audio> element and Web Audio decodeAudioData — removes the mismatch at
// the source instead of storing whatever codec the recording browser chose.
package media

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
)

const CanonicalMimeType = "audio/mpeg"

func TranscodeToMP3(ctx context.Context, input []byte) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "ffmpeg",
		"-hide_banner", "-loglevel", "error",
		"-i", "pipe:0",
		"-vn",
		"-ac", "1",
		"-ar", "44100",
		"-b:a", "96k",
		"-f", "mp3",
		"pipe:1",
	)
	cmd.Stdin = bytes.NewReader(input)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("ffmpeg transcode: %w: %s", err, stderr.String())
	}
	if stdout.Len() == 0 {
		return nil, fmt.Errorf("ffmpeg transcode produced no output: %s", stderr.String())
	}
	return stdout.Bytes(), nil
}
