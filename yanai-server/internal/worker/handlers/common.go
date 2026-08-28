// Package handlers implements the per-kind job handlers dispatched by
// internal/worker's registry. Each handler takes plain arguments (job id,
// raw JSON payload) rather than a worker.Job, so this package never needs
// to import worker — avoiding an import cycle back through the registry.
//
// There is exactly one kind: grade.recompute, which maintains computed_grades
// for the school's optional internal weighted system. The official record —
// the nivel de logro per competencia under RVM 094-2020 — is asserted by a
// teacher through the HTTP API and is never produced by a job.
package handlers
