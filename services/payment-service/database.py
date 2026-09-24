import os

from sqlalchemy import Column, DateTime, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


db_url = os.getenv("DATABASE_URL")

if not db_url:
    raise RuntimeError("DATABASE_URL environment variable is required")
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(db_url, echo=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


class PaymentRecord(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    order_total = Column(Numeric(12, 2), nullable=False)
    subtotal = Column(Numeric(12, 2), nullable=False)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0.00, server_default=text("0.00"))
    shipping_cost = Column(Numeric(12, 2), nullable=False, default=0.00, server_default=text("0.00"))
    currency = Column(String(5), nullable=False, default="MXN", server_default=text("'MXN'"))
    method = Column(String(30), nullable=False, default="credit_card", server_default=text("'credit_card'"))
    provider = Column(String(100))
    card_last_four = Column(String(4))
    card_expiry = Column(String(7))
    card_network = Column(String(30))
    billing_address = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    coupon_code = Column(String(20))
    installment_count = Column(Integer, nullable=False, default=1, server_default=text("1"))
    status = Column(String(30), nullable=False, default="pending", server_default=text("'pending'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
