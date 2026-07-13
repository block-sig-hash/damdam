from collections.abc import Callable, Generator

from sqlmodel import Session, create_engine

from app.config import Settings

SessionFactory = Callable[[], Session]


def create_session_factory(settings: Settings) -> SessionFactory:
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    def factory() -> Session:
        return Session(engine)

    return factory


def session_dependency(
    factory: SessionFactory,
) -> Callable[[], Generator[Session, None, None]]:
    def dependency() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    return dependency
