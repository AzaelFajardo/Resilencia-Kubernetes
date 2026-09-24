import os

from sqlalchemy import Boolean, Column, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
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


class NotificationRecord(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    enable_email = Column(Boolean, nullable=False, default=True, server_default=text("TRUE"))
    enable_sms = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    enable_push = Column(Boolean, nullable=False, default=True, server_default=text("TRUE"))
    preferred_channel = Column(String(20), nullable=False, default="email", server_default=text("'email'"))
    marketing_opt_in = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    template_id = Column(String(20))
    tracking_pixel_id = Column(UUID(as_uuid=True))
    campaign_id = Column(String(20))
    referral_code = Column(String(20))
    link_shortener_key = Column(String(20))
    status = Column(String(30), nullable=False, default="pending", server_default=text("'pending'"))
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
