#!/usr/bin/env bash
# Read-only verification for the droplet observability stack.
# Run on the droplet after starting the stack.
#
# It confirms the three services are running, Grafana is healthy, the
# provisioned Loki datasource and "Mawta logs" dashboard exist, and Loki
# holds recent {service="mawta-server", environment="prod"} lines with the
# request_id correlation field intact. To guarantee a fresh line it may send
# one GET /healthz to the public domain; that is its only outbound request.
#
# It creates no data, restarts nothing, and prints no secrets: the Grafana
# password is read from the environment or the env file and passed to curl
# on stdin, never on the command line, and response bodies of authenticated
# Grafana calls are never echoed.
#
# Usage: bash /srv/mawta/deploy/observability/droplet-check.sh
# (ENV_FILE and COMPOSE_FILE can be overridden in the environment; the
# defaults are the droplet paths.)

set -euo pipefail

# The droplet Compose file requires GRAFANA_ADMIN_PASSWORD, so every
# `docker compose` call must pass the same env file the stack was started with.
ENV_FILE="${ENV_FILE:-/srv/mawta/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-/srv/mawta/deploy/observability/docker-compose.droplet.yml}"
COMPOSE="docker compose --env-file ${ENV_FILE} -f ${COMPOSE_FILE}"

# Read one variable from the env file without printing it (last assignment
# wins, surrounding quotes stripped). The process environment takes priority.
env_value() {
  local name="${1}" value="${!1:-}"
  if [ -z "${value}" ] && [ -r "${ENV_FILE}" ]; then
    value=$(grep -E "^(export +)?${name}=" "${ENV_FILE}" | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)
  fi
  printf '%s' "${value}"
}

# Public domain for the health check (generates one fresh log line)
PUBLIC_DOMAIN="$(env_value DOMAIN)"
GRAFANA_PORT_VALUE="$(env_value GRAFANA_PORT)"
GRAFANA_URL="http://127.0.0.1:${GRAFANA_PORT_VALUE:-3000}"
GRAFANA_PASSWORD="$(env_value GRAFANA_ADMIN_PASSWORD)"

# Authenticated Grafana GET. The credentials go to curl on stdin (-K -), never
# on the command line where `ps` would show them, and are never echoed.
grafana_get() {
  printf 'user = "admin:%s"\n' "${GRAFANA_PASSWORD}" | curl -sf -K - "${GRAFANA_URL}${1}" 2>/dev/null || true
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
section "1. Services are running"
# ---------------------------------------------------------------------------

for svc in loki alloy grafana; do
  state=$($COMPOSE ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="${svc}" '$1 == s {print $2}' || true)
  if [ "${state}" = "running" ]; then
    ok "${svc} is running"
  else
    fail "${svc} is not running (state: '${state:-absent}')"
  fi
done

# ---------------------------------------------------------------------------
section "2. Grafana health"
# ---------------------------------------------------------------------------

health=$(curl -sf "${GRAFANA_URL}/api/health" 2>/dev/null || true)
if echo "${health}" | grep -Eq '"database": *"ok"'; then
  ok "Grafana health endpoint answers"
else
  fail "Grafana health check failed: ${health:-no response}"
fi

# ---------------------------------------------------------------------------
section "3. Provisioned datasource and dashboard"
# ---------------------------------------------------------------------------

# The uids and the dashboard title the checks below rely on come from the
# versioned provisioning files this stack mounts; verify them against those
# files first, so a drifted file fails loudly here instead of as a confusing
# Grafana 404 below.
PROVISIONING_DIR="$(dirname "${COMPOSE_FILE}")/grafana/provisioning"
DATASOURCE_UID="mawta-loki"
DASHBOARD_UID="mawta-logs"
DASHBOARD_TITLE="Mawta logs"

if grep -q "uid: ${DATASOURCE_UID}" "${PROVISIONING_DIR}/datasources/datasource.yaml" 2>/dev/null; then
  ok "datasource uid ${DATASOURCE_UID} matches the provisioning file"
else
  fail "uid ${DATASOURCE_UID} not found in ${PROVISIONING_DIR}/datasources/datasource.yaml"
fi

if grep -q "\"uid\": \"${DASHBOARD_UID}\"" "${PROVISIONING_DIR}/dashboards/mawta-logs.json" 2>/dev/null; then
  ok "dashboard uid ${DASHBOARD_UID} matches the provisioning file"
else
  fail "uid ${DASHBOARD_UID} not found in ${PROVISIONING_DIR}/dashboards/mawta-logs.json"
fi

if grep -q "\"title\": \"${DASHBOARD_TITLE}\"" "${PROVISIONING_DIR}/dashboards/mawta-logs.json" 2>/dev/null; then
  ok "dashboard title '${DASHBOARD_TITLE}' matches the provisioning file"
else
  fail "title '${DASHBOARD_TITLE}' not found in ${PROVISIONING_DIR}/dashboards/mawta-logs.json"
fi

if [ -n "${GRAFANA_PASSWORD}" ]; then
  ds=$(grafana_get /api/datasources/uid/mawta-loki)
  if echo "${ds}" | grep -q '"type":"loki"'; then
    ok "Loki datasource is provisioned (uid mawta-loki)"
  else
    fail "Loki datasource uid mawta-loki not found (check the password and provisioning)"
  fi

  dash=$(grafana_get /api/dashboards/uid/mawta-logs)
  if echo "${dash}" | grep -q '"title":"Mawta logs"'; then
    ok "Dashboard 'Mawta logs' is provisioned"
  else
    fail "Dashboard uid mawta-logs not found (check the password and provisioning)"
  fi
else
  # A check that could not run is a failure, never a pass.
  fail "GRAFANA_ADMIN_PASSWORD not found in the environment or ${ENV_FILE}; cannot verify datasource/dashboard"
fi

# ---------------------------------------------------------------------------
section "4. Loki holds recent production logs"
# ---------------------------------------------------------------------------

# Generate one fresh log line if we know the public domain
if [ -n "${PUBLIC_DOMAIN}" ]; then
  echo "  sending GET /healthz to ${PUBLIC_DOMAIN}..."
  curl -sf "https://${PUBLIC_DOMAIN}/healthz" >/dev/null 2>&1 || true
  # Give Alloy time to forward the line and Loki time to index it (the same
  # wait the local smoke check uses).
  sleep 10
fi

# Query Loki for recent production logs with request_id
now_epoch() { date -u +%s; }
since_epoch() {
  local now
  now=$(date -u +%s)
  echo $((now - $1))
}

START=$(since_epoch 300)
END=$(now_epoch)

loki_query_range() {
  local query="${1}"
  local start="${2}"
  local end="${3}"
  $COMPOSE exec -T loki wget -qO- \
    --header="Accept: application/json" \
    "http://localhost:3100/loki/api/v1/query_range?query=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "${query}")&start=${start}000000000&end=${end}000000000&limit=100" 2>/dev/null || true
}

body=$(loki_query_range '{service="mawta-server", environment="prod"}' "${START}" "${END}")
if echo "${body}" | grep -q '"stream"'; then
  ok "Loki has recent {service=\"mawta-server\", environment=\"prod\"} streams"
else
  fail "No recent production logs in Loki: ${body:-no response}"
fi

# Check that request_id field is present in log lines
body=$(loki_query_range '{service="mawta-server", environment="prod"} | json' "${START}" "${END}")
if echo "${body}" | grep -q '"request_id"'; then
  ok "Log lines contain request_id field (correlation preserved)"
else
  fail "request_id field missing from log lines"
fi

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
  echo "See deploy/observability/README.md (Droplet deployment) for troubleshooting."
  exit 1
fi
echo "Droplet observability stack verified."
