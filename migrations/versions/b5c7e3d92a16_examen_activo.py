"""examen activo del usuario

Revision ID: b5c7e3d92a16
Revises: a8d4e2f71c90
Create Date: 2026-10-11 20:20:00.000000

Solo añade una columna que admite nulo (issue #8): sin examen activo, la
aplicación sigue trabajando sobre el primero sin archivar, como hasta ahora.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5c7e3d92a16'
down_revision = 'a8d4e2f71c90'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active_exam_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_users_active_exam', 'exams', ['active_exam_id'], ['id'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_active_exam', type_='foreignkey')
        batch_op.drop_column('active_exam_id')
