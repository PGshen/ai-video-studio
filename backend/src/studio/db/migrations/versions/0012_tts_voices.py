"""新增 `tts_voices` 表：设置页可增删的 TTS 音色（计划 tts-voice-management）。

音色原来是 `engines/tts/voice_map.py` 里的静态映射；这里写入同样的 6 个种子（含豆包 v1 的
`sisi`）。种子只在迁移里写一次——用户删掉的音色不会在重启后复活。中文名与性别取自旧项目
`tts_voices` 表（2026-09-30 只读查证）。

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# (alias, label, gender, speaker_id, engine)——顺序即列表顺序。
_SEED = [
    ("sisi", "思思", "female", "zh_female_shuangkuaisisi_moon_bigtts", "doubao_1.0"),
    ("xiaozhupeiqi", "小猪佩奇", "female", "zh_female_peiqi_uranus_bigtts", "doubao_2.0"),
    ("xiaoxinjiejie", "小新小姐姐", "female", "zh_female_chunribu_uranus_bigtts", "doubao_2.0"),
    ("zizi", "清澈梓梓", "female", "zh_female_qingchezizi_uranus_bigtts", "doubao_2.0"),
    ("yunzhou", "云舟", "male", "zh_male_m191_uranus_bigtts", "doubao_2.0"),
    ("xiaohe", "小禾", "female", "zh_female_xiaohe_uranus_bigtts", "doubao_2.0"),
]


def upgrade() -> None:
    table = op.create_table(
        "tts_voices",
        sa.Column("alias", sa.String(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("gender", sa.String(), nullable=False),
        sa.Column("speaker_id", sa.String(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    start = datetime.now(UTC)
    op.bulk_insert(
        table,
        [
            {
                "alias": alias,
                "label": label,
                "gender": gender,
                "speaker_id": speaker_id,
                "engine": engine,
                "created_at": start + timedelta(microseconds=i),
            }
            for i, (alias, label, gender, speaker_id, engine) in enumerate(_SEED)
        ],
    )


def downgrade() -> None:
    op.drop_table("tts_voices")
