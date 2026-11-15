"""shortlist

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12 23:10:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shortlist_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("value_at_add_eur", sa.BigInteger(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name=op.f("fk_shortlist_entry_user_id_app_user"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], name=op.f("fk_shortlist_entry_player_id_player"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shortlist_entry")),
        sa.UniqueConstraint("user_id", "player_id", name="uq_shortlist_user_player"),
    )
    op.create_index(op.f("ix_shortlist_entry_user_id"), "shortlist_entry", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shortlist_entry_user_id"), table_name="shortlist_entry")
    op.drop_table("shortlist_entry")
