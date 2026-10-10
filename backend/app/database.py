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
            _engine = _create_server_engine(url)
    return _engine


def _create_server_engine(url: str):
    # neon suspends the database after a few idle minutes and drops every
    # open connection, so a pooled connection from before the suspend fails
    # with "SSL connection has been closed unexpectedly" on its next use,
    # pre ping swaps a dead connection for a fresh one before handing it out
    return create_engine(url, echo=False, pool_pre_ping=True)


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
