# Local observability stack (Grafana, Loki, Alloy)

This directory holds the local log-observability stack for Mawta: it collects
the `mawta-server` API's structured JSON stdout logs and makes them searchable
in a local Grafana, without leaving the developer's machine.

```
mawta-server JSON stdout -> Grafana Alloy -> Loki -> Grafana
```

- **Alloy** (`alloy-config.alloy`) is the collector. It reads the API
  container's logs through the Docker API socket and forwards them to Loki.
- **Loki** (`loki-config.yaml`) is the log store, on a named volume with a
  bounded 7-day retention.
- **Grafana** (`grafana/provisioning/`) is the viewer, with the Loki
  datasource and the "Mawta logs" dashboard provisioned from versioned files.

Everything runs as part of `docker-compose.local.yml`. **Deploying this to the
droplet is future work** — see [Future work](#future-work-droplet-rollout).

## Prerequisites

- **Docker Desktop** (macOS/Windows) or a Linux Docker Engine, with the
  compose plugin. The stack is developed against the repository's Docker
  Desktop workflow: the same `docker compose -f docker-compose.local.yml up`
  command used for the app starts Grafana, Loki, and Alloy alongside it.
- The Postgres prerequisite from `mawta-server/docs/local-postgres-setup.md`
  (`mawta-pg` running, migrations applied) — unchanged by this stack.
- `curl` and `python3` on the host for the smoke check (URL-encoding the
  LogQL queries).
- No Grafana Cloud account, no paid service, no droplet.

### Linux notes

- `host.docker.internal` is already wired up by `docker-compose.local.yml`
  (`extra_hosts: host-gateway`), so nothing changes there.
- The Docker socket path is `/var/run/docker.sock` on Linux as well; Alloy
  mounts it read-only. If your rootless Docker uses a different socket path,
  adjust the two `/var/run/docker.sock` mounts in `docker-compose.local.yml`.
- On Linux, `127.0.0.1:3000` is reachable only from the same host, which is
  the intent; on Docker Desktop the port mapping behaves the same way.

## Start / stop

From the repository root:

```sh
# Start the app (API + UI) together with Grafana, Loki, and Alloy.
docker compose -f docker-compose.local.yml up -d --build

# Follow the collector's own logs (useful when logs are missing).
docker compose -f docker-compose.local.yml logs -f alloy

# Stop the stack. The named volumes (loki_data, grafana_data, alloy_data)
# are preserved: logs, dashboard state, and collector positions survive.
docker compose -f docker-compose.local.yml stop

# Start again later — everything is still there.
docker compose -f docker-compose.local.yml up -d

# Tear down containers and networks, still preserving the named volumes.
docker compose -f docker-compose.local.yml down
```

### Reset (explicit, destructive)

Stopping or `down`-ing the stack never deletes the volumes. To wipe all
stored logs, Grafana state, and collector positions, run this explicitly:

```sh
docker compose -f docker-compose.local.yml down
docker volume rm mawta-local_loki_data mawta-local_grafana_data mawta-local_alloy_data
```

## Grafana access

- URL: **http://127.0.0.1:3000** (bound to `127.0.0.1` only — not reachable
  from other machines).
- Default credentials: `admin` / `admin` (Grafana asks to change the password
  on first login; the local stack does not enforce the change).
- The **Mawta logs** dashboard is provisioned automatically in the `Mawta`
  folder; the Loki datasource (`uid: mawta-loki`) is the default one. No
  manual setup.
- Loki and Alloy publish no ports at all: they are reachable only inside the
  compose network. The smoke check queries Loki through
  `docker compose exec loki` instead of a published port.

## Pinned versions

| Component | Image | Version |
|-----------|-------|---------|
| Grafana   | `grafana/grafana` | `11.3.0` |
| Loki      | `grafana/loki`    | `3.3.2`  |
| Alloy     | `grafana/alloy`   | `1.7.1`  |

These are pinned (no `latest`), and they are a compatible set: Alloy 1.7
speaks the Loki 3.x push API, and Grafana 11.3 ships the Loki datasource and
the LogQL features the dashboard uses. Upgrade them together and re-run
`deploy/observability/smoke-check.sh` afterwards.

## What is collected — and what is not

Alloy collects **only the Compose service `api`** (`com.docker.compose.service=api`),
not every container on the host. The filter is a Docker label match, not a
container-name match, so it keeps working regardless of the compose project
name. The UI, Postgres, and any unrelated container on the developer's
machine are never collected.

The API's log lines are forwarded **unaltered**: every JSON field the API
wrote — `request_id`, `task_id`, `generation_id`, the sanitized
`request`/`response` body values, `cost_usd` — reaches Loki exactly as it
was written. Alloy only adds stream labels.

### Bounded labels, unbounded fields

Loki stream labels are bounded by design; high-cardinality values must never
become labels. The stack sets exactly these labels:

| Label | Value |
|-------|-------|
| `service` | `mawta-server` |
| `environment` | `local` (from the `MAWTA_ENVIRONMENT` variable) |
| `compose_service` | `api` |
| `json_parse_failed` | `true` / `false` (from the processing stage) |
| `detected_level` | `info` / `warn` / `error` (added automatically by Loki 3.x from the log line's level) |
| `service_name` | `mawta-server` (added automatically by Loki 3.x, copied from `service`) |

The last two are added by Loki 3.x itself, not by the collector: `detected_level`
is derived from the line's `level` field and `service_name` is copied from
`service`. Both are bounded (a handful of values), so they are safe as labels.

Everything else — `request_id`, `task_id`, `generation_id`, `route`, `status`,
`kind`, `outcome`, `cost_usd`, body values — stays a **log field** inside the
JSON line, searchable with `| json` filters, and inspectable in the log
details view. The number of streams stays fixed no matter how much traffic
flows.

### JSON parse failures stay visible

A line that fails JSON parsing is forwarded with the raw line intact and
`json_parse_failed=true`, so parse failures are queryable in Loki instead of
being silently dropped:

```logql
{service="mawta-server", json_parse_failed="true"}
```

The dashboard has a "JSON parse failures" panel for exactly this.

## Example sanitized log events

The API writes one JSON object per line to stdout. Sanitized examples of the
three event types (see `mawta-server/internal/logging/logging.go` for the
complete vocabulary):

```json
{"time":"2026-09-27T12:00:00.123456789Z","level":"INFO","msg":"request","service":"mawta-server","event":"http.request","request_id":"7f3e...","method":"GET","route":"/api/v1/classes/{classID}/students","status":200,"duration_ms":12,"request":null,"request_capture":"disabled","response":null,"response_capture":"disabled"}
```

```json
{"time":"2026-09-27T12:00:01.000Z","level":"INFO","msg":"worker: job started","service":"mawta-server","event":"worker.job_started","task_id":42,"job_id":42,"kind":"grade.recompute","attempt":1,"max_attempts":3,"worker":"mawta-local"}
```

```json
{"time":"2026-09-27T12:00:02.000Z","level":"INFO","msg":"stt: transcription usage","service":"mawta-server","event":"stt.usage","task_id":42,"attempt":1,"provider":"openrouter","model":"openai/whisper-large-v3","duration_ms":1500,"outcome":"success","generation_id":"gen-1","cost_usd":0.0123,"cost_source":"provider","audio_seconds":12.5,"tokens":321}
```

No log entry contains passwords, session tokens, cookies, API keys,
authorization headers, audio, transcripts, or student data — the API's
capture policy (see `mawta-server/internal/logging/logging.go`) guarantees
that before the line ever reaches stdout, and the collector adds nothing.

## The dashboard

The **Mawta logs** dashboard (`grafana/provisioning/dashboards/mawta-logs.json`)
is provisioned from a versioned file. It has:

- **HTTP requests** — searchable by `request_id`, `route`, and `status` via
  the variables at the top of the dashboard. Click any line to open its JSON
  details (including the sanitized `request`/`response` bodies and their
  capture statuses).
- **Worker jobs** — searchable by `task_id`, `kind`, and `outcome`.
- **Transcription events** — one line per provider call with per-call
  `cost_usd`, an observed cost total (only `cost_source="provider"` lines are
  summed), and an unknown-cost count (`cost_source="unknown"`).
- **JSON parse failures** — the discoverability panel described above.
- **All API logs** — the raw search surface.

### Refresh and time range

- The dashboard auto-refreshes every **10 seconds** (top-right refresh
  picker). Set it to `Off` when inspecting a specific incident.
- The default time range is **last 1 hour**. Widen it (top-right) to see
  older logs; Loki retains 7 days (see below).
- The variables (`request_id`, `route`, `status`, `task_id`, `kind`,
  `outcome`) are regex textboxes: `.*` matches everything, `5..` matches all
  5xx statuses, and a specific `request_id` narrows to one request.

## LogQL examples for Explore

Open **Explore**, select the **Loki** datasource, and paste any of these:

```logql
# All logs from the API
{service="mawta-server"}

# HTTP requests only
{service="mawta-server"} | json | event="http.request"

# One request by its correlation id
{service="mawta-server"} | json | request_id="7f3e..."

# Errors: 5xx responses
{service="mawta-server"} | json | event="http.request" | status >= 500

# Requests to one route
{service="mawta-server"} | json | event="http.request" | route="/api/v1/classes/{classID}/students"

# Worker jobs of one kind, with outcomes
{service="mawta-server"} | json | event="worker.job_outcome" | kind="grade.recompute"

# One worker job across all its events
{service="mawta-server"} | json | task_id="42"

# Transcription usage events with a provider-reported cost
{service="mawta-server"} | json | event="stt.usage" | cost_source="provider"

# Observed transcription cost total over the last hour
sum(sum_over_time({service="mawta-server"} | json | event="stt.usage" | cost_source="provider" | unwrap cost_usd [1h]))

# Transcription calls with no reported cost
{service="mawta-server"} | json | event="stt.usage" | cost_source="unknown"

# JSON parse failures
{service="mawta-server", json_parse_failed="true"}
```

## Persistence and retention

- **Loki data** lives in the named volume `mawta-local_loki_data` (chunks,
  index, compactor working directory). It survives `stop`, `down`, and
  machine restarts.
- **Grafana state** (users, dashboard changes) lives in
  `mawta-local_grafana_data`.
- **Alloy positions** (how far the collector has read) live in
  `mawta-local_alloy_data`, so a restarted collector resumes instead of
  re-reading or losing its place.
- **Retention**: Loki keeps **7 days** (`retention_period: 168h` in
  `loki-config.yaml`, enforced by the compactor). Older data is deleted
  automatically; the volume never grows without bound.
- **Docker log rotation** is explicit in `docker-compose.local.yml`
  (`json-file` driver, `max-size: 10m`, `max-file: 3` per service): the
  container's own stdout log files are bounded too, so neither store grows
  unbounded on a long-running laptop.
- Stopping the stack preserves all three volumes; only the explicit reset
  command above removes them.

## Smoke check

With the stack running, from the repository root:

```sh
bash deploy/observability/smoke-check.sh
```

It is repeatable and self-contained. It:

1. Verifies the four services are running.
2. Verifies Grafana health, the provisioned Loki datasource, and the
   provisioned dashboard.
3. Generates synthetic HTTP traffic against `localhost:8080` with a unique
   `X-Request-ID` per run, then queries Loki to confirm the `http.request`
   events arrived with `service`, `request_id`, `route`, and `status`.
4. Confirms worker events, when present, keep `task_id` (the check itself
   enqueues no jobs, so this is a conditional assertion).
5. Restarts the collector and confirms new events keep arriving and
   previously stored logs remain queryable.

### What the smoke check does not cover

- **Transcription.** The check never triggers a transcription: it does not
  upload a voice note and cannot point the API at a fake provider. The
  transcription panels and their LogQL queries are verified manually later,
  with a real (or skipped) transcription; the queries themselves are
  documented above and in the dashboard.
- It needs no real student data, no paid transcription, no Grafana Cloud
  account, and no droplet.

## Troubleshooting

**No logs in Grafana / Loki.**

1. Is the API container running and logging?
   ```sh
   docker compose -f docker-compose.local.yml logs --tail 20 api
   ```
   You should see one JSON object per line. If not, the problem is upstream
   of the observability stack.
2. Is Alloy running and error-free?
   ```sh
   docker compose -f docker-compose.local.yml logs --tail 50 alloy
   ```
   Look for `failed to evaluate config` (config error) or Docker API errors.
3. Is the Docker socket mounted? Alloy reads logs through the Docker API:
   ```sh
   docker compose -f docker-compose.local.yml exec alloy ls -l /var/run/docker.sock
   ```
   Without the socket, discovery finds no containers and nothing is
   collected — silently. The socket is mounted **read-only** in
   `docker-compose.local.yml`; Alloy needs no write access to it.
4. Is Loki up and healthy?
   ```sh
   docker compose -f docker-compose.local.yml ps loki
   docker compose -f docker-compose.local.yml exec loki wget -qO- http://localhost:3100/ready
   ```
5. Widen the time range in Grafana. Logs older than the current range are
   invisible even when present.
6. Check the parse-failure panel: `{service="mawta-server", json_parse_failed="true"}`
   — if the API wrote a non-JSON line, it lands there instead of being
   dropped.

**Docker API access requirements.** The collector needs the Docker socket
(`/var/run/docker.sock`) mounted read-only to (a) list containers
(`discovery.docker`) and (b) stream their logs (`loki.source.docker`). It
needs no other Docker permissions: no write access to the socket, no
container start/stop, no host filesystem access. On Docker Desktop the
socket is the VM's API endpoint, which is exactly why the collector must use
the API rather than reading log files from disk — the log files live inside
the VM where the host cannot read them.

**Grafana asks for a password change.** Log in with `admin`/`admin` and
either change it or skip; the local stack does not enforce the change.

**Loki returns "entry too far behind" or drops old entries.** The API's log
lines carry their own timestamps; if the host clock and the container clock
disagree wildly, entries can fall outside Loki's acceptance window. Restart
the stack; the smoke check's restart step exercises exactly this path.

## Future work: droplet rollout

Deploying this stack to the droplet is **future work, out of scope here**.
This directory is written to be droplet-ready — the same Alloy, Loki, and
Grafana files run on Linux unchanged — but the rollout itself needs:

- **A separate Compose file** (for example `deploy/observability/docker-compose.observability.yml`)
  rather than changes to the production one; the production stack must not
  grow a Grafana dependency.
- **Grafana exposure**: on the droplet, `127.0.0.1:3000` is reachable only
  from the droplet itself. Reach it through an **SSH tunnel**
  (`ssh -L 3000:127.0.0.1:3000 <droplet>`) or an authenticated Caddy route;
  never publish it on a public interface without authentication.
- **The security weight of the Docker socket mount**: read-only or not, the
  socket grants container-log access and, in practice, broad control of the
  daemon. On a shared host this is a real decision, not a default.
- **Memory and disk sizing**: Loki's compactor and index want headroom
  (hundreds of MB), and the retention volume needs a disk budget matched to
  the retention period.
- **The `environment` label**: set `MAWTA_ENVIRONMENT` to the droplet's value
  (for example `prod`) in the new Compose file; the Alloy config reads it
  from the variable and needs no edit.

## File map

| File | Purpose |
|------|---------|
| `alloy-config.alloy` | Collector: Docker API discovery, `api`-service selection, bounded labels, JSON parse-failure marking, Loki push. |
| `loki-config.yaml` | Loki: schema v13, filesystem store on the named volume, 7-day retention. |
| `grafana/provisioning/datasources/datasource.yaml` | Loki datasource (`uid: mawta-loki`), provisioned. |
| `grafana/provisioning/dashboards/dashboard.yaml` | Dashboard provider: loads the JSON below from the mounted directory. |
| `grafana/provisioning/dashboards/mawta-logs.json` | The "Mawta logs" dashboard. |
| `smoke-check.sh` | End-to-end smoke check (see above). |
| `README.md` | This file. |
