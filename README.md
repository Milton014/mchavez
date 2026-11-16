# Backend de gestión de tareas — 2.1

Registro de cuentas personales, cambio de contraseña y tareas compartidas para todos los usuarios autenticados.

Conservá tu archivo `test.db`. Al iniciar se agrega `users.is_active` y un índice único de usuarios sin distinguir mayúsculas. No se borran tareas.

```powershell
cd "C:\Users\Usuario\Desktop\app-mchavez\mchavez"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Creá tu cuenta desde la app. No ejecutes `crear_usuario.py --demo`: la opción fue retirada. Como alternativa local, `crear_usuario.py` sin argumentos pide los datos por terminal.

Al ingresar correctamente con una cuenta distinta de `demo`, se desactiva el acceso de prueba y sus sesiones. Las tareas se conservan y se comparten.

Pruebas con SQLite temporal:

```powershell
.\.venv\Scripts\python.exe -m unittest test_api -v
```

Guía completa de instalación y funcionamiento: `../../app-gestiondetareas/README.md`.
