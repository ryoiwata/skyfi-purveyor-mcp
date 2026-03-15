"""add order_payload_json to order_confirmations

Revision ID: b1c2d3e4f5a6
Revises: a96bf3d3af8d
Create Date: 2026-03-15 00:00:00.000000

Moves order params out of the Fernet URL token and into the DB so the token
only carries the API key.  This reduces the base32 URL token from ~960 chars
to ~194 chars, preventing LLM truncation of confirmation links.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a96bf3d3af8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_confirmations",
        sa.Column(
            "order_payload_json",
            sa.Text(),
            nullable=True,
            comment=(
                "JSON blob with order_params and webhook_url; not security-sensitive. "
                "NULL on records created before this migration (those store params in token)."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("order_confirmations", "order_payload_json")
