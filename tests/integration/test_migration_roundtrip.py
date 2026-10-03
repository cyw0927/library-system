import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import CreateSchema

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
TABLES = {"books", "volumes", "chapters", "paragraphs", "sync_state", "alembic_version"}


def test_upgrade_downgrade_upgrade_in_isolated_schema():
    engine = create_engine(DATABASE_URL)
    schema = "migration_test_" + uuid4().hex
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(CreateSchema(schema))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                assert set(inspect(connection).get_table_names(schema=schema)) == TABLES
                command.downgrade(config, "base")
                assert set(inspect(connection).get_table_names(schema=schema)) == {"alembic_version"}
                command.upgrade(config, "head")
                assert set(inspect(connection).get_table_names(schema=schema)) == TABLES
            finally:
                transaction.rollback()
        # The temporary schema itself is rolled back; no existing data is dropped.
        assert schema not in inspect(engine).get_schema_names()
    finally:
        engine.dispose()
