## Purpose
The single binary entrypoint: wires config, database, HTTP server, and the in-process background worker.

## Contents
- `main.go` — loads config (`config.Load`), opens the pgx pool (`db.Open`), builds the chi router (`httpapi.New`), starts the HTTP server, and when `cfg.WorkerEnabled` starts `worker.Run` in a goroutine. Handles graceful shutdown on SIGINT/SIGTERM.

## Inputs / Outputs
Inputs: environment variables (and `.env` in dev) per `internal/config`. Outputs: HTTP server on `HTTP_ADDR`, structured slog logging, background job processing.

## Conventions & Constraints
- Keep `main.go` thin: composition only, no business logic. The worker lives behind `worker.Run(ctx, ...)` so it could later become its own binary.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
