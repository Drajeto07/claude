"""template persistence and workspace default template

Templates become real workspace-owned rows (корекции.docx §18): the style system,
the rules it compiled to, a version counter, visibility and the document they
came from. Built-ins stay in code, so `is_builtin` and a NULL workspace go away.
Documents lose their unused `template_id` column (the applied template is
data["templateId"]); workspaces gain a default template.

Assumes `templates` is empty, as it is everywhere: until now custom templates
lived in JSON files, never in this table. The NOT NULL columns below make the
upgrade fail loudly rather than invent values if that ever isn't true.

Revision ID: 74e891504d93
Revises: e68923f36278
Create Date: 2026-09-24 18:38:57.593647

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '74e891504d93'
down_revision: Union[str, Sequence[str], None] = 'e68923f36278'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql')


# batch_alter_table: plain ALTER TABLE on Postgres; on SQLite (the migration
# tests) it rebuilds the table, since SQLite can't drop constraints in place.
def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('documents') as batch:
        batch.drop_index('ix_documents_template_id')
        batch.drop_constraint('fk_documents_template_id_templates', type_='foreignkey')
        batch.drop_column('template_id')

    with op.batch_alter_table('template_versions') as batch:
        batch.add_column(sa.Column('created_by', sa.String(length=36), nullable=True))
        batch.create_index('ix_template_versions_created_by', ['created_by'], unique=False)
        batch.create_foreign_key(
            'fk_template_versions_created_by_users', 'users', ['created_by'], ['id'], ondelete='SET NULL'
        )

    with op.batch_alter_table('templates') as batch:
        batch.add_column(sa.Column('source_document_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('visibility', sa.String(length=20), server_default='workspace', nullable=False))
        batch.add_column(sa.Column('style_system', _JSON, nullable=False))
        batch.add_column(sa.Column('rules', _JSON, nullable=False))
        batch.add_column(sa.Column('version', sa.Integer(), server_default='1', nullable=False))
        batch.alter_column('workspace_id', existing_type=sa.VARCHAR(length=36), nullable=False)
        batch.create_index('ix_templates_source_document_id', ['source_document_id'], unique=False)
        batch.create_foreign_key(
            'fk_templates_source_document_id_documents', 'documents', ['source_document_id'], ['id'], ondelete='SET NULL'
        )
        batch.drop_column('is_builtin')

    op.add_column('workspaces', sa.Column('default_template_id', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workspaces', 'default_template_id')

    with op.batch_alter_table('templates') as batch:
        batch.add_column(sa.Column('is_builtin', sa.BOOLEAN(), server_default=sa.false(), nullable=False))
        batch.drop_constraint('fk_templates_source_document_id_documents', type_='foreignkey')
        batch.drop_index('ix_templates_source_document_id')
        batch.alter_column('workspace_id', existing_type=sa.VARCHAR(length=36), nullable=True)
        batch.drop_column('version')
        batch.drop_column('rules')
        batch.drop_column('style_system')
        batch.drop_column('visibility')
        batch.drop_column('source_document_id')

    with op.batch_alter_table('template_versions') as batch:
        batch.drop_constraint('fk_template_versions_created_by_users', type_='foreignkey')
        batch.drop_index('ix_template_versions_created_by')
        batch.drop_column('created_by')

    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('template_id', sa.VARCHAR(length=36), nullable=True))
        batch.create_foreign_key(
            'fk_documents_template_id_templates', 'templates', ['template_id'], ['id'], ondelete='SET NULL'
        )
        batch.create_index('ix_documents_template_id', ['template_id'], unique=False)
