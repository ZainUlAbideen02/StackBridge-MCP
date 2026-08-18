from typing import Generator

from sqlalchemy import Column, Float, ForeignKey, String
from sqlalchemy.orm import Session, declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)

    billing_account = relationship("BillingAccount", back_populates="user", uselist=False)


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    plan = Column(String, nullable=False, default="free")
    balance = Column(Float, nullable=False, default=0.0)

    user = relationship("User", back_populates="billing_account")


def get_db() -> Generator[Session, None, None]:
    # Placeholder session generator for FastAPI Depends
    pass
