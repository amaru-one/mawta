"""Onboarding: the catalog, the file validation and the loader."""

import copy
import json
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import DictRow, dict_row

import curriculum
from db import returned
from onboarding import derive_id
from onboarding import load as loader
from onboarding import spec as spec_mod
from onboarding.validate import ValidationErrors, validate

SEED = Path(__file__).resolve().parents[1] / "seed" / "onboarding"
EXAMPLE = SEED / "ejemplo-san-felipe.json"


@pytest.fixture(scope="module")
def cat():
    return curriculum.load()


def example_spec():
    return spec_mod.decode(EXAMPLE.read_text(encoding="utf-8"))


def test_catalog_loads_and_resolves_codes(cat):
    assert cat.fuente
    assert cat.expected_level("ebr", "ciclo_vii") == 7
    mat = cat.competencia_by_code("MAT-C1")
    assert mat is not None and mat["capacidades"]
    assert curriculum.capability_code("MAT-C1", 2) == "MAT-C1-CAP2"
    # only the last grade of a cycle reaches the standard
    assert cat.en_proceso("1S") and not cat.en_proceso(cat.last_grade_of_cycle("ciclo_vi"))


def test_catalog_rejects_unknown_keys(tmp_path):
    root = tmp_path / "cneb"
    (root / "competencias").mkdir(parents=True)
    (root / "cneb.json").write_text(json.dumps({"fuente": "x", "grados": [], "oops": 1}))
    (root / "areas.json").write_text(json.dumps({"areas": [], "transversales": []}))
    with pytest.raises(curriculum.CatalogError) as err:
        curriculum.load(root)
    assert "oops" in str(err.value)


def test_example_file_is_valid(cat):
    validate(example_spec(), cat)


def test_template_reports_every_unfilled_placeholder(cat):
    spec = spec_mod.decode((SEED / "plantilla.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationErrors) as err:
        validate(spec, cat)
    assert len(err.value.errors) > 3
    assert all(": " in e for e in err.value.errors)


def test_unknown_key_and_wrong_type_are_decode_errors():
    with pytest.raises(spec_mod.DecodeError, match="apellido_paterrno"):
        spec_mod.decode('{"aulas": [{"estudiantes": [{"apellido_paterrno": "x"}]}]}')
    with pytest.raises(spec_mod.DecodeError, match="anio"):
        spec_mod.decode('{"anio_escolar": {"anio": "2026"}}')
    with pytest.raises(spec_mod.DecodeError, match="línea"):
        spec_mod.decode("{not json")


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda s: setattr(s.colegio, "codigo_modular", "123"), "7 dígitos"),
        (lambda s: setattr(s.docentes[0], "usuario", "Bad User"), "minúsculas"),
        (lambda s: setattr(s.clases[0], "area", "NOPE"), "no está en la lista de áreas"),
        (lambda s: setattr(s.clases[0], "aula", "9X-Z"), "no existe"),
        (lambda s: setattr(s.anio_escolar, "estructura", "decenio"), "no es válido"),
    ],
)
def test_validation_names_the_problem(cat, mutate, fragment):
    spec = copy.deepcopy(example_spec())
    mutate(spec)
    with pytest.raises(ValidationErrors) as err:
        validate(spec, cat)
    assert any(fragment in e for e in err.value.errors), err.value.errors


def test_ids_match_postgres_md5(databases):
    with psycopg.Connection[DictRow].connect(databases.admin_url, row_factory=dict_row) as conn:
        row = returned(conn.execute("select md5('student:0723519:EST-1')::uuid as id").fetchone())
    assert derive_id("student", "0723519", "EST-1") == row["id"]


def test_load_creates_the_school_and_rolls_back(databases, cat):
    spec = example_spec()
    with psycopg.Connection[DictRow].connect(databases.admin_url, row_factory=dict_row) as conn:
        summary = loader.load(conn, spec, cat, 4)
        assert summary.docentes == len(spec.docentes) and summary.sesiones > 0
        assert summary.estudiantes == sum(len(a.estudiantes) for a in spec.aulas)
        mod = spec.colegio.codigo_modular
        row = returned(
            conn.execute("select id from tenants where modular_code = %s", (mod,)).fetchone()
        )
        assert row["id"] == derive_id("tenant", mod, "")
        # a second load of the same school in the same transaction is refused up front
        with pytest.raises(ValidationErrors, match="ya existe"):
            loader.load(conn, spec, cat, 4)
        conn.rollback()
        gone = conn.execute("select count(*) as n from tenants where modular_code = %s", (mod,))
        assert returned(gone.fetchone())["n"] == 0


def test_sync_is_idempotent_on_a_freshly_loaded_school(databases, cat):
    from onboarding import sync as syncer

    spec = example_spec()
    grade_map = {g.codigo: g.grado_cneb for g in spec.grados}
    with psycopg.Connection[DictRow].connect(databases.admin_url, row_factory=dict_row) as conn:
        loader.load(conn, spec, cat, 4)
        mod = spec.colegio.codigo_modular
        first = syncer.sync_curriculum(conn, cat, mod, grade_map)
        second = syncer.sync_curriculum(conn, cat, mod, grade_map)
        assert first.competencias > 0 and first.renamed == []
        assert (second.capacidades, second.estandares, second.desempenos) == (0, 0, 0)
        assert second.niveles_esperados == 0 and second.grados == 0
        conn.rollback()
