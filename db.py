from contextlib import contextmanager
from datetime import datetime
from typing import Generator

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import DB_NAME, DEFAULT_LIMIT

engine = create_engine(
    f"sqlite:///{DB_NAME}", connect_args={"check_same_thread": False}, future=True, echo=False
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(Integer, unique=True, nullable=True)
    full_name = Column(String)
    office = Column(String)
    role = Column(String, default="employee")
    balance = Column(Integer, default=0)
    auth_token = Column(String, nullable=True)

    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)

    menu_items = relationship("MenuItem", back_populates="restaurant", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="restaurant", cascade="all, delete-orphan")


class MenuItem(Base):
    __tablename__ = "menu"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"))
    name = Column(String)
    description = Column(String)
    price = Column(Integer)

    restaurant = relationship("Restaurant", back_populates="menu_items")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))
    order_date = Column(String)
    items_json = Column(String)
    total_price = Column(Integer)
    paid_extra = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="orders")
    restaurant = relationship("Restaurant", back_populates="orders")


class Config(Base):
    __tablename__ = "config"

    key = Column(String, primary_key=True)
    value = Column(String)


@contextmanager
def get_session() -> Generator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    with get_session() as session:
        existing_limit = session.get(Config, "daily_limit")
        if existing_limit is None:
            session.add(Config(key="daily_limit", value=str(DEFAULT_LIMIT)))
            session.commit()


def get_limit() -> int:
    with get_session() as session:
        cfg = session.get(Config, "daily_limit")
        return int(cfg.value) if cfg else DEFAULT_LIMIT


def set_limit(value: int) -> None:
    with get_session() as session:
        cfg = session.get(Config, "daily_limit")
        if cfg:
            cfg.value = str(value)
        else:
            session.add(Config(key="daily_limit", value=str(value)))
        session.commit()


def upsert_user(tg_id: int, full_name: str, role: str = "employee"):
    with get_session() as session:
        stmt = select(User).where(User.tg_id == tg_id)
        user = session.scalars(stmt).first()
        if user:
            user.full_name = full_name
            user.role = role
        else:
            session.add(User(tg_id=tg_id, full_name=full_name, role=role))
        session.commit()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
