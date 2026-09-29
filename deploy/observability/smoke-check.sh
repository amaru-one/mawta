#!/usr/bin/env bash
# End-to-end smoke check for the local Mawta observability stack.
#
# Verifies the whole pipeline — mawta-server JSON stdout -> Alloy -> Loki ->
# Grafana — against the running docker-compose.local.yml stack:
#
#   1. Grafana health, provisioned Loki datasource, provisioned dashboard.
#   2. Synthetic HTTP traffic against the API (localhost:8080), then Loki
#      queries confirming the http.request events arrived with their
#      expected fields (service, request_id, route, status).
#   3. Worker events, when present, keep task_id.
#   4. Collector restart: new events keep arriving and previously stored
#      logs remain queryable (Loki data and Alloy positions persist).
#
# It never triggers a transcription (no voice-note upload, no fake provider),
# needs no real student data, no paid service, no Grafana Cloud account, and
# no droplet. The transcription panels of the dashboard are verified
# manually later; see README.md ("What the smoke check does not cover").
#
# Usage (from the repository root, with the stack running):
#   bash deploy/observability/smoke-check.sh
#
# Exit status: 0 when every check passes, 1 otherwise.

set -euo pipefail

COMPOSE_FILE="docker-compose.local.yml"
COMPOSE="docker compose -f ${COMPOSE_FILE}"

# The API is published on localhost:8080 by docker-compose.local.yml.
API_URL="http://localhost:8080"
# Grafana is published on 127.0.0.1:3000 only.
GRAFANA_URL="http://127.0.0.1:3000"
GRAFANA_USER="admin"
GRAFANA_PASS="admin"

# Loki is NOT published: queries go through the loki container itself.
# The loki image has no `date`; compute the epoch bounds on the host.
now_epoch() { date -u +%s; }
since_epoch() { # $1: seconds back
  local now
  now=$(date -u +%s)
  echo $((now - $1))
}

loki_query_range() {
  # $1: LogQL query, $2: start epoch, $3: end epoch
  local query="${1}"
  local start="${2}"
  local end="${3}"
  $COMPOSE exec -T loki wget -qO- \
    --header="Accept: application/json" \
    "http://localhost:3100/loki/api/v1/query_range?query=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "${query}")&start=${start}000000000&end=${end}000000000&limit=5000" 2>/dev/null
}

PASS=0
FAIL=0

ok() {
  PASS=$((PASS + 1))
  printf '  \033[32mPASS\033[0m %s\n' "${1}"
}

fail() {
  FAIL=$((FAIL + 1))
  printf '  \033[31mFAIL\033[0m %s\n' "${1}"
}

section() {
  printf '\n== %s ==\n' "${1}"
}

# ---------------------------------------------------------------------------
section "1. Stack is up"
# ---------------------------------------------------------------------------

for svc in api loki alloy grafana; do
  state=$($COMPOSE ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="${svc}" '$1 == s {print $2}')
  if [ "${state}" = "running" ]; then
    ok "${svc} is running"
  else
    fail "${svc} is not running (state: '${state:-absent}'). Start the stack: docker compose -f ${COMPOSE_FILE} up -d --build"
  fi
done

# ---------------------------------------------------------------------------
section "2. Grafana health and provisioning"
# ---------------------------------------------------------------------------

health=$(curl -sf "${GRAFANA_URL}/api/health" 2>/dev/null || true)
if echo "${health}" | grep -Eq '"database": *"ok"'; then
  ok "Grafana health endpoint answers (database ok)"
else
  fail "Grafana health endpoint did not answer: ${health:-no response}"
fi

ds=$(curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" "${GRAFANA_URL}/api/datasources/uid/mawta-loki" 2>/dev/null || true)
if echo "${ds}" | grep -q '"type":"loki"'; then
  ok "Loki datasource is provisioned (uid mawta-loki)"
else
  fail "Loki datasource uid mawta-loki not found: ${ds:-no response}"
fi

dash=$(curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" "${GRAFANA_URL}/api/dashboards/uid/mawta-logs" 2>/dev/null || true)
if echo "${dash}" | grep -q '"title":"Mawta logs"'; then
  ok "Dashboard 'Mawta logs' is provisioned (uid mawta-logs)"
else
  fail "Dashboard uid mawta-logs not found: ${dash:-no response}"
fi

# ---------------------------------------------------------------------------
section "3. Synthetic HTTP traffic"
# ---------------------------------------------------------------------------

# A unique request id per run, so the Loki query below can find exactly this
# run's traffic and the check is repeatable.
REQ_ID="smoke-$(date +%s)-$$"
echo "  generating traffic with X-Request-ID: ${REQ_ID}"

# /healthz is a real route (router.go mounts the request logger globally), so
# each curl produces one http.request event with route=/healthz. A second,
# unmatched URL produces one with the raw path as its route. Neither touches
# student data, sessions, or transcription.
curl -sf -H "X-Request-ID: ${REQ_ID}" "${API_URL}/healthz" >/dev/null || true
curl -sf -H "X-Request-ID: ${REQ_ID}" "${API_URL}/healthz" >/dev/null || true
curl -s -H "X-Request-ID: ${REQ_ID}" "${API_URL}/api/v1/definitely-not-a-route" >/dev/null || true

# Give Alloy a moment to forward and Loki a moment to index.
echo "  waiting for collection (10s)..."
sleep 10

# ---------------------------------------------------------------------------
section "4. Loki received the events with their fields"
# ---------------------------------------------------------------------------

START=$(since_epoch 120)
END=$(now_epoch)

# Extract the raw log lines from a Loki query_range response. The lines are
# JSON strings inside Loki's JSON envelope, so plain grep on the envelope
# would see escaped quotes; this decodes them first.
loki_lines() {
  # $1: the query_range response body
  python3 -c '
import json, sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
for r in d.get("data", {}).get("result", []):
    for _, line in r.get("values", []):
        print(line)
' "${1:-}"
}

# The exact request_id: proves the correlation field survived the pipeline.
body=$(loki_query_range '{service="mawta-server"} | json | request_id="'${REQ_ID}'" | event="http.request"' "${START}" "${END}")
lines=$(loki_lines "${body}")
if echo "${lines}" | grep -q '"event":"http.request"'; then
  ok "http.request events for request_id ${REQ_ID} are in Loki"
else
  fail "no http.request events for request_id ${REQ_ID} in Loki: ${body:-no response}"
fi

# Expected fields on the healthz events: route, status, method, duration_ms.
body=$(loki_query_range '{service="mawta-server"} | json | request_id="'${REQ_ID}'" | event="http.request" | route="/healthz"' "${START}" "${END}")
lines=$(loki_lines "${body}")
if echo "${lines}" | grep -q '"status":200'; then
  ok "route=/healthz events carry status 200"
else
  fail "route=/healthz events missing or not status 200: ${lines:-no lines}"
fi

# An unmatched /api/v1 URL: chi reports it as route "/api/v1/*" with status 404.
body=$(loki_query_range '{service="mawta-server"} | json | request_id="'${REQ_ID}'" | event="http.request" | route="/api/v1/*"' "${START}" "${END}")
lines=$(loki_lines "${body}")
if echo "${lines}" | grep -q '"status":404'; then
  ok "unmatched route event carries status 404"
else
  fail "unmatched route event missing or not status 404: ${lines:-no lines}"
fi

# Bounded labels: the stream selector matches, and the environment label is
# the one docker-compose.local.yml sets.
body=$(loki_query_range '{service="mawta-server", environment="local", compose_service="api"}' "${START}" "${END}")
if echo "${body}" | grep -q '"stream"'; then
  ok "bounded labels present (service, environment=local, compose_service=api)"
else
  fail "no stream for {service=\"mawta-server\", environment=\"local\", compose_service=\"api\"}: ${body:-no response}"
fi

# Worker events, when present, keep task_id. The smoke check does not enqueue
# jobs, so this is a conditional check: it only asserts when such events exist.
body=$(loki_query_range '{service="mawta-server"} | json | event=~"worker.*"' "${START}" "${END}")
lines=$(loki_lines "${body}")
if [ -n "${lines}" ]; then
  if echo "${lines}" | grep -q '"task_id"'; then
    ok "worker events present and carry task_id"
  else
    fail "worker events present but missing task_id: ${lines}"
  fi
else
  ok "no worker events in the window (expected: the smoke check enqueues none)"
fi

# ---------------------------------------------------------------------------
section "5. Collector restart: continuity"
# ---------------------------------------------------------------------------

# Restart Alloy. Its positions live in the alloy_data named volume, and
# Loki's data in loki_data, so after the restart: (a) previously stored logs
# are still queryable, and (b) new events keep arriving.
echo "  restarting the collector..."
$COMPOSE restart alloy >/dev/null 2>&1
sleep 10

REQ_ID2="smoke-after-restart-$(date +%s)-$$"
echo "  generating post-restart traffic with X-Request-ID: ${REQ_ID2}"
curl -sf -H "X-Request-ID: ${REQ_ID2}" "${API_URL}/healthz" >/dev/null || true
sleep 10

START2=$(since_epoch 60)
END2=$(now_epoch)

body=$(loki_query_range '{service="mawta-server"} | json | request_id="'${REQ_ID2}'" | event="http.request"' "${START2}" "${END2}")
lines=$(loki_lines "${body}")
if echo "${lines}" | grep -q '"status"'; then
  ok "new events arrive after the collector restart"
else
  fail "no events after the collector restart: ${lines:-no lines}"
fi

# Old logs remain queryable: the pre-restart request_id must still resolve.
body=$(loki_query_range '{service="mawta-server"} | json | request_id="'${REQ_ID}'" | event="http.request"' "${START}" "${END2}")
lines=$(loki_lines "${body}")
if echo "${lines}" | grep -q '"status"'; then
  ok "pre-restart logs remain queryable"
else
  fail "pre-restart logs are gone: ${lines:-no lines}"
fi

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
  echo "See deploy/observability/README.md (Troubleshooting) for missing logs."
  exit 1
fi
echo "Observability stack verified end to end."
