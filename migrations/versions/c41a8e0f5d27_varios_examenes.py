"""varios exámenes: Exam, Domain, Skill y QuestionFormat

Revision ID: c41a8e0f5d27
Revises: 9c3f1d7e2b84
Create Date: 2026-10-11 18:00:00.000000

Transforma datos (issue #7): crea AIB-C01 con los dominios, pesos y
formatos que hasta ahora vivían en app/sampling.py y en el validador, y
reasigna a él todas las preguntas y sesiones existentes. Antes de
desplegarla en producción, lanzar a mano el workflow «Copia del banco».

Los datos de AIB-C01 van escritos aquí a propósito: es la migración que lo
siembra, y a partir de ella el único punto de verdad es la base de datos.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c41a8e0f5d27'
down_revision = '9c3f1d7e2b84'
branch_labels = None
depends_on = None


AIB_C01 = {
    "code": "AIB-C01",
    "name": "AWS Certified AI Business Strategist",
    "duration_minutes": 130,  # la guía; la página del beta dice 170
    "minutes_per_question": 2,
    "pass_threshold_pct": 72,
    "desired_retention": 0.9,
}

AIB_C01_DOMAINS = [
    (1, "Conceptos básicos y alfabetización en IA", "Fundamentos", 24),
    (2, "Estrategia de IA y creación de valor empresarial", "Estrategia", 28),
    (3, "Gobernanza de la IA y liderazgo responsable", "Gobernanza", 24),
    (4, "Preparación empresarial, liderazgo y transformación", "Transformación", 24),
]

# Una de cada seis preguntas del examen es de respuesta múltiple.
AIB_C01_FORMATS = [
    (4, 1, round(5 / 6, 4)),
    (5, 2, round(1 / 6, 4)),
]


def upgrade():
    op.create_table(
        'exams',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('exam_date', sa.Date(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('minutes_per_question', sa.Integer(), nullable=False),
        sa.Column('pass_threshold_pct', sa.Integer(), nullable=False),
        sa.Column('desired_retention', sa.Float(), nullable=False),
        sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_exams_code'),
    )
    op.create_table(
        'domains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('exam_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('short_name', sa.String(length=40), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], name='fk_domains_exam'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('exam_id', 'number', name='uq_domains_exam_number'),
    )
    op.create_table(
        'skills',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], name='fk_skills_domain'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('domain_id', 'code', name='uq_skills_domain_code'),
    )
    op.create_table(
        'question_formats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('exam_id', sa.Integer(), nullable=False),
        sa.Column('option_count', sa.Integer(), nullable=False),
        sa.Column('correct_count', sa.Integer(), nullable=False),
        sa.Column('target_share', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], name='fk_question_formats_exam'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('exam_id', 'option_count', 'correct_count', name='uq_question_formats_exam_shape'),
    )

    bind = op.get_bind()
    exams = sa.table(
        'exams',
        sa.column('code', sa.String), sa.column('name', sa.String),
        sa.column('duration_minutes', sa.Integer), sa.column('minutes_per_question', sa.Integer),
        sa.column('pass_threshold_pct', sa.Integer), sa.column('desired_retention', sa.Float),
        sa.column('archived', sa.Boolean), sa.column('created_at', sa.DateTime(timezone=True)),
    )
    bind.execute(exams.insert().values(**AIB_C01, archived=False, created_at=sa.func.now()))
    exam_id = bind.execute(sa.text("SELECT id FROM exams WHERE code = :code"), {"code": AIB_C01["code"]}).scalar_one()

    domains = sa.table(
        'domains',
        sa.column('exam_id', sa.Integer), sa.column('number', sa.Integer), sa.column('name', sa.String),
        sa.column('short_name', sa.String), sa.column('weight', sa.Integer),
    )
    bind.execute(domains.insert(), [
        {"exam_id": exam_id, "number": n, "name": name, "short_name": short, "weight": w}
        for n, name, short, w in AIB_C01_DOMAINS
    ])
    formats = sa.table(
        'question_formats',
        sa.column('exam_id', sa.Integer), sa.column('option_count', sa.Integer),
        sa.column('correct_count', sa.Integer), sa.column('target_share', sa.Float),
    )
    bind.execute(formats.insert(), [
        {"exam_id": exam_id, "option_count": o, "correct_count": c, "target_share": share}
        for o, c, share in AIB_C01_FORMATS
    ])

    # Preguntas: primero las columnas nuevas admitiendo nulo, se rellenan y
    # después se cierran. El dominio se resuelve por su número.
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('exam_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('domain_id', sa.Integer(), nullable=True))

    bind.execute(sa.text("UPDATE questions SET exam_id = :exam_id"), {"exam_id": exam_id})
    bind.execute(sa.text(
        "UPDATE questions SET domain_id = ("
        " SELECT d.id FROM domains d WHERE d.exam_id = :exam_id AND d.number = questions.domain"
        ")"
    ), {"exam_id": exam_id})
    orphans = bind.execute(sa.text("SELECT ext_id FROM questions WHERE domain_id IS NULL")).scalars().all()
    if orphans:
        raise RuntimeError(
            "Hay preguntas con un dominio que AIB-C01 no tiene, así que no se pueden reasignar: "
            f"{', '.join(orphans)}. Corrige su campo 'domain' (1 a 4) y vuelve a lanzar la migración."
        )

    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.alter_column('exam_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('domain_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_questions_exam', 'exams', ['exam_id'], ['id'])
        batch_op.create_foreign_key('fk_questions_domain', 'domains', ['domain_id'], ['id'])
        batch_op.create_index(batch_op.f('ix_questions_exam_id'), ['exam_id'], unique=False)
        # ext_id deja de ser único en todo el banco: lo es dentro de cada examen.
        batch_op.drop_index(batch_op.f('ix_questions_ext_id'))
        batch_op.create_index(batch_op.f('ix_questions_ext_id'), ['ext_id'], unique=False)
        batch_op.create_unique_constraint('uq_questions_exam_ext_id', ['exam_id', 'ext_id'])
        batch_op.drop_column('domain')

    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('exam_id', sa.Integer(), nullable=True))
    bind.execute(sa.text("UPDATE study_sessions SET exam_id = :exam_id"), {"exam_id": exam_id})
    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.alter_column('exam_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_study_sessions_exam', 'exams', ['exam_id'], ['id'])


def downgrade():
    """Vuelve al esquema de un solo examen.

    Solo es posible mientras los ext_id no se repitan entre exámenes: si
    se repiten, el índice único global falla y la migración se detiene sin
    perder nada.
    """
    bind = op.get_bind()

    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_study_sessions_exam', type_='foreignkey')
        batch_op.drop_column('exam_id')

    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('domain', sa.Integer(), nullable=True))
    bind.execute(sa.text(
        "UPDATE questions SET domain = (SELECT d.number FROM domains d WHERE d.id = questions.domain_id)"
    ))
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.alter_column('domain', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint('uq_questions_exam_ext_id', type_='unique')
        batch_op.drop_index(batch_op.f('ix_questions_ext_id'))
        batch_op.create_index(batch_op.f('ix_questions_ext_id'), ['ext_id'], unique=True)
        batch_op.drop_index(batch_op.f('ix_questions_exam_id'))
        batch_op.drop_constraint('fk_questions_domain', type_='foreignkey')
        batch_op.drop_constraint('fk_questions_exam', type_='foreignkey')
        batch_op.drop_column('domain_id')
        batch_op.drop_column('exam_id')

    op.drop_table('question_formats')
    op.drop_table('skills')
    op.drop_table('domains')
    op.drop_table('exams')
