# Onboard a school

A new school is installed from **one JSON file**, into **its own, empty database**: Mawta runs
one database per school. The onboarding team fills the file in, and `onboard` loads it.
Everything runs in one transaction: the whole school is created, or nothing is saved.

The file gives each teacher their classrooms and students, subjects, classes,
timetable, and term sessions, including topics where provided. The curriculum
(competencies, capabilities, standards, and grade performances) is **not** in the
file: the loader copies it from the CNEB catalog shipped with the app
(`src/curriculum/cneb/`, transcribed from RM 281-2016 and RM 649-2016).

## Files

| File | Purpose |
| --- | --- |
| `onboarding/plantilla.json` | Blank template. **Share this file** with the onboarding team. |
| `ejemplo-san-felipe.json` in the demo folder (`mawta-demo`, kept outside this repository) | A complete example school, used by the demo. Use it as a reference for filling in the template. `mawta-demo/build.py` generates it. |
| `onboarding/colegios/` | Completed school files. **Git ignores this folder** because the files contain passwords and minors' data. |
| `onboard` | The command that loads a file, or syncs an installed school's curriculum: `uv run onboard`, or the same command inside the app's image. |
| `src/curriculum/cneb/` | The CNEB catalog: `cneb.json` (grades, cycles, expected levels), `areas.json` (areas and their competency codes), `competencias/cNN.json` (one file per CNEB competency). Data only; never edited by hand outside a reviewed transcription. |

## Step by step

1. Copy the template to `onboarding/colegios/<school>.json` and complete it
   (see "Filling in the file"). Replace every `<...>` placeholder. Fields with
   `""` are optional.
2. Validate without saving:

   ```sh
   uv run onboard -file onboarding/colegios/<school>.json -dry-run
   ```

   The command reports **all** issues together, each with its location. For
   example, `aulas[0].estudiantes[3].codigo_siagie` must contain exactly 14 digits,
   so `"123"` is invalid. `aulas[0]` is the first classroom; `estudiantes[3]` is
   the fourth student (indexes start at zero).
3. Once validation passes, load the file without `--dry-run`:

   ```sh
   uv run onboard -file onboarding/colegios/<school>.json
   ```

4. Give each teacher their `usuario` (username) and `clave` (password).

`onboard` connects as the database owner (`ADMIN_DATABASE_URL`). On a server, it runs inside the
app's container (`onboard -file -` reads the file from stdin), so the file is never stored on the
server's disk. The ops repository wraps this in `scripts/onboard.sh --target droplet`.

A database that already has a school refuses a second one without changing anything.

### Before starting

The database must be new and migrated ([local-postgres-setup.md](local-postgres-setup.md)):

```sh
uv run alembic upgrade head
```

## Filling in the file

File order is installation order; each section references only earlier entries:

**school → academic year and terms → teachers → subjects → grades → classrooms
and students → classes, timetable, and sessions**

Sections reference **codes**, never ids: a class uses `"area": "MAT"`,
`"aula": "1S-A"`, and `"docente": "jperez"`. Keep the JSON field names and enum
values exactly as specified below.

- **School (`colegio`):** `codigo_modular` is the seven-digit MINEDU code.
  `tipo` is `publica`, `privada`, `parroquial`, or `internacional`.
- **Academic year (`anio_escolar`):** `estructura` is `bimestre`, `trimestre`,
  or `semestre`. **At least one term** is required. Terms cannot share a date:
  if one ends on May 29, the next starts on May 30 or later.
  `dias_no_lectivos` lists the days without class: each entry has either
  `fecha` (one day) or `desde` and `hasta` (an inclusive range), a `tipo`
  (`feriado`, `vacaciones`, or `gestion`), and an optional `nombre`, for example
  `{ "desde": "2026-07-27", "hasta": "2026-08-07", "tipo": "vacaciones", "nombre": "Vacaciones de medio año" }`.
  Every day must fall within the academic year and be declared only once (a
  holiday inside a vacation range is already covered). Use `[]` when the school
  has none yet.
- **Teachers (`docentes`):** `usuario` is lowercase, without spaces, and is
  used to log in. `clave` contains 10 to 72 characters.
- **Subjects (`areas`):** `codigo` is a catalog area code (`MAT`, `CCSS`, `PS`,
  `DPCC`, `EF`, …; see `curriculum/cneb/areas.json`) and `nombre` is how the
  school names it. The loader copies that area's competencies (`MAT-C1`…),
  capabilities (`MAT-C1-CAP1`…), standards, and the performances of the school's
  grades. An area the catalog does not have yet is rejected; the catalog grows
  area by area. `criterios_legacy` (optional, normally `[]`) keeps criteria a
  school already uses, each with `codigo`, `descripcion`, and the `capacidad`
  code it belongs to.
- **Cross-curricular competencies (`competencias_transversales`):** a list of
  catalog codes; the template includes both (`TR-C1`, `TR-C2`).
- **Grades (`grados`):** `orden` is the schooling position, from 1 to 11
  (first primary grade = 1; first secondary grade = 7). `grado_cneb` is the
  catalog grade (`1P`–`6P`, `1S`–`5S`); it sets the grade's level and cycle and
  selects which performances are loaded.
- **Classrooms (`aulas`):** identified by grade and section. A classroom with
  `"grado": "1S"` and `"seccion": "A"` is referenced as `"1S-A"` by classes.
  `tutor` is an optional teacher username. Each classroom lists its `estudiantes`.
  A student with `tipo_documento` must also have `numero_documento` (DNI: eight digits).
- **Classes (`clases`):** a subject taught in a classroom by a teacher, with a
  displayed `nombre` (for example, "Mathematics, first secondary grade, section A")
  and a `codigo`. A classroom cannot have two classes for the same subject.
  - `horario`: at least one slot (`dia`, `inicio`, `fin`, using HH:MM). Slots
    cannot overlap for the same classroom or teacher.
  - `sesiones` (optional): topics for specific sessions, such as
    `{ "fecha": "2026-03-04", "tema": "Equations" }`. The date must match the
    class timetable, fall within a term, and not be a `dias_no_lectivos` day.

## What the loader creates beyond the file

- **Sessions:** one session for every matching timetable date in each term,
  all with `scheduled` status, except on `dias_no_lectivos` days. The
  application reads sessions but does not create them, so teachers would have
  none without this step.
- **Days without class:** one `non_teaching_days` row per declared day (a range
  becomes one row per date, weekends included). Planning uses them to count
  class dates and lay out sessions.
- **Scales:** the official MINEDU AD/A/B/C scale.
- **Curriculum from the catalog:** for each subject, its competencies and
  capabilities, the standards (levels 1–8) of those competencies, the
  performances of the school's grades, and the (modality, cycle) → expected level
  rows of the school's cycles. A performance is *in progress* towards its cycle's
  level unless its grade is the last of the cycle; neither value is in the data
  files.
- **One course per subject and grade**, named "<subject> <grade>" (for example,
  "Mathematics, first secondary grade"). Classes for that subject and grade share it.

Each row's id derives from its identity:
`md5('<type>:<modular code>:<key>')::uuid`, for example
`md5('class:0723519:2026:MAT-1A')::uuid` (see `src/onboarding/__init__.py`), and the school's
own row is `md5('school:<modular code>:')::uuid`.
Loading the same file into an empty database produces the same ids.

## Updating an existing school's curriculum

A school installed before the catalog existed, or before an area was added to
it, is brought up to date with `--sync`. Each `--grado` maps one of the school's
grade codes to a catalog grade:

```sh
uv run onboard -sync -modular 0723519 -grado 1S=1S -dry-run
uv run onboard -sync -modular 0723519 -grado 1S=1S
```

The modular code must be the one of the school in this database; another one is refused.

The sync matches the school's competencies and capabilities by code and inserts
what is missing (capabilities, standards, performances of the mapped grades,
expected-level rows) and sets the mapped grades' level and cycle. It does not
add subjects the school does not have. When a name differs from the catalog, it
**reports** the difference and leaves the school's name alone. It runs in one
transaction, and a second run changes nothing.

## Demo data (optional)

The demo school, I.E. San Felipe, lives outside this repository, in the `mawta-demo` folder. It has its generator,
the school's JSON, `seed_demo.sql` (a lived school year: T-I and T-II closed with planning, scores,
levels, conclusions and voice notes; T-III open and unplanned) and `PERFILES.md`, the answer key
of every student's profile. Load it into a new, migrated database:

```sh
uv run onboard -file ../mawta-demo/ejemplo-san-felipe.json
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f ../mawta-demo/seed_demo.sql
```

**This is sample data for exploring and testing the application, not a school installation.**
The students are fictional. `seed_demo.sql` refuses a database without the demo school, and one
where it is already loaded.

## Two rules enforced by the schema

**Terms close at the end, not at creation.** The `app.sync_score_denormalised()`
trigger rejects scores for a `closed` term, preventing changes to reported
grades. The loader leaves all terms open. The demo's `seed_demo.sql` closes its first two terms
only after inserting their evidence.

**Scores and judgments are superseded, not overwritten.** `scores`,
`competency_term_levels`, and `descriptive_conclusions`
retain replaced records. Corrections mark the current row's `superseded_at`
and insert a replacement with `supersedes_id`. For `scores`, a
trigger rejects updates to score values.

## Adding a teacher or changing a password

Use `useradd` (`uv run useradd …`, or the same command inside the app's container). It asks
for the password, or takes `-password` or `-generate-password`:

```sh
useradd -username <username> -email <email> -given-name <given-names> -family-name <family-names>
useradd -username <username> -role director -no-teacher-profile -email <email> \
        -given-name <given-names> -family-name <family-names>
useradd -reset-password -username <username>
```

## See also

- [local-postgres-setup.md](local-postgres-setup.md): start PostgreSQL locally.
- The ops repository's README: a new school database on the server.
