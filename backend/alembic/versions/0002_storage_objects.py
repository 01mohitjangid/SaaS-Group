"""storage_objects: artwork kept in Postgres instead of a bucket

Cloudflare R2 needs a payment card on file. The whole catalogue's artwork is about 5 MB,
which fits inside a free Postgres tier, so the storage abstraction grew a third backend
rather than the deployment growing a second account.

Deliberately not a mapped ORM model: storage sits below the domain, and a mapped class
would invite the rest of the app to read artwork bytes directly instead of going through
`ObjectStorage`.

Revision ID: 0002_storage_objects
Revises: 0001_initial_schema
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_storage_objects"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_objects",
        # The storage key is the natural primary key: it is what every reader has.
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_storage_objects")),
    )


def downgrade() -> None:
    op.drop_table("storage_objects")
