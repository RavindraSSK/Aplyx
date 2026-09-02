"""Copy all jobagent data from the local SQLite DB into a Postgres database.

Usage (from the repo root, venv active):
    python scripts/migrate_sqlite_to_postgres.py "postgresql+psycopg2://user:pass@host/db?sslmode=require"

Optional second arg = source URL (default: sqlite:///./jobagent.db).
Creates tables in the target if missing, preserves row ids, and refuses to run
if the target already contains jobs (so it can't duplicate data).
"""
import sys

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, ".")
from app.db.models import Application, Base, Job, TailoredResume  # noqa: E402

# Insert order respects foreign keys: applications reference jobs + tailored_resumes.
TABLES = [Job, TailoredResume, Application]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    target_url = sys.argv[1]
    source_url = sys.argv[2] if len(sys.argv) > 2 else "sqlite:///./jobagent.db"

    source = sessionmaker(bind=create_engine(source_url))()
    target_engine = create_engine(target_url)
    Base.metadata.create_all(target_engine)
    target = sessionmaker(bind=target_engine)()

    if target.scalar(select(func.count(Job.id))):
        print("Target already has jobs - refusing to migrate on top. "
              "Empty the target DB first if you really want a re-run.")
        return 1

    for model in TABLES:
        rows = source.execute(select(model)).scalars().all()
        for row in rows:
            data = {c.name: getattr(row, c.name) for c in model.__table__.columns}
            target.execute(model.__table__.insert().values(**data))
        print(f"{model.__tablename__}: copied {len(rows)} row(s)")

    target.commit()

    # Explicit-id inserts don't advance Postgres sequences; fix them.
    if target_engine.dialect.name == "postgresql":
        with target_engine.connect() as conn:
            for model in TABLES:
                t = model.__tablename__
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)"
                ))
            conn.commit()
        print("Postgres id sequences reset.")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
