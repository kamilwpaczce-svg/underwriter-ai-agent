"""wejscia_modelu

Etap 15 (SPEC decyzja 8): tabela wejsc modelu ryzyka szkody. Migracja pisana recznie
(autogenerate nie jest potrzebny - jedna nowa tabela, bez zmian w istniejacych).

Revision ID: b7e3c1a95d24
Revises: 896d4c7be956
Create Date: 2026-10-26 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7e3c1a95d24'
down_revision: Union[str, Sequence[str], None] = '896d4c7be956'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('wejscia_modelu',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('wniosek_id', sa.Uuid(), nullable=True),
    sa.Column('wersja_modelu', sa.String(), nullable=False),
    sa.Column('cechy', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('wynik', sa.Float(), nullable=False),
    sa.Column('zrodlo', sa.String(), nullable=False),
    sa.Column('utworzono', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint("zrodlo IN ('api', 'symulacja')", name='ck_wejscia_modelu_zrodlo'),
    sa.ForeignKeyConstraint(['wniosek_id'], ['wnioski.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('wejscia_modelu')
