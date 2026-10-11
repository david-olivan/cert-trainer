"""repetición espaciada con FSRS: estado por pregunta y parámetros por examen

Revision ID: e7b2c9a14f63
Revises: c41a8e0f5d27
Create Date: 2026-10-11 19:40:00.000000

Solo crea tablas y columnas (issue #16). Los estados no se calculan aquí:
`flask fsrs rebuild`, que docker-start.sh lanza en cada arranque, los
reconstruye a partir del historial de respuestas.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b2c9a14f63'
down_revision = 'c41a8e0f5d27'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'review_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.Integer(), nullable=False),
        sa.Column('step', sa.Integer(), nullable=True),
        sa.Column('stability', sa.Float(), nullable=True),
        sa.Column('difficulty', sa.Float(), nullable=True),
        sa.Column('due', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_review', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id'], name='fk_review_states_question'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id'),
    )
    with op.batch_alter_table('review_states', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_review_states_due'), ['due'], unique=False)

    op.create_table(
        'fsrs_parameters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('exam_id', sa.Integer(), nullable=False),
        sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('rating_config', sa.JSON(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('review_count', sa.Integer(), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], name='fk_fsrs_parameters_exam'),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('predicted_r', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.drop_column('predicted_r')
        batch_op.drop_column('rating')

    op.drop_table('fsrs_parameters')
    with op.batch_alter_table('review_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_review_states_due'))
    op.drop_table('review_states')
