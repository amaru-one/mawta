# Instalar un colegio

Un colegio nuevo se instala desde **un solo archivo JSON**. El equipo de
onboarding lo llena, y un comando lo carga en local o en el droplet. Todo entra
en una sola transacción: el colegio queda completo, o no queda nada.

Con ese archivo, un docente puede entrar a Mawta y encontrar sus aulas con sus
estudiantes, sus áreas con competencias y capacidades, sus clases, el horario
y las sesiones de cada periodo, con el tema de las que ya tengan uno.

## Los archivos

| Archivo | Para qué |
|---|---|
| `seed/onboarding/plantilla.json` | La plantilla en blanco. **Es la que se comparte** con el equipo de onboarding. |
| `seed/onboarding/ejemplo-san-felipe.json` | Un colegio completo de ejemplo (el de la demo). Sirve de referencia al llenar la plantilla. |
| `seed/onboarding/colegios/` | Donde se guardan los archivos ya llenos. **Git lo ignora**: llevan claves y datos de menores. |
| `seed/onboard.sh` | El comando que carga un archivo. |

## Paso a paso

1. Copia la plantilla a `seed/onboarding/colegios/<colegio>.json` y complétala
   (ver "Cómo se llena" más abajo). Todo lo que diga `<...>` es para
   reemplazar. Los campos con `""` son opcionales.
2. Pruébalo sin guardar nada:
   ```sh
   ./seed/onboard.sh --target local --dry-run seed/onboarding/colegios/<colegio>.json
   ```
   Si algo está mal, el comando lista **todos** los problemas a la vez, cada
   uno con su ubicación en el archivo, por ejemplo
   `aulas[0].estudiantes[3].codigo_siagie: "123" debe tener exactamente 14 dígitos`.
   `aulas[0]` es la primera aula y `estudiantes[3]` es el cuarto estudiante
   (se cuenta desde 0).
3. Cuando la prueba pasa, cárgalo de verdad (sin `--dry-run`):
   ```sh
   ./seed/onboard.sh --target local   seed/onboarding/colegios/<colegio>.json
   ./seed/onboard.sh --target droplet seed/onboarding/colegios/<colegio>.json
   ```
4. Entrega a cada docente su `usuario` y su `clave` del archivo.

Para el droplet, el JSON viaja por SSH al contenedor del API, así que nunca
queda en el disco del servidor. Hace falta haber desplegado una imagen que
incluya el binario `onboard`.

Si el colegio ya existe (mismo código modular), el comando se niega y no toca
nada. Si un `usuario` o `email` ya existe en Mawta, también se niega: una
persona solo puede pertenecer a un colegio.

### Antes de empezar

La base debe tener la migración aplicada:

```sh
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
```

## Cómo se llena

El orden del archivo es el orden de instalación, y cada sección solo usa
cosas que ya aparecieron más arriba:

**colegio → año escolar y periodos → docentes → áreas → grados → aulas y
estudiantes → clases, horario y sesiones**

Las secciones se conectan **por código**, nunca por un id: una clase dice
`"area": "MAT"`, `"aula": "1S-A"` y `"docente": "jperez"`.

- **colegio**: `codigo_modular` son los 7 dígitos del MINEDU. `tipo` es
  `publica`, `privada`, `parroquial` o `internacional`.
- **anio_escolar**: `estructura` es `bimestre`, `trimestre` o `semestre`.
  Hace falta **al menos un periodo**. Los periodos no pueden compartir un día:
  si el primero termina el 29-05, el segundo empieza el 30-05 o después.
- **docentes**: `usuario` en minúsculas y sin espacios, que es con lo que
  entra a Mawta. `clave` va de 10 a 72 caracteres.
- **areas**: cada área lleva su árbol completo:
  `competencias` → `capacidades` → `criterios` (los criterios son
  opcionales). Los códigos de competencia, capacidad y criterio no se pueden
  repetir en todo el colegio (`MAT-C1`, `MAT-C1-CAP1`, `MAT-C1-CR1`).
  `esquema_calificacion` puede ir en `null`: entonces el área recibe el
  esquema estándar (prácticas 40% descartando la más baja, exámenes 40%,
  proyectos 20%). Si se define, los pesos deben sumar exactamente 1.
- **competencias_transversales**: la plantilla ya trae las dos del CNEB.
- **grados**: `orden` es la posición en la escolaridad de 1 a 11
  (1ro de primaria = 1, 1ro de secundaria = 7).
- **aulas**: se nombran con grado y sección. El aula `"grado": "1S"`,
  `"seccion": "A"` es `"1S-A"` para las clases. `tutor` es el usuario de un
  docente, u opcional. Cada aula lista sus `estudiantes`. Si un estudiante
  tiene `tipo_documento`, también debe tener `numero_documento` (un DNI tiene
  8 dígitos).
- **clases**: cada clase es un área en un aula, con un docente. Lleva un
  `nombre` (el que ve el docente, por ejemplo "Matemática 1ro A") y un
  `codigo`. Un aula no puede tener dos clases de la misma área.
  - `horario`: al menos una franja (`dia`, `inicio`, `fin` en HH:MM). Dos
    franjas no pueden cruzarse en la misma aula ni para el mismo docente.
  - `sesiones` (opcional): el tema de una sesión concreta, por ejemplo
    `{ "fecha": "2026-03-04", "tema": "Ecuaciones" }`. La fecha tiene que caer
    en un día del horario de esa clase y dentro de un periodo.

## Qué crea el cargador además de lo que dice el archivo

- **Las sesiones.** Por cada franja del horario, una sesión en cada fecha de
  ese día de la semana dentro de cada periodo, todas en estado `scheduled`.
  La aplicación solo lee sesiones y nunca las crea, así que sin este paso el
  docente no vería ninguna.
- **Las escalas**: la oficial AD/A/B/C del MINEDU y la interna vigesimal
  (0-20).
- **Un curso por área y grado**, llamado "<área> <grado>", por ejemplo
  "Matemática 1ro". Todas las clases de esa área en ese grado lo comparten.

Los id de cada fila salen de lo que la fila es:
`md5('<tipo>:<código modular>:<clave>')::uuid`, por ejemplo
`md5('class:0723519:2026:MAT-1A')::uuid` (ver `internal/onboarding/ids.go`).
Cargar el mismo archivo en una base vacía siempre da los mismos id.

## Datos de demostración (opcional)

```sh
cp seed/onboarding/ejemplo-san-felipe.json seed/onboarding/colegios/san-felipe.json
# completa las dos claves en la copia
./seed/onboard.sh --target local seed/onboarding/colegios/san-felipe.json
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f seed/seed_demo.sql
```

`seed_demo.sql` carga un año vivido: sesiones dictadas, asistencia,
evaluaciones con notas, niveles de logro y conclusiones descriptivas. Los dos
primeros trimestres quedan cerrados; el tercero, en curso y a medias. El corte
entre pasado y futuro se calcula con la fecha real en Lima, así que el archivo
envejece solo.

**Es relleno para ver y probar la aplicación, no parte de instalar un colegio.**
Los estudiantes son ficticios. No lo ejecutes contra una base con datos reales.

## Tres cosas que el esquema impone

**Los periodos se cierran al final, no al crearse.** El trigger
`app.sync_score_denormalised()` rechaza toda nota dirigida a un trimestre
`closed`. Así, una nota ya reportada no puede cambiar después. Por eso el
cargador deja todos los periodos abiertos, y el cierre de los dos primeros de
la demo vive al final de `seed_demo.sql`, con su evidencia ya dentro.

**Un esquema de calificación se publica después de tener sus pesos.**
`check_publishable` es un trigger `BEFORE` normal, no diferido: busca los
pesos en el momento en que se escribe `published_at`. Por eso el cargador
inserta la versión sin publicar, agrega los pesos y publica con un `UPDATE`
posterior.

**Las notas y los juicios no se actualizan, se superan.** `scores`,
`criterion_scores`, `competency_term_levels` y `descriptive_conclusions` son
append-only. Una corrección marca `superseded_at` en la fila vigente e inserta
el reemplazo con `supersedes_id`. En las dos primeras lo impone un trigger que
lanza excepción ante cualquier `UPDATE`.

## Agregar un docente o cambiar una clave después

`cmd/useradd` sigue sirviendo para eso:

```sh
useradd -tenant <uuid del colegio> -username <usuario> -email <correo> \
        -given-name <nombres> -family-name <apellidos>
useradd -reset-password -username <usuario>
```

## Ver también

- `docs/local-postgres-setup.md`: levantar Postgres en local
- `../DEPLOY.md`: reiniciar la base del servidor
