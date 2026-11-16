from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database import Base

class UserModel(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class SessionModel(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)

class TaskModel(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[str] = mapped_column(String(5), default='media', nullable=False)
    # Nullable únicamente para conservar tareas de la versión anterior.
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
