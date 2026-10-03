from sqlalchemy import text

from app.db.session import get_engine


def enable(engine):
    with engine.begin() as connection:
        if not connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name='vector')")):
            raise RuntimeError("pgvector is not installed on this PostgreSQL server. Use the documented pgvector Docker setup.")
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    print("pgvector enabled; SQL cosine-distance retrieval is available")


if __name__ == "__main__":
    enable(get_engine())
