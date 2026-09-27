from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def _normalize_database_url(url: str) -> str:
    # managed postgres providers (eg render) hand out bare "postgres://" or
    # "postgresql://" connection strings, sqlalchemy's default driver for
    # both is psycopg2, which this project doesn't install, only psycopg
    # (v3), via the "postgresql+psycopg://" dialect, without this rewrite,
    # create_engine() raises ModuleNotFoundError no module named 'psycopg2'
    # the first time the app touches the database
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def get_engine():
    global _engine
    if _engine is None:
        url = _normalize_database_url(get_settings().database_url)
        connect_args = {}
        # in memory sqlite (used by the test suite) needs a shared connection
        # pool, or each new connection would see an empty, separate database
        if url.startswith("sqlite") and ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            connect_args = {"check_same_thread": False}
            _engine = create_engine(url, connect_args=connect_args, poolclass=StaticPool)
        else:
            _engine = create_engine(url, echo=False)
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
