"""Initial database schema for LLM-MUD Web.

Revision ID: 001_initial_schema
Revises: None
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial database tables."""
    # Accounts table
    op.create_table(
        'accounts',
        sa.Column('account_id', sa.Text(), primary_key=True),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1')),
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('0')),
        sa.Column('settings', sa.Text(), server_default="'{}'"),
        sa.UniqueConstraint('email', name='uq_accounts_email'),
    )

    # Create index for email lookups
    op.create_index('idx_accounts_email', 'accounts', ['email'])

    # Characters table
    op.create_table(
        'characters',
        sa.Column('character_id', sa.Text(), primary_key=True),
        sa.Column('account_id', sa.Text(), sa.ForeignKey('accounts.account_id'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('race_id', sa.Text(), nullable=False),
        sa.Column('class_id', sa.Text(), nullable=False),
        sa.Column('level', sa.Integer(), server_default='1'),
        sa.Column('experience', sa.Integer(), server_default='0'),
        sa.Column('gold', sa.Integer(), server_default='0'),
        sa.Column('stats', sa.Text(), server_default="'{}'"),
        sa.Column('inventory', sa.Text(), server_default="'[]'"),
        sa.Column('equipment', sa.Text(), server_default="'{}'"),
        sa.Column('location_id', sa.Text(), server_default="'ravenmoor_square'"),
        sa.Column('quest_log', sa.Text(), server_default="'{}'"),
        sa.Column('preferences', sa.Text(), server_default="'{}'"),
        sa.Column('skills', sa.Text(), server_default="'{}'"),
        sa.Column('cooldowns', sa.Text(), server_default="'{}'"),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
        sa.Column('last_played', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1')),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('0')),
        sa.UniqueConstraint('name', name='uq_characters_name'),
    )

    # Create indexes for characters
    op.create_index('idx_characters_account', 'characters', ['account_id'])
    op.create_index('idx_characters_name', 'characters', ['name'])

    # Online characters table (session tracking)
    op.create_table(
        'online_characters',
        sa.Column('character_id', sa.Text(), sa.ForeignKey('characters.character_id'), primary_key=True),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('connected_at', sa.DateTime(), server_default=sa.func.current_timestamp()),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('online_characters')
    op.drop_index('idx_characters_name', table_name='characters')
    op.drop_index('idx_characters_account', table_name='characters')
    op.drop_table('characters')
    op.drop_index('idx_accounts_email', table_name='accounts')
    op.drop_table('accounts')
