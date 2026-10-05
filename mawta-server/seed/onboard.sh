#!/usr/bin/env bash
#
# Instala un colegio nuevo a partir de su archivo JSON de onboarding
# (plantilla: seed/onboarding/plantilla.json). Todo entra en una sola
# transacción: o se crea el colegio completo, o no se crea nada.
#
#   ./seed/onboard.sh --target local   --dry-run seed/onboarding/colegios/mi-colegio.json
#   ./seed/onboard.sh --target local             seed/onboarding/colegios/mi-colegio.json
#   ./seed/onboard.sh --target droplet --dry-run seed/onboarding/colegios/mi-colegio.json
#
# Para un colegio ya instalado, --sync trae su currículo al día con el
# catálogo CNEB (capacidades, estándares, desempeños y ciclo de cada grado
# que falten). Reporta los nombres distintos sin sobrescribirlos y una
# segunda ejecución no cambia nada. Cada --grado une un grado del colegio con
# un grado del catálogo (1P-6P, 1S-5S):
#
#   ./seed/onboard.sh --target local --dry-run --sync --modular 0723519 --grado 1S=1S
#
# --dry-run valida el archivo y ejecuta la carga completa, pero la deshace al
# final: úsalo siempre primero.
#
# local:   compila y ejecuta cmd/onboard desde este checkout contra el
#          contenedor mawta-pg (puerto 55432).
# droplet: ejecuta el binario onboard que ya viene en la imagen del API. El
#          JSON viaja por stdin a través de SSH, así que nunca queda un archivo
#          con claves en el disco del servidor. Requiere haber desplegado una
#          imagen que incluya onboard.
#
set -euo pipefail

# --- Conexión (edita solo si tu entorno es distinto) ----------------------
LOCAL_DB='mawta'
LOCAL_DB_USER='postgres'
LOCAL_DB_PASSWORD='mawta'   # POSTGRES_PASSWORD del contenedor local
LOCAL_DB_PORT='55432'
DROPLET_SSH_HOST='mawta'
DROPLET_API_CONTAINER='mawta-api-1'
# --------------------------------------------------------------------------

usage() { sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; }

TARGET='' DRY_RUN='' FILE='' SYNC='' MODULAR='' GRADOS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --target)  TARGET="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN='-dry-run'; shift ;;
    --sync)    SYNC=1; shift ;;
    --modular) MODULAR="${2:-}"; shift 2 ;;
    --grado)   GRADOS+=(-grado "${2:-}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*)        echo "opción desconocida: $1" >&2; exit 2 ;;
    *)         FILE="$1"; shift ;;
  esac
done

case "$TARGET" in
  local|droplet) ;;
  *) echo "error: falta --target local|droplet" >&2; exit 2 ;;
esac
if [ -n "$SYNC" ]; then
  if [ -z "$MODULAR" ] || [ ${#GRADOS[@]} -eq 0 ]; then
    echo "error: --sync requiere --modular <código> y al menos un --grado <grado>=<grado_cneb>" >&2; exit 2
  fi
  if [ -n "$FILE" ]; then
    echo "error: --sync no lleva archivo JSON" >&2; exit 2
  fi
  if [ "$TARGET" = local ]; then
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [ ! -f "$root/go.mod" ] && [ "$root" != / ]; do
      root="$(dirname "$root")"
    done
    cd "$root"
    ADMIN_DATABASE_URL="postgres://${LOCAL_DB_USER}:${LOCAL_DB_PASSWORD}@127.0.0.1:${LOCAL_DB_PORT}/${LOCAL_DB}?sslmode=disable" \
      go run ./cmd/onboard -sync -modular "$MODULAR" "${GRADOS[@]}" $DRY_RUN
  else
    ssh "$DROPLET_SSH_HOST" "docker exec $DROPLET_API_CONTAINER onboard -sync -modular $MODULAR ${GRADOS[*]} $DRY_RUN"
  fi
  exit 0
fi

if [ -z "$FILE" ]; then
  echo "error: falta el archivo JSON del colegio" >&2; exit 2
fi
if [ ! -f "$FILE" ]; then
  echo "error: no existe el archivo $FILE" >&2; exit 2
fi

if [ "$TARGET" = local ]; then
  # La raíz del módulo Go se busca subiendo desde este script, para que
  # funcione invocado desde cualquier directorio.
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while [ ! -f "$root/go.mod" ] && [ "$root" != / ]; do
    root="$(dirname "$root")"
  done
  if [ ! -f "$root/go.mod" ]; then
    echo "error: no encuentro go.mod subiendo desde $(dirname "${BASH_SOURCE[0]}")." >&2
    exit 1
  fi
  file_abs="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"
  cd "$root"
  ADMIN_DATABASE_URL="postgres://${LOCAL_DB_USER}:${LOCAL_DB_PASSWORD}@127.0.0.1:${LOCAL_DB_PORT}/${LOCAL_DB}?sslmode=disable" \
    go run ./cmd/onboard -file "$file_abs" $DRY_RUN
else
  # El contenedor del API ya trae ADMIN_DATABASE_URL desde compose.
  ssh "$DROPLET_SSH_HOST" "docker exec -i $DROPLET_API_CONTAINER onboard -file - $DRY_RUN" < "$FILE"
fi
