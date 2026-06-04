import enum
import os

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


db_url = os.getenv(
    "DATABASE_URL",
    "postgresql://resilencia:resilencia_secret@postgres:5432/resilencia_db",
)
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(db_url, echo=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    processing = "processing"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    total_price = Column(Numeric(12, 2), nullable=False)
    status = Column(
        Enum(OrderStatus, name="order_status", native_enum=True, create_type=False),
        nullable=False,
        default=OrderStatus.pending,
        server_default=text("'pending'"),
    )
    internal_status = Column(String(50), nullable=False, default="awaiting_validation")
    priority = Column(String(20), nullable=False, default="normal")
    is_gift = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    gift_message = Column(Text)
    special_instructions = Column(Text)
    estimated_delivery_at = Column(DateTime(timezone=True))
    warehouse_dispatch_id = Column(UUID(as_uuid=True))
    carrier_service_level = Column(String(30), nullable=False, default="standard")
    return_policy_accepted = Column(Boolean, nullable=False, default=True, server_default=text("TRUE"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
