"""Every Postgres object Alembic manages through alembic_utils, in creation order."""

from mawta_schema.functions import FUNCTIONS
from mawta_schema.policies import POLICIES
from mawta_schema.triggers import TRIGGERS
from mawta_schema.views import VIEWS

ALL = [*FUNCTIONS, *TRIGGERS, *VIEWS, *POLICIES]

# Schemas whose functions, triggers, views and policies are all declared here: anything else
# found in them is reported by autogenerate as something to drop.
SCHEMAS = ("public", "app", "chat", "chat_api", "privacy")
