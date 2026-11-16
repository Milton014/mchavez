import os
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from database import engine, get_db, init_db
from models import SessionModel, TaskModel, UserModel
from schemas import ChangePasswordRequest, LoginRequest, LoginResponse, RegisterRequest, TaskCreate, TaskResponse, TaskStatusUpdate, UserResponse
from security import SESSION_SECONDS, get_current_session, get_current_user, hash_password, token_hash, verify_password

DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()

app = FastAPI(title='Gestión de tareas - app-mchavez', version='2.1.0', lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv('CORS_ORIGINS', 'http://localhost:8081,http://127.0.0.1:8081').split(',') if origin.strip()],
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
)

@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc: RequestValidationError):
    # No devolver valores ingresados: pueden contener contraseñas.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(error['loc']), 'msg': error['msg'], 'type': error['type']}
        for error in exc.errors()
    ]})

@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'app-mchavez'}

@app.post('/auth/login', response_model=LoginResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(UserModel).where(func.lower(UserModel.username) == data.username.lower()))
    valid = await run_in_threadpool(verify_password, data.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if user is None or not valid or not user.is_active:
        raise HTTPException(401, 'Usuario o contraseña incorrectos.', headers={'WWW-Authenticate': 'Bearer'})
    # Retirar el acceso de prueba únicamente después de validar una cuenta personal.
    # No se borran usuarios ni tareas: owner_id conserva quién creó cada registro.
    if user.username.lower() != 'demo':
        demo = await db.scalar(select(UserModel).where(func.lower(UserModel.username) == 'demo'))
        if demo is not None and demo.is_active:
            demo.is_active = False
            await db.execute(delete(SessionModel).where(SessionModel.user_id == demo.id))
    now = int(time.time())
    await db.execute(delete(SessionModel).where(SessionModel.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(SessionModel(token_hash=token_hash(token), user_id=user.id, expires_at=now + SESSION_SECONDS))
    await db.commit()
    return LoginResponse(access_token=token, expires_in=SESSION_SECONDS, user=UserResponse.model_validate(user))

@app.post('/auth/register', response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(UserModel.id).where(func.lower(UserModel.username) == data.username))
    if existing is not None:
        raise HTTPException(409, 'Ese usuario ya está registrado. Elegí otro.')
    user = UserModel(username=data.username, name=data.name,
                     password_hash=await run_in_threadpool(hash_password, data.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'Ese usuario ya está registrado. Elegí otro.') from None
    await db.refresh(user)
    return user

@app.post('/auth/change-password', status_code=204)
async def change_password(data: ChangePasswordRequest, user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await run_in_threadpool(verify_password, data.current_password, user.password_hash):
        # Un error de contraseña actual no significa que el token haya vencido.
        raise HTTPException(400, 'La contraseña actual es incorrecta.')
    user.password_hash = await run_in_threadpool(hash_password, data.new_password)
    await db.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
    await db.commit()
    return Response(status_code=204)

@app.get('/auth/me', response_model=UserResponse)
async def me(user: UserModel = Depends(get_current_user)):
    return user

@app.post('/auth/logout', status_code=204)
async def logout(session: SessionModel = Depends(get_current_session), db: AsyncSession = Depends(get_db)):
    await db.delete(session)
    await db.commit()
    return Response(status_code=204)

async def shared_task(task_id: int, db: AsyncSession) -> TaskModel:
    task = await db.get(TaskModel, task_id)
    if task is None:
        raise HTTPException(404, 'Tarea no encontrada.')
    return task

@app.post('/tasks/', response_model=TaskResponse, status_code=201)
async def create_task(task: TaskCreate, user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record = TaskModel(**task.model_dump(), owner_id=user.id)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record

@app.get('/tasks/', response_model=list[TaskResponse])
async def read_tasks(
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
    user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    records = await db.scalars(select(TaskModel).order_by(TaskModel.id.desc()).offset(skip).limit(limit))
    return list(records)

@app.get('/tasks/{task_id}', response_model=TaskResponse)
async def read_task(task_id: int, user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await shared_task(task_id, db)

@app.put('/tasks/{task_id}', response_model=TaskResponse)
async def update_task(task_id: int, data: TaskCreate, user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await shared_task(task_id, db)
    for field, value in data.model_dump().items():
        setattr(task, field, value)
    await db.commit()
    await db.refresh(task)
    return task

@app.patch('/tasks/{task_id}', response_model=TaskResponse)
async def update_status(task_id: int, data: TaskStatusUpdate, user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await shared_task(task_id, db)
    task.completed = data.completed
    await db.commit()
    await db.refresh(task)
    return task

@app.delete('/tasks/{task_id}', status_code=204)
async def delete_task(task_id: int, user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await shared_task(task_id, db)
    await db.delete(task)
    await db.commit()
    return Response(status_code=204)
