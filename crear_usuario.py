"""Alta local opcional. También se pueden crear cuentas desde la aplicación."""
import argparse
import asyncio
from getpass import getpass
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from database import AsyncSessionLocal, engine, init_db
from models import UserModel
from schemas import RegisterRequest
from security import hash_password


async def create_user(data: RegisterRequest):
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            if await db.scalar(select(UserModel.id).where(func.lower(UserModel.username) == data.username)) is not None:
                print('Ese usuario ya existe; no se modificó su contraseña.')
                return
            db.add(UserModel(username=data.username, name=data.name, password_hash=hash_password(data.password)))
            try:
                await db.commit()
                print(f'Cuenta creada: {data.username}. Ya podés iniciar sesión en la app.')
            except IntegrityError:
                await db.rollback()
                print('Ese usuario ya existe; elegí otro.')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Crear una cuenta personal del gestor de tareas.')
    parser.add_argument('--demo', action='store_true', help='Opción retirada: se debe crear una cuenta personal.')
    args = parser.parse_args()
    if args.demo:
        parser.error('El alta demo se retiró. Usá Crear cuenta en la app o ejecutá este programa sin --demo.')
    username = input('Usuario (3 a 50 letras, números, puntos o guiones): ')
    name = input('Nombre: ')
    password = getpass('Contraseña (15 a 128 caracteres): ')
    confirmation = getpass('Repetir contraseña: ')
    try:
        data = RegisterRequest(username=username, name=name, password=password, confirm_password=confirmation)
    except ValidationError as error:
        raise SystemExit('\n'.join(item['msg'] for item in error.errors()))
    asyncio.run(create_user(data))
