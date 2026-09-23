#!/usr/bin/env bash
#
# Crea un colegio y sus dos docentes: las filas de identidad sobre las que se
# apoyan 02-academic.sql .. 09-classes.sql.
#
# Corre contra local o contra el droplet; el entorno se elige con --target.
# Es el ÚNICO paso que no es SQL puro, porque las contraseñas deben pasar por
# el hash bcrypt de la aplicación (cmd/useradd) y no por un literal escrito a
# mano.
#
#   ./01-create-school.sh --target local
#   ./01-create-school.sh --target droplet
#
# Antes de ejecutarlo, EDITA el bloque de configuración de abajo: los UUID, el
# nombre del colegio y, sobre todo, las dos contraseñas.
#
set -euo pipefail

# ===========================================================================
# CONFIGURACIÓN — edita todo esto antes de ejecutar
# ===========================================================================

# --- El colegio ------------------------------------------------------------
TENANT_ID='84d84ee4-816d-4035-a1ad-55efeee4f11e'
TENANT_NAME='I.E. San Felipe'
TENANT_MODULAR_CODE='0723519'   # código modular MINEDU, 7 dígitos
TENANT_KIND='publica'           # publica | privada | parroquial | otro
TENANT_CITY='Miraflores'
TENANT_REGION='Lima'
TENANT_TIMEZONE='America/Lima'

# --- Docente 1: dicta Matemática y es tutor de aula ------------------------
T1_USER_ID='9965b3ad-ea65-4e73-987d-f1723d1ea7f0'
T1_MEMBERSHIP_ID='9a1f41e3-c722-4ec8-aec5-8890add90e73'
T1_TEACHER_ID='d74f215c-b8be-4f62-bdd0-f725fa25ab3f'
T1_USERNAME='jeffrey'
T1_EMAIL='amaruorihuela@gmail.com'
T1_GIVEN_NAME='Jeffrey'
T1_FAMILY_NAME='Orihuela'
T1_DISPLAY_NAME='Jeffrey Orihuela'
T1_TITLE='Docente de Secundaria'
T1_PASSWORD=''   # <<< aquí va tu contraseña

# --- Docente 2: dicta Ciencias Sociales ------------------------------------
T2_USER_ID='4da6cc53-2db0-4583-8717-d2a407212c9d'
T2_MEMBERSHIP_ID='59afbc82-f9dc-4bb2-9501-d7002c091f24'
T2_TEACHER_ID='dd9d0f46-8518-4f83-9f98-5ab0c25b738b'
T2_USERNAME='gonzalo'
T2_EMAIL='gonzaloscb7@gmail.com'
T2_GIVEN_NAME='Gonzalo'
T2_FAMILY_NAME='Saavedra'
T2_DISPLAY_NAME='Gonzalo Saavedra'
T2_TITLE='Docente de Secundaria'
T2_PASSWORD=''   # <<< aquí va tu contraseña

# --- Conexión --------------------------------------------------------------
# local: contenedor Docker en esta máquina.
LOCAL_CONTAINER='mawta-pg'
LOCAL_DB='mawta'
LOCAL_DB_USER='postgres'
LOCAL_DB_PASSWORD='mawta'   # POSTGRES_PASSWORD del contenedor local
LOCAL_DB_PORT='55432'       # puerto publicado del contenedor hacia la máquina
# droplet: se llega por SSH y se opera sobre los contenedores de allá.
DROPLET_SSH_HOST='mawta'
DROPLET_PG_CONTAINER='mawta-postgres-1'
DROPLET_API_CONTAINER='mawta-api-1'
DROPLET_DB='mawta'
DROPLET_DB_USER='postgres'

# ===========================================================================
# A partir de aquí no hace falta editar nada
# ===========================================================================

TARGET=''
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
done

case "$TARGET" in
  local|droplet) ;;
  *) echo "error: falta --target local|droplet" >&2; exit 2 ;;
esac

# Las contraseñas se validan ANTES de tocar la base. Si fallaran después, el
# colegio quedaría creado con contraseñas inservibles y volver a ejecutar el
# script abortaría por colegio duplicado: un estado a medias del que solo se
# sale a mano. internal/auth exige entre 10 y 72 caracteres.
PW_MIN=10
PW_MAX=72
for var in T1_PASSWORD T2_PASSWORD; do
  pw="${!var}"
  if [ -z "$pw" ]; then
    echo "error: $var está vacía. Edita el bloque de configuración de este script" >&2
    echo "       y define la contraseña antes de ejecutarlo." >&2
    exit 2
  fi
  if [ "${#pw}" -lt "$PW_MIN" ] || [ "${#pw}" -gt "$PW_MAX" ]; then
    echo "error: $var tiene ${#pw} caracteres; deben ser entre $PW_MIN y $PW_MAX." >&2
    exit 2
  fi
done

# psql_admin: ejecuta SQL como superusuario en el entorno elegido.
psql_admin() {
  if [ "$TARGET" = local ]; then
    docker exec -i "$LOCAL_CONTAINER" psql -U "$LOCAL_DB_USER" -d "$LOCAL_DB" \
      -v ON_ERROR_STOP=1 "$@"
  else
    ssh "$DROPLET_SSH_HOST" \
      "docker exec -i $DROPLET_PG_CONTAINER psql -U $DROPLET_DB_USER -d $DROPLET_DB -v ON_ERROR_STOP=1 $*"
  fi
}

# set_password: pone la contraseña vía cmd/useradd, que aplica el mismo bcrypt
# que usa el login. Nunca se escribe un hash a mano.
# En el droplet el binario ya viene en la imagen del API; en local se compila
# al vuelo desde el checkout.
set_password() {
  local username="$1" password="$2"
  if [ "$TARGET" = local ]; then
    # La raíz del módulo Go se busca subiendo desde este script, no se asume
    # el directorio de trabajo: así funciona invocado desde cualquier sitio.
    local root; root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [ ! -f "$root/go.mod" ] && [ "$root" != / ]; do
      root="$(dirname "$root")"
    done
    if [ ! -f "$root/go.mod" ]; then
      echo "error: no encuentro go.mod subiendo desde $(dirname "${BASH_SOURCE[0]}")." >&2
      echo "       Este script debe vivir dentro del checkout de mawta-server." >&2
      return 1
    fi
    ( cd "$root" && \
      ADMIN_DATABASE_URL="postgres://${LOCAL_DB_USER}:${LOCAL_DB_PASSWORD}@127.0.0.1:${LOCAL_DB_PORT}/${LOCAL_DB}?sslmode=disable" \
      go run ./cmd/useradd -reset-password -username "$username" -password "$password" )
  else
    ssh "$DROPLET_SSH_HOST" \
      "cd /srv/mawta && set -a && . ./.env && set +a && \
       docker exec -e ADMIN_DATABASE_URL -i $DROPLET_API_CONTAINER \
         useradd -reset-password -username '$username' -password '$password'"
  fi
}

echo "==> Creando el colegio y sus docentes en: $TARGET"

# Una sola transacción: o entra todo, o no entra nada.
#
# El superusuario OMITE RLS, y eso es lo que permite insertar la fila de
# tenants y las de users antes de que exista membresía alguna. La política de
# users prueba visibilidad a través de una membership que todavía no existe,
# así que como mawta_app este bloque sería imposible.
#
# password_hash entra con un marcador que NO corresponde a ninguna contraseña:
# nadie puede iniciar sesión con él. La contraseña real la pone cmd/useradd
# inmediatamente después.
psql_admin <<SQL
begin;

do \$\$
begin
  if exists (select 1 from tenants where id = '${TENANT_ID}') then
    raise exception 'El colegio % ya existe. Este script no modifica colegios existentes.', '${TENANT_ID}';
  end if;
end
\$\$;

insert into tenants
  (id, name, modular_code, kind, city, region, timezone,
   uses_internal_grading, status)
values
  ('${TENANT_ID}', '${TENANT_NAME}', '${TENANT_MODULAR_CODE}', '${TENANT_KIND}',
   '${TENANT_CITY}', '${TENANT_REGION}', '${TENANT_TIMEZONE}', true, 'active');

-- users no lleva tenant_id: es la tabla de credenciales compartida.
insert into users
  (id, email, given_name, family_name, display_name, status, username,
   password_hash, password_changed_at, failed_login_count)
values
  ('${T1_USER_ID}', '${T1_EMAIL}', '${T1_GIVEN_NAME}', '${T1_FAMILY_NAME}',
   '${T1_DISPLAY_NAME}', 'active', '${T1_USERNAME}',
   'PENDIENTE-cmd/useradd-define-la-contrasena', now(), 0),
  ('${T2_USER_ID}', '${T2_EMAIL}', '${T2_GIVEN_NAME}', '${T2_FAMILY_NAME}',
   '${T2_DISPLAY_NAME}', 'active', '${T2_USERNAME}',
   'PENDIENTE-cmd/useradd-define-la-contrasena', now(), 0);

-- memberships_one_school_per_user es un índice único sobre (user_id) sola:
-- cada docente queda atado a este colegio y a ningún otro mientras su
-- membresía siga viva.
insert into memberships (id, tenant_id, user_id, role, status, joined_at)
values
  ('${T1_MEMBERSHIP_ID}', '${TENANT_ID}', '${T1_USER_ID}', 'teacher', 'active', now()),
  ('${T2_MEMBERSHIP_ID}', '${TENANT_ID}', '${T2_USER_ID}', 'teacher', 'active', now());

insert into teachers
  (id, tenant_id, membership_id, display_name, title, status)
values
  ('${T1_TEACHER_ID}', '${TENANT_ID}', '${T1_MEMBERSHIP_ID}',
   '${T1_DISPLAY_NAME}', '${T1_TITLE}', 'active'),
  ('${T2_TEACHER_ID}', '${TENANT_ID}', '${T2_MEMBERSHIP_ID}',
   '${T2_DISPLAY_NAME}', '${T2_TITLE}', 'active');

commit;
SQL

echo "==> Filas creadas. Definiendo contraseñas con cmd/useradd"
# Si algo falla aquí, las filas YA están comprometidas. No hay que reejecutar
# el script (abortaría por colegio duplicado): basta con repetir el reset.
if ! set_password "$T1_USERNAME" "$T1_PASSWORD" || \
   ! set_password "$T2_USERNAME" "$T2_PASSWORD"; then
  echo >&2
  echo "error: el colegio y los docentes SÍ se crearon, pero no se pudo definir" >&2
  echo "       alguna contraseña. No reejecutes este script. Repite solo:" >&2
  echo "         useradd -reset-password -username <usuario> -password <clave>" >&2
  exit 1
fi

echo
echo "Listo. Colegio '${TENANT_NAME}' con ${T1_USERNAME} y ${T2_USERNAME}."
echo "Siguiente paso: cargar 02-academic.sql .. 09-classes.sql en ese orden."
