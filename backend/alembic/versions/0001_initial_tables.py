"""initial tables

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	op.create_table(
		'supported_currencies',
		sa.Column('code', sa.String(5), primary_key=True),
		sa.Column('name', sa.String(100), nullable=True),
	)

	op.create_table(
		'rate_history',
		sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
		sa.Column('from_currency', sa.String(5), nullable=False),
		sa.Column('to_currency', sa.String(5), nullable=False),
		sa.Column('rate', sa.DECIMAL(precision=18, scale=6), nullable=False),
		sa.Column('timestamp', sa.DateTime, nullable=False),
		sa.Column('source', sa.String(50), nullable=False),
		sa.UniqueConstraint(
			'from_currency', 'to_currency', 'timestamp', name='uq_base_target_currency'
		),
	)

	op.create_index('idx_from_currency', 'rate_history', ['from_currency'])
	op.create_index('idx_to_currency', 'rate_history', ['to_currency'])
	op.create_index('idx_timestamp', 'rate_history', ['timestamp'])


def downgrade() -> None:
	op.drop_index('idx_timestamp', table_name='rate_history')
	op.drop_index('idx_to_currency', table_name='rate_history')
	op.drop_index('idx_from_currency', table_name='rate_history')
	op.drop_table('rate_history')
	op.drop_table('supported_currencies')
