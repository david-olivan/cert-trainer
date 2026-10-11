"""señales de cada respuesta: confianza, pista y orden de opciones

Revision ID: 5b1e7c2a9d40
Revises: 084e931b95b3
Create Date: 2026-10-11 12:40:00.000000

Columnas nulas a propósito: los intentos anteriores no tienen estas
señales y no se rellenan con un valor inventado (issue #13).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b1e7c2a9d40'
down_revision = '084e931b95b3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confidence', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('hint_used', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('option_order', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.drop_column('option_order')
        batch_op.drop_column('hint_used')
        batch_op.drop_column('confidence')
