"""la cola de la tanda pasa de la cookie de sesión a study_sessions

Revision ID: a8d4e2f71c90
Revises: f3a91d6c0b58
Create Date: 2026-10-11 20:10:00.000000

Solo añade columnas que admiten nulo (issue #18): las sesiones anteriores
no tienen cola guardada y no la necesitan.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8d4e2f71c90'
down_revision = 'f3a91d6c0b58'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('queue', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('option_orders', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('recall_first', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.drop_column('recall_first')
        batch_op.drop_column('position')
        batch_op.drop_column('option_orders')
        batch_op.drop_column('queue')
