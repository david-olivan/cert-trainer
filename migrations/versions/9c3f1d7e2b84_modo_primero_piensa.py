"""modo «primero piensa»: preferencia del usuario y datos por respuesta

Revision ID: 9c3f1d7e2b84
Revises: 5b1e7c2a9d40
Create Date: 2026-10-11 13:45:00.000000

La preferencia lleva server_default para que el usuario ya existente
quede con el modo apagado. Las columnas de Attempt admiten nulo: los
intentos anteriores no tienen el dato (issue #14).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c3f1d7e2b84'
down_revision = '5b1e7c2a9d40'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recall_first', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recall_first', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('seconds_to_reveal', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.drop_column('seconds_to_reveal')
        batch_op.drop_column('recall_first')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('recall_first')
