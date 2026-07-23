"""add_branches_table

Revision ID: e37a4c5483af
Revises: 5d599c1583ad
Create Date: 2026-07-23 09:38:47.512122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e37a4c5483af'
down_revision: Union[str, None] = '5d599c1583ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'branches',
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('phone_number', sa.String(length=30), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        if_not_exists=True
    )
    op.create_index(op.f('ix_branches_code'), 'branches', ['code'], unique=True, if_not_exists=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_branches_code'), table_name='branches', if_exists=True)
    op.drop_table('branches', if_exists=True)
