"""pytest-alembic's standard checks: one head, upgrade from empty, the models match the
migrated database (what `alembic check` does), and every migration downgrades cleanly."""

from pytest_alembic.tests import (  # noqa: F401
    test_model_definitions_match_ddl,
    test_single_head_revision,
    test_up_down_consistency,
    test_upgrade,
)
