from contextlib import contextmanager
from sqlalchemy import text
from db_connection import engine
from models import Base


DEFAULT_SETTINGS = {
    "company_name": "FACENEX",
    "office_start": "09:30",
    "grace_minutes": "10",
    "threshold": "0.45",
    "min_gap_minutes": "10",
    "weekly_off": "Sunday",
    "liveness": "1",
    "backup_folder": "",
}


class CompatRow(dict):
    """Supports both row['column'] and row[0] access."""

    def __init__(self, mapping, values):
        super().__init__(mapping)
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class CompatResult:
    """Small compatibility wrapper around SQLAlchemy Result."""

    def __init__(self, result):
        self.result = result

    def _convert(self, row):
        if row is None:
            return None
        mapping = row._mapping
        return CompatRow(mapping, row)

    def fetchone(self):
        return self._convert(self.result.fetchone())

    def fetchall(self):
        return [self._convert(row) for row in self.result.fetchall()]

    def __iter__(self):
        for row in self.result:
            yield self._convert(row)


class CompatConnection:
    """Allows existing SQLite-style queries to run through SQLAlchemy."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=None):
        sql = sql.strip()

        if params is None:
            params = {}

        # Convert SQLite-style positional '?' placeholders
        # to SQLAlchemy named bind parameters.
        if isinstance(params, (tuple, list)):
            bind_params = {}
            index = 0

            def replace_placeholder(_match):
                nonlocal index
                name = f"p{index}"
                bind_params[name] = params[index]
                index += 1
                return f":{name}"

            import re

            sql = re.sub(r"\?", replace_placeholder, sql)
            params = bind_params

        result = self.connection.execute(text(sql), params)
        return CompatResult(result)


@contextmanager
def db():
    """Open a PostgreSQL transaction."""
    with engine.begin() as connection:
        yield CompatConnection(connection)


def init_db():
    """Create database tables and insert missing default settings."""
    Base.metadata.create_all(engine)

    with db() as con:
        for key, value in DEFAULT_SETTINGS.items():
            con.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT (key) DO NOTHING
                """,
                (key, value),
            )


def get_settings(con):
    settings = dict(DEFAULT_SETTINGS)

    rows = con.execute("SELECT key, value FROM settings").fetchall()

    settings.update({row["key"]: row["value"] for row in rows})

    return settings


def set_setting(con, key, value):
    con.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT (key)
        DO UPDATE SET value = EXCLUDED.value
        """,
        (key, str(value)),
    )
