"""Alembic 환경.

스키마 기준선은 docker/db/init/02_schema.sql(DB 최초 생성 시 실행)이고, 이후 변경은 이 디렉터리의 리비전으로만 한다.
autogenerate는 추가·변경만 만든다: 모델에 없는 테이블·컬럼·인덱스(Airflow 전용 테이블, pgvector 인덱스,
AGE 스키마 등)는 비교에서 빼서 삭제를 제안하지 않는다. 삭제가 필요하면 리비전에 직접 쓴다.
"""
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401 — 모델을 Base.metadata에 등록
from app.database import Base, engine

if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # DB에만 있고 모델에 없는 객체는 비교하지 않는다 (삭제 제안 방지)
    if reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
