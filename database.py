"""Conexión y actualización aditiva de la base SQLite original."""
import os
from pathlib import Path
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DB_PATH = Path(__file__).resolve().with_name('test.db')
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite+aiosqlite:///{DB_PATH.as_posix()}')
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

@event.listens_for(engine.sync_engine, 'connect')
def enable_foreign_keys(connection, _):
    cursor = connection.cursor()
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()

async def init_db():
    import models  # Registra las tablas antes de create_all.
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        user_columns = {row[1] for row in (await connection.execute(text('PRAGMA table_info(users)')))}
        if 'is_active' not in user_columns:
            await connection.execute(text('ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1'))
        # Impide altas duplicadas incluso con distinta capitalización o solicitudes simultáneas.
        await connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_lower ON users (lower(username))'))
        columns = {row[1] for row in (await connection.execute(text('PRAGMA table_info(tasks)')))}
        # create_all no agrega columnas a una tabla que ya existe.
        if 'priority' not in columns:
            await connection.execute(text("ALTER TABLE tasks ADD COLUMN priority VARCHAR(5) NOT NULL DEFAULT 'media'"))
        if 'owner_id' not in columns:
            await connection.execute(text('ALTER TABLE tasks ADD COLUMN owner_id INTEGER REFERENCES users(id)'))
        await connection.execute(text('CREATE INDEX IF NOT EXISTS ix_tasks_owner_id ON tasks (owner_id)'))

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
