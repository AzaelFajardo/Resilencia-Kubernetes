import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer
from sqlalchemy.dialects.postgresql import JSONB

# Todos los servicios deben consumir la variable DATABASE_URL desde compose.yml
db_url = os.getenv("DATABASE_URL", "postgresql://resilencia:resilencia_secret@postgres:5432/resilencia_db")
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Creación del motor con create_async_engine
engine = create_async_engine(db_url, echo=True)

# Manejo de sesiones asíncronas
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    data = Column(JSONB, nullable=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

