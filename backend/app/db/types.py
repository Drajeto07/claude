from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on Postgres (indexable, binary-stored), plain JSON on every other
# dialect -- lets the same model run against SQLite in tests and Postgres in
# production without two separate column definitions.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")
