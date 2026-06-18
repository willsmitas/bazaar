from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.debug,       # logs every SQL statement when DEBUG=true
    pool_pre_ping=True,        # drops stale connections (essential for cloud)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass
