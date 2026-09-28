from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import create_engine, pool

from app.config.settings import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS owns spatial_ref_sys & co; never touch them
    if type_ == "table" and name in {"spatial_ref_sys", "topology", "layer"}:
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      include_object=include_object,
                      process_revision_directives=alembic_helpers.writer,
                      render_item=alembic_helpers.render_item)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          include_object=include_object,
                          process_revision_directives=alembic_helpers.writer,
                          render_item=alembic_helpers.render_item)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
