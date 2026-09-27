"""inventory-service database layer - async SQLAlchemy engine/session setup
plus the `products` table used for catalog and stock data.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer
from sqlalchemy.dialects.postgresql import JSONB

# Todos los servicios deben consumir la variable DATABASE_URL desde compose.yml
db_url = os.getenv("DATABASE_URL")

if not db_url:
    raise RuntimeError("DATABASE_URL environment variable is required")
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

class Product(Base):
    """Product catalog table; `quantity` is a dedicated column (for atomic
    reserve/release updates) while the remaining 24 fields live in `data` (JSONB)."""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    quantity = Column(Integer, nullable=False)
    data = Column(JSONB, nullable=False)

async def get_db():
    """FastAPI dependency yielding a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

