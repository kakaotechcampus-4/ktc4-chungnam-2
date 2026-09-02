"""
Alembic 히스토리는 저장소 전체에 하나(backend/CLAUDE.md 참고). 모듈마다 별도 체인을 만들지 않는다.
각 모듈이 models.py를 추가하면, 아래에 import를 추가해야 Alembic이 그 테이블을 인식한다
(SQLAlchemy는 import된 모델만 Base.metadata에 등록한다).
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from common.database import Base  # noqa: E402

# 모듈이 models.py를 만들면 여기 추가한다. 예:
# import auth.models  # noqa: F401
# import maps.models  # noqa: F401
# import pins.models  # noqa: F401
# import places.models  # noqa: F401
# import recommend.models  # noqa: F401
# import shortlist.models  # noqa: F401
# import realtime.models  # noqa: F401
# import seeding.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo"),
)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
