# Instalar un colegio

Cómo poner en marcha un colegio nuevo en una base de datos recién migrada:
el colegio, sus docentes, el año escolar, el aula y las clases.

Todo ocurre como **superusuario** (`ADMIN_DATABASE_URL`). El rol `yanai_app`
está sujeto a RLS y no puede hacer nada de esto: la política de `users` prueba
la visibilidad a través de una membresía que en ese momento todavía no existe.

## Antes de empezar

Una base con la migración aplicada y sin datos:

```sh
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
```

## Paso 1 — El colegio y sus docentes

Es el único paso que no es SQL puro: las contraseñas tienen que pasar por el
bcrypt de la aplicación (`cmd/useradd`), nunca por un hash escrito a mano.

```sh
cd seed/install
# Edita el bloque de configuración: UUID, nombre del colegio, código modular,
# datos de cada docente y, sobre todo, las dos contraseñas (vienen vacías).
./01-create-school.sh --target local      # o --target droplet
```

El script crea `tenants`, `users`, `memberships` y `teachers` en una sola
transacción y después define las contraseñas. Si el colegio ya existe, aborta
sin tocar nada.

## Paso 2 — La estructura académica

Ocho archivos, **en este orden**. Son SQL puro, sin comandos con backslash, así
que se pegan tal cual en el Query Tool de pgAdmin:

| Archivo | Qué crea |
|---|---|
| `02-academic.sql` | Año escolar, trimestres, grado, sección (el aula) |
| `03-students.sql` | Estudiantes y su matrícula en la sección |
| `04-competencies.sql` | Áreas curriculares y competencias CNEB |
| `05-capabilities.sql` | Capacidades de cada competencia |
| `06-criteria.sql` | Criterios de evaluación |
| `07-scales.sql` | Escala oficial AD/A/B/C y escala interna vigesimal |
| `08-schemes.sql` | Esquemas de calificación con sus pesos |
| `09-classes.sql` | Cursos, clases, docentes titulares y horarios |

```sh
for f in seed/install/0[2-9]-*.sql; do
  psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

## Paso 3 (opcional) — Datos de demostración

```sh
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f seed/seed_demo.sql
```

Carga un año vivido: sesiones dictadas, asistencia, evaluaciones con notas,
niveles de logro y conclusiones descriptivas. Los dos primeros trimestres
quedan cerrados; el tercero, en curso y a medias. El corte entre pasado y
futuro se calcula con la fecha real en Lima, así que el archivo envejece solo.

**Es relleno para ver y probar la aplicación, no parte de instalar un colegio.**
Los estudiantes son ficticios. No lo ejecutes contra una base con datos reales.

## Qué editar para un colegio distinto

Los UUID están fijos en los archivos, a propósito: hacen que recargar sea
determinista. Para un segundo colegio hay que cambiarlos a mano.

- En `01-create-school.sh`, el bloque de configuración de arriba.
- En los ocho `.sql`, el UUID del colegio aparece en cada `insert`; los de los
  docentes aparecen en `02-academic.sql` (tutor de aula) y en `09-classes.sql`
  (quién dicta cada clase).

## Tres cosas que el esquema impone

**Los trimestres se cierran al final, no al crearse.** El trigger
`app.sync_score_denormalised()` rechaza toda nota dirigida a un trimestre
`closed` — así es como una nota ya reportada no puede cambiar después. Por eso
`02-academic.sql` los deja abiertos y el cierre de los dos primeros vive al
final de `seed_demo.sql`, con su evidencia ya dentro.

Si instalas un colegio sin cargar datos de demostración, los tres trimestres
quedan abiertos. Es el estado correcto para un año que aún no registró nada.

**Un esquema de calificación se publica después de tener sus pesos.**
`forbid_publish_without_components` es un trigger `BEFORE` normal, no diferido:
busca los pesos en el momento en que se escribe `published_at`. Por eso
`08-schemes.sql` inserta la versión sin publicar, agrega los pesos y publica
con un `UPDATE` posterior. Los pesos deben sumar exactamente 1 al hacer commit.

**Las notas y los juicios no se actualizan, se superan.** `scores`,
`criterion_scores`, `competency_term_levels` y `descriptive_conclusions` son
append-only. Una corrección marca `superseded_at` en la fila vigente e inserta
el reemplazo con `supersedes_id`. En las dos primeras lo impone un trigger que
lanza excepción ante cualquier `UPDATE`.

## Ver también

- `migrations/SPEC.md` — el esquema y sus convenciones
- `docs/local-postgres-setup.md` — levantar Postgres en local
- `../DEPLOY.md` — reiniciar la base del servidor
