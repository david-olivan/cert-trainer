"""cupo diario de preguntas nuevas por examen, para «Repaso de hoy»

Revision ID: f3a91d6c0b58
Revises: e7b2c9a14f63
Create Date: 2026-10-11 20:00:00.000000

Solo añade una columna con valor por defecto (issue #17).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a91d6c0b58'
down_revision = 'e7b2c9a14f63'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('new_per_day', sa.Integer(), nullable=False, server_default='10'))


def downgrade():
    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.drop_column('new_per_day')
