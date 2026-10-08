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

Everything runs as part of `docker-compose.local.yml`. **The droplet
deployment is described below** — see
[Droplet deployment](#droplet-deployment).

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

Alloy collects **only the Compose service `api`** of the matching Compose
project (`com.docker.compose.service=api` plus
`com.docker.compose.project`, from the `MAWTA_COMPOSE_PROJECT` variable:
`mawta-local` locally, `mawta` on the droplet), not every container on the
host. The filters are Docker label matches, not container-name matches, so
they keep working regardless of the compose project name. The UI, Postgres,
and any unrelated container on the developer's machine are never collected.

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
{"time":"2026-09-27T12:00:01.000Z","level":"INFO","msg":"worker: job started","service":"mawta-server","event":"worker.job_started","task_id":42,"job_id":42,"kind":"voice_note.transcribe","attempt":1,"max_attempts":3,"worker":"mawta-local"}
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
{service="mawta-server"} | json | event="worker.job_outcome" | kind="voice_note.transcribe"

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
   collected — silently. The socket is mounted with `:ro` in
   `docker-compose.local.yml`, but `:ro` does not restrict the Docker API
   (see "Docker API access requirements" below).
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
uses no other Docker API calls. The socket, however, grants the full Docker
API regardless of the `:ro` mount flag (`:ro` only protects the socket file
itself), so the Alloy container effectively has full control of the Docker
daemon; see "Security note: the Docker socket mount" below. On Docker Desktop the
socket is the VM's API endpoint, which is exactly why the collector must use
the API rather than reading log files from disk — the log files live inside
the VM where the host cannot read them.

**Grafana asks for a password change.** Log in with `admin`/`admin` and
either change it or skip; the local stack does not enforce the change.

**Loki returns "entry too far behind" or drops old entries.** The API's log
lines carry their own timestamps; if the host clock and the container clock
disagree wildly, entries can fall outside Loki's acceptance window. Restart
the stack; the smoke check's restart step exercises exactly this path.

## Droplet deployment

The same Alloy, Loki, and Grafana files run on the droplet unchanged; only
the surrounding Compose file differs. The droplet stack is
`docker-compose.droplet.yml` in this directory, with its own fixed project
name `mawta-observability`, so its containers, network, and volumes are
completely separate from the production `mawta` project (postgres, api,
caddy). Starting, stopping, or resetting it never touches production.

```
mawta api container JSON stdout -> Alloy (Docker API) -> Loki -> Grafana
```

- **Alloy** selects the production API by two Docker labels:
  `com.docker.compose.project=mawta` (from `MAWTA_COMPOSE_PROJECT`) and
  `com.docker.compose.service=api` — not Postgres, not Caddy, not the
  observability containers themselves. The `environment` label is `prod`
  (from `MAWTA_ENVIRONMENT`).
- **Loki** keeps the same 7-day retention (`loki-config.yaml`, unchanged).
- **Grafana** is published on `127.0.0.1` only (default port 3000,
  configurable with `GRAFANA_PORT`); Loki and Alloy publish no ports. The
  operator reaches Grafana through an SSH tunnel.

### Prerequisites

1. **Merge to `main`.** The deploy workflow (`.github/workflows/deploy.yml`)
   rsyncs `deploy/` to `/srv/mawta/deploy/` on every push to `main`, so after
   the merge the droplet has `docker-compose.droplet.yml`,
   `droplet-check.sh`, `droplet.env.example`, and the shared Alloy/Loki/
   Grafana files. Nothing in this ticket touches the droplet directly.
2. **Add the variables to `/srv/mawta/.env`** (the same env file the
   production stack uses). Run these once on the droplet; the shell
   generates the password as the line is written, because an env file does
   not run commands (a literal `$(openssl ...)` inside `.env` would become
   the password itself):
   ```sh
   # on the droplet, once
   cd /srv/mawta
   echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 32)" >> .env   # REQUIRED, no default
   echo "MAWTA_ENVIRONMENT=prod" >> .env
   echo "MAWTA_COMPOSE_PROJECT=mawta" >> .env
   # echo "GRAFANA_PORT=3000" >> .env   # optional, only if 3000 is taken on loopback
   grep -c '^GRAFANA_ADMIN_PASSWORD=' .env   # must print 1
   ```
   Read the password back when you first log in with
   `grep '^GRAFANA_ADMIN_PASSWORD=' /srv/mawta/.env` (on the droplet only;
   never paste it anywhere else).
   `GRAFANA_ADMIN_PASSWORD` is required: `docker-compose.droplet.yml` uses
   `${GRAFANA_ADMIN_PASSWORD:?...}`, so `docker compose` fails fast when it
   is unset — Grafana can never start with a guessable password.

### Pre-flight checks

The droplet also runs Postgres, the API, and Caddy, so check there is
headroom for ~900 MB of observability limits (Loki 256M, Alloy 256M,
Grafana 384M) plus transient spikes:

```sh
free -m                            # memory: expect a comfortable margin over ~1 GB used
df -h /                            # disk: see the budget below
docker stats --no-stream           # per-container memory right now
docker compose --env-file /srv/mawta/.env -f /srv/mawta/deploy/docker-compose.prod.yml ps   # production is up
```

Expected steady-state disk usage of the observability stack:

| Store | Expected size |
|-------|---------------|
| Loki data (`mawta-observability_loki_data`) | ~500 MB for 7 days at moderate traffic |
| Grafana state (`mawta-observability_grafana_data`) | ~50 MB |
| Alloy positions (`mawta-observability_alloy_data`) | ~10 MB |
| Docker logs | 10 MB × 3 files = at most ~30 MB per observability container, ~90 MB for the three |

### One-time start

From `/srv/mawta` (the relative paths in the Compose file resolve from
`/srv/mawta/deploy/observability/`):

```sh
cd /srv/mawta
docker compose --env-file .env \
  -f deploy/observability/docker-compose.droplet.yml up -d
```

`up -d` on later merges to `main` re-creates only what changed.

### SSH tunnel access

Grafana is bound to the droplet's `127.0.0.1` only. From your machine:

```sh
ssh -L 3000:127.0.0.1:3000 <droplet>
```

Then open **http://127.0.0.1:3000** locally and log in as `admin` with
`GRAFANA_ADMIN_PASSWORD`. The **Mawta logs** dashboard is provisioned
automatically; the Loki datasource (`uid: mawta-loki`) is the default one.

### Verification

On the droplet (read-only; it may send one `GET /healthz` to the public
domain to produce a fresh log line):

```sh
bash /srv/mawta/deploy/observability/droplet-check.sh
```

It confirms the three services are running, Grafana is healthy, the
provisioned datasource and dashboard exist, and Loki holds recent
`{service="mawta-server", environment="prod"}` lines with `request_id`
intact. It creates no data, restarts nothing, and prints no secrets.

### Lifecycle

```sh
cd /srv/mawta
OBS="--env-file .env -f deploy/observability/docker-compose.droplet.yml"

docker compose ${OBS} start     # start after a stop or a droplet reboot
docker compose ${OBS} stop      # stop; volumes and data are preserved
docker compose ${OBS} down      # remove containers and network; volumes preserved
docker compose ${OBS} up -d     # start again after down (or after a merge to main)
```

**Upgrade.** Bump the three pinned images in
`docker-compose.droplet.yml` **together** (they are a compatible set: Alloy
1.7 speaks the Loki 3.x push API, Grafana 11.3 ships the Loki datasource and
the LogQL features the dashboard uses), merge, then on the droplet:

```sh
docker compose ${OBS} up -d      # re-creates the changed services
bash /srv/mawta/deploy/observability/droplet-check.sh
```

Keep the versions in sync with `docker-compose.local.yml` and re-run
`deploy/observability/smoke-check.sh` locally after an upgrade.

**Destructive reset (explicit).** Stopping or `down`-ing never deletes the
volumes. To wipe all stored logs, Grafana state, and collector positions:

```sh
docker compose ${OBS} down
docker volume rm mawta-observability_loki_data \
  mawta-observability_grafana_data mawta-observability_alloy_data
```

### Rollback

`docker compose ${OBS} down` removes only the `mawta-observability`
project's containers and network — the `mawta` production project is
untouched, and no production container, network, or volume is referenced
or shared. If the observability stack misbehaves, `down` (or `stop`) is a
complete rollback: production keeps running and keeps logging to stdout.

### Troubleshooting

**No logs in Grafana / Loki.**

1. Is the production API container running and logging?
   ```sh
   docker compose --env-file /srv/mawta/.env -f /srv/mawta/deploy/docker-compose.prod.yml logs --tail 20 api
   ```
   You should see one JSON object per line. If not, the problem is
   upstream of the observability stack.
2. Is Alloy running and error-free?
   ```sh
   docker compose --env-file /srv/mawta/.env -f /srv/mawta/deploy/observability/docker-compose.droplet.yml logs --tail 50 alloy
   ```
3. Is the Docker socket mounted? Alloy reads logs through the Docker API:
   ```sh
   docker compose --env-file /srv/mawta/.env -f /srv/mawta/deploy/observability/docker-compose.droplet.yml exec alloy ls -l /var/run/docker.sock
   ```
4. Is the project filter right? Alloy collects only
   `com.docker.compose.project=mawta` + `com.docker.compose.service=api`.
   Check the label on the production container:
   ```sh
   docker inspect $(docker ps --format '{{ .Names }}' | grep -m1 'mawta.*api') \
     --format '{{ .Config.Labels }}'
   ```
   `MAWTA_COMPOSE_PROJECT` in `/srv/mawta/.env` must be `mawta`.
5. Is Loki up and healthy?
   ```sh
   docker compose --env-file /srv/mawta/.env -f /srv/mawta/deploy/observability/docker-compose.droplet.yml ps loki
   docker compose --env-file /srv/mawta/.env -f /srv/mawta/deploy/observability/docker-compose.droplet.yml exec loki wget -qO- http://localhost:3100/ready
   ```
6. Widen the time range in Grafana; logs older than the range are invisible
   even when present.

**Grafana auth.** `GRAFANA_ADMIN_PASSWORD` only takes effect when Grafana
creates its database on **first start**; changing it in `.env` later does
not change an existing deployment's password. Change it with (run by the
operator, on the droplet):

```sh
docker compose --env-file .env -f deploy/observability/docker-compose.droplet.yml \
  exec grafana grafana cli admin reset-admin-password '<new>'
```

Anonymous access and sign-up are disabled
(`GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`), and
Grafana's outbound telemetry and update checks are off
(`GF_ANALYTICS_*`).

**Loki retention.** Loki keeps **7 days** (`retention_period: 168h` in
`loki-config.yaml`, enforced by the compactor). Older data is deleted
automatically; the volume never grows without bound. If disk runs short,
`docker compose ${OBS} down` plus removing `mawta-observability_loki_data`
is the explicit destructive reset above.

### Security note: the Docker socket mount

Alloy mounts `/var/run/docker.sock` into the Alloy container only — no
other observability container gets it. The `:ro` flag does **not** limit
what Alloy can do with the socket: it only stops the socket file itself
from being replaced. Any process that can connect to the socket has the
**full Docker API** — it can start, stop, and delete containers, and run a
privileged container that mounts the host filesystem, which is root on the
droplet. That is why this is a real decision on a production host, not a
default.

What actually limits the risk here: only the Alloy container gets the
socket; Alloy runs a pinned official image with a config that only reads
(`discovery.docker` and `loki.source.docker` list containers and stream
logs); and nothing in the stack is reachable from outside the droplet
(Grafana is bound to `127.0.0.1`, Loki and Alloy publish no ports). Treat a
compromise of the Alloy container as a compromise of the host.

A stronger mitigation, left as a follow-up: put a read-only Docker API
proxy (for example `tecnativa/docker-socket-proxy` with only
`CONTAINERS=1`, everything else denied, including all POST requests) in
front of the socket, and point Alloy at the proxy instead of mounting the
socket.

### Known follow-up

The production `api` container's **own** Docker log rotation is governed by
`deploy/docker-compose.prod.yml` (or the Docker daemon configuration), not
by this stack. This ticket deliberately does not change that file; the
observability containers' log rotation is explicit in
`docker-compose.droplet.yml` (`json-file`, `max-size: 10m`,
`max-file: 3`).

## File map

| File | Purpose |
|------|---------|
| `alloy-config.alloy` | Collector: Docker API discovery, project + `api`-service selection (variable-driven), bounded labels, JSON parse-failure marking, Loki push. |
| `loki-config.yaml` | Loki: schema v13, filesystem store on the named volume, 7-day retention. |
| `grafana/provisioning/datasources/datasource.yaml` | Loki datasource (`uid: mawta-loki`), provisioned. |
| `grafana/provisioning/dashboards/dashboard.yaml` | Dashboard provider: loads the JSON below from the mounted directory. |
| `grafana/provisioning/dashboards/mawta-logs.json` | The "Mawta logs" dashboard. |
| `smoke-check.sh` | End-to-end smoke check (see above). |
| `docker-compose.droplet.yml` | Droplet stack: same pinned Loki/Alloy/Grafana, project `mawta-observability`, memory limits, log rotation, Grafana on `127.0.0.1` only. |
| `droplet.env.example` | Example variables for `/srv/mawta/.env` (no real secrets). |
| `droplet-check.sh` | Read-only droplet verification (see above). |
| `README.md` | This file. |
