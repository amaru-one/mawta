"""Install a new school from one onboarding JSON file (see seed/onboarding/plantilla.json and
docs/school-onboarding.md). Everything goes in one transaction: the school is fully created or not
at all.

    onboard -file colegio.json            # load
    onboard -file colegio.json -dry-run   # validate and roll back
    onboard -file - < colegio.json        # read from stdin (the droplet path)

The curriculum tree is not in the file: it is copied from the CNEB catalog shipped with this
package (curriculum/cneb).

For a school that already exists, the sync brings its curriculum up to date with the catalog, in
one transaction and with the same dry-run:

    onboard -sync -modular 0723519 -grado 1S=1S [-dry-run]
"""

import argparse
import sys

import psycopg
from psycopg.rows import DictRow, dict_row

import curriculum
from onboarding import load as loader
from onboarding import spec as spec_mod
from onboarding import sync as syncer
from onboarding.validate import ValidationErrors, validate
from settings import Settings


class OnboardError(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="onboard", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("-file", "--file", default="", help="archivo JSON del colegio, o - para stdin")
    p.add_argument("-dry-run", "--dry-run", action="store_true",
                   help="valida y ejecuta todo en una transacción que luego se deshace")  # fmt: skip
    p.add_argument("-sync", "--sync", action="store_true",
                   help="sincroniza el currículo CNEB de un colegio ya instalado")  # fmt: skip
    p.add_argument("-modular", "--modular", default="", help="código modular (con -sync)")
    p.add_argument("-grado", "--grado", action="append", default=[],
                   help="con -sync: <grado del colegio>=<grado CNEB>, ej. 1S=1S; se repite")  # fmt: skip
    return p


def _admin_url(settings: Settings, what: str) -> str:
    if not settings.admin_database_url:
        raise OnboardError(
            f"ADMIN_DATABASE_URL es obligatoria (una conexión de superusuario; mawta_app no "
            f"puede {what})"
        )
    return settings.admin_database_url


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # The catalog is an input, not a runtime option: a process carrying a broken catalog must
    # refuse to do anything at all.
    cat = curriculum.load()
    if args.sync:
        return _run_sync(cat, args.modular, args.grado, args.dry_run)
    if not args.file:
        raise OnboardError("falta -file (o -sync -modular <código>)")
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    try:
        spec = spec_mod.decode(text)
    except spec_mod.DecodeError as exc:
        raise OnboardError(str(exc)) from None
    # Validate before connecting, so a file full of typos is reported even when no database is
    # reachable.
    validate(spec, cat)
    settings = Settings()  # pyright: ignore[reportCallIssue]
    url = _admin_url(settings, "crear un colegio")
    with psycopg.Connection[DictRow].connect(url, row_factory=dict_row) as conn:
        summary = loader.load(conn, spec, cat, settings.bcrypt_cost)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    print(summary, end="")
    if args.dry_run:
        print("\nPRUEBA (-dry-run): todo es válido, pero no se guardó nada.")
    else:
        print("\nListo. Entrega a cada docente su usuario y la clave del archivo.")
    return 0


def _run_sync(cat, modular: str, grados: list[str], dry_run: bool) -> int:
    if not modular:
        raise OnboardError("-sync requiere -modular <código modular del colegio>")
    if not grados:
        raise OnboardError(
            "-sync requiere al menos un -grado <grado>=<grado_cneb>, por ejemplo -grado 1S=1S"
        )
    grade_map: dict[str, str] = {}
    for item in grados:
        codigo, sep, cneb = item.partition("=")
        if not sep or not codigo or not cneb:
            raise OnboardError(
                f'-grado "{item}": debe tener la forma <grado>=<grado_cneb>, por ejemplo 1S=1S'
            )
        if cneb not in cat.grado:
            raise OnboardError(
                f'-grado "{item}": "{cneb}" no es un grado del catálogo CNEB; los grados son: '
                f"{cat.grade_list()}"
            )
        if codigo in grade_map:
            raise OnboardError(
                f'-grado: el grado "{codigo}" aparece dos veces (={grade_map[codigo]} y ={cneb})'
            )
        grade_map[codigo] = cneb
    settings = Settings()  # pyright: ignore[reportCallIssue]
    url = _admin_url(settings, "escribir el currículo")
    with psycopg.Connection[DictRow].connect(url, row_factory=dict_row) as conn:
        try:
            report = syncer.sync_curriculum(conn, cat, modular, grade_map)
        except syncer.SyncError as exc:
            raise OnboardError(str(exc)) from None
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    print(report, end="")
    if dry_run:
        print("\nPRUEBA (-dry-run): nada se guardó.")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except ValidationErrors as exc:
        print(
            f"El archivo tiene {len(exc.errors)} problema(s). No se cargó nada.\n", file=sys.stderr
        )
        for line in exc.errors:
            print(f"  - {line}", file=sys.stderr)
        sys.exit(1)
    except (OnboardError, RuntimeError, OSError, curriculum.CatalogError) as exc:
        print(f"onboard: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
