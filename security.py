"""Contraseñas con PBKDF2; sesiones revocables con tokens aleatorios."""
import hashlib
import hmac
import secrets
import time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import SessionModel, UserModel

SESSION_SECONDS = 12 * 60 * 60
ITERATIONS = 600_000
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'

def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def unauthorized():
    return HTTPException(401, 'La sesión venció o no es válida. Iniciá sesión nuevamente.', headers={'WWW-Authenticate': 'Bearer'})

async def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> SessionModel:
    if credentials is None or credentials.scheme.lower() != 'bearer':
        raise unauthorized()
    session = await db.get(SessionModel, token_hash(credentials.credentials))
    if session is None or session.expires_at <= int(time.time()):
        raise unauthorized()
    return session

async def get_current_user(
    session: SessionModel = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    user = await db.get(UserModel, session.user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user
