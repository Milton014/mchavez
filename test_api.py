"""Pruebas de integración contra una SQLite temporal; no modifica test.db."""
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
DB_FILE = Path(TEMP.name) / 'tests.db'
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{DB_FILE.as_posix()}'

from fastapi.testclient import TestClient
from main import app
from security import hash_password, token_hash


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reproduce la tabla original, incluyendo una tarea previa.
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, name VARCHAR(100) NOT NULL, password_hash VARCHAR(255) NOT NULL)')
            db.execute('INSERT INTO users VALUES (1, ?, ?, ?)', ('demo', 'Cuenta anterior', hash_password('Demo1234')))
            db.execute('CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(100) NOT NULL, description VARCHAR(255), completed BOOLEAN NOT NULL)')
            db.execute("INSERT INTO tasks VALUES (1, 'Tarea anterior', 'Conservar', 0)")
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.password_hash = hash_password('Prueba1234')
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            cls.migrated = db.execute('SELECT title, description, completed, priority, owner_id FROM tasks WHERE id=1').fetchone()
            cls.migrated_user = db.execute('SELECT username, is_active FROM users WHERE id=1').fetchone()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        assert Path(TEMP.name).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        TEMP.cleanup()

    def setUp(self):
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            db.execute('DELETE FROM sessions')
            db.execute('DELETE FROM tasks')
            db.execute('DELETE FROM users')
            for user_id, username in [(1, 'uno'), (2, 'dos')]:
                db.execute('INSERT INTO users (id, username, name, password_hash) VALUES (?, ?, ?, ?)', (user_id, username, username, self.password_hash))

    def headers(self, username='uno'):
        response = self.client.post('/auth/login', json={'username': username, 'password': 'Prueba1234'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('password_hash', payload['user'])
        return {'Authorization': 'Bearer ' + payload['access_token']}

    def test_migration_preserves_original_task(self):
        self.assertEqual(self.migrated, ('Tarea anterior', 'Conservar', 0, 'media', None))
        self.assertEqual(self.migrated_user, ('demo', 1))

    def test_login_and_protection(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        for method, path, body in [('GET', '/tasks/', None), ('POST', '/tasks/', {'title': 'X'}), ('PUT', '/tasks/1', {'title': 'X'}), ('PATCH', '/tasks/1', {'completed': True}), ('DELETE', '/tasks/1', None)]:
            self.assertEqual(self.client.request(method, path, json=body).status_code, 401)
        for username, password in [('uno', 'incorrecta'), ('noexiste', 'Prueba1234'), ('uno', ' Prueba1234')]:
            self.assertEqual(self.client.post('/auth/login', json={'username': username, 'password': password}).status_code, 401)
        self.assertEqual(self.client.get('/auth/me', headers=self.headers()).json()['username'], 'uno')

    def test_crud_and_persistence(self):
        headers = self.headers()
        created = self.client.post('/tasks/', headers=headers, json={'title': '  Estudiar  ', 'description': 'Programación', 'priority': 'alta'})
        self.assertEqual(created.status_code, 201)
        task = created.json()
        self.assertEqual(task['title'], 'Estudiar')
        task_id = task['id']
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            self.assertEqual(db.execute('SELECT title, priority, owner_id FROM tasks WHERE id=?', (task_id,)).fetchone(), ('Estudiar', 'alta', 1))
        # Otra sesión consulta los datos almacenados; no dependen de la memoria del login.
        self.assertEqual(self.client.get('/tasks/', headers=self.headers()).json()[0]['id'], task_id)
        updated = self.client.put(f'/tasks/{task_id}', headers=headers, json={'title': 'Entrega', 'description': 'Revisada', 'priority': 'baja', 'completed': False})
        self.assertEqual(updated.status_code, 200)
        marked = self.client.patch(f'/tasks/{task_id}', headers=headers, json={'completed': True})
        self.assertTrue(marked.json()['completed'])
        self.assertEqual(marked.json()['description'], 'Revisada')
        self.assertEqual(self.client.get(f'/tasks/{task_id}', headers=headers).json()['priority'], 'baja')
        deleted = self.client.delete(f'/tasks/{task_id}', headers=headers)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b'')
        self.assertEqual(self.client.delete(f'/tasks/{task_id}', headers=headers).status_code, 404)

    def test_all_users_share_tasks(self):
        first, second = self.headers('uno'), self.headers('dos')
        task_id = self.client.post('/tasks/', headers=first, json={'title': 'Compartida'}).json()['id']
        self.assertEqual(self.client.get('/tasks/', headers=second).json()[0]['id'], task_id)
        self.assertEqual(self.client.get(f'/tasks/{task_id}', headers=second).status_code, 200)
        self.assertEqual(self.client.put(f'/tasks/{task_id}', headers=second, json={'title': 'Editada por otro'}).status_code, 200)
        self.assertEqual(self.client.patch(f'/tasks/{task_id}', headers=second, json={'completed': True}).status_code, 200)
        self.assertEqual(self.client.get(f'/tasks/{task_id}', headers=first).json()['title'], 'Editada por otro')
        self.assertEqual(self.client.delete(f'/tasks/{task_id}', headers=second).status_code, 204)
        self.assertEqual(self.client.get('/tasks/', headers=first).json(), [])

    def test_tasks_without_owner_are_visible(self):
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            db.execute("INSERT INTO tasks (title, completed, priority) VALUES ('Anterior', 0, 'media')")
        self.assertEqual(self.client.get('/tasks/', headers=self.headers()).json()[0]['title'], 'Anterior')

    def register(self, **changes):
        data = {'name': '  Nueva persona  ', 'username': 'Nueva', 'password': 'Una frase larga 2026!', 'confirm_password': 'Una frase larga 2026!'}
        return self.client.post('/auth/register', json={**data, **changes})

    def test_register_persistence_and_duplicate(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['name'], 'Nueva persona')
        self.assertEqual(response.json()['username'], 'nueva')
        self.assertEqual(set(response.json()), {'id', 'username', 'name'})
        self.assertEqual(self.register(username=' NUEVA ').status_code, 409)
        self.assertEqual(self.register(username='UNO').status_code, 409)
        login = self.client.post('/auth/login', json={'username': 'NUEVA', 'password': 'Una frase larga 2026!'})
        self.assertEqual(login.status_code, 200)
        with closing(sqlite3.connect(DB_FILE)) as db:
            stored = db.execute("SELECT password_hash FROM users WHERE username='nueva'").fetchone()[0]
            self.assertNotEqual(stored, 'Una frase larga 2026!')
            self.assertTrue(stored.startswith('pbkdf2_sha256$'))

    def test_register_validation_does_not_echo_passwords(self):
        for changes in [{'password': 'corta'}, {'confirm_password': 'distinta'}, {'name': '  '}, {'username': 'demo'}, {'username': 'a b'}, {'username': 'ab'}, {'username': 'x'*51}, {'password': ' '*15, 'confirm_password': ' '*15}, {'password': 'x'*129}, {'is_active': True}]:
            response = self.register(**changes)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('Una frase larga 2026!', response.text)
            for error in response.json()['detail']:
                self.assertNotIn('input', error)

    def test_password_change_requires_current_and_revokes_all_sessions(self):
        first, second = self.headers(), self.headers()
        other = self.headers('dos')
        data = {'current_password': 'Prueba1234', 'new_password': 'Mi nueva frase 2026!', 'confirm_password': 'Mi nueva frase 2026!'}
        self.assertEqual(self.client.post('/auth/change-password', json=data).status_code, 401)
        self.assertEqual(self.client.post('/auth/change-password', headers=first, json={**data, 'current_password': 'incorrecta'}).status_code, 400)
        self.assertEqual(self.client.get('/auth/me', headers=first).status_code, 200)
        self.assertEqual(self.client.post('/auth/change-password', headers=first, json={**data, 'confirm_password': 'otra'}).status_code, 422)
        self.assertEqual(self.client.post('/auth/change-password', headers=first, json=data).status_code, 204)
        for headers in [first, second]:
            self.assertEqual(self.client.get('/tasks/', headers=headers).status_code, 401)
        self.assertEqual(self.client.get('/tasks/', headers=other).status_code, 200)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'uno', 'password': 'Prueba1234'}).status_code, 401)
        login = self.client.post('/auth/login', json={'username': 'uno', 'password': data['new_password']})
        self.assertEqual(login.status_code, 200)
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        same = {'current_password': data['new_password'], 'new_password': data['new_password'], 'confirm_password': data['new_password']}
        self.assertEqual(self.client.post('/auth/change-password', headers=headers, json=same).status_code, 422)

    def test_demo_retired_only_after_successful_personal_login(self):
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            db.execute('INSERT INTO users (id, username, name, password_hash) VALUES (3, ?, ?, ?)', ('demo', 'Demo', self.password_hash))
        demo = self.headers('demo')
        task_id = self.client.post('/tasks/', headers=demo, json={'title': 'Conservar tarea demo'}).json()['id']
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.client.get('/tasks/', headers=demo).status_code, 200)
        self.client.post('/auth/login', json={'username': 'nueva', 'password': 'incorrecta'})
        self.assertEqual(self.client.get('/tasks/', headers=demo).status_code, 200)
        response = self.client.post('/auth/login', json={'username': 'nueva', 'password': 'Una frase larga 2026!'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/tasks/', headers=demo).status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'demo', 'password': 'Prueba1234'}).status_code, 401)
        headers = {'Authorization': 'Bearer ' + response.json()['access_token']}
        self.assertEqual(self.client.get(f'/tasks/{task_id}', headers=headers).json()['title'], 'Conservar tarea demo')

    def test_validation_and_pagination(self):
        headers = self.headers()
        for body in [{'title': '   '}, {'title': 'x' * 101}, {'title': 'X', 'description': 'x' * 256}, {'title': 'X', 'priority': 'urgente'}, {'title': 'X', 'owner_id': 2}]:
            self.assertEqual(self.client.post('/tasks/', headers=headers, json=body).status_code, 422)
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            db.executemany('INSERT INTO tasks (title, completed, priority, owner_id) VALUES (?, 0, ?, 1)', [(f'Tarea {i}', 'media') for i in range(105)])
        first = self.client.get('/tasks/?skip=0&limit=100', headers=headers).json()
        last = self.client.get('/tasks/?skip=100&limit=100', headers=headers).json()
        self.assertEqual((len(first), len(last)), (100, 5))
        self.assertEqual(len({task['id'] for task in first + last}), 105)
        self.assertEqual(self.client.get('/tasks/?skip=-1', headers=headers).status_code, 422)

    def test_logout_and_expiration(self):
        headers = self.headers()
        self.assertEqual(self.client.post('/auth/logout', headers=headers).status_code, 204)
        self.assertEqual(self.client.get('/tasks/', headers=headers).status_code, 401)
        headers = self.headers()
        hashed = token_hash(headers['Authorization'].split()[1])
        with closing(sqlite3.connect(DB_FILE)) as db, db:
            db.execute('UPDATE sessions SET expires_at=? WHERE token_hash=?', (int(time.time()) - 1, hashed))
        self.assertEqual(self.client.get('/tasks/', headers=headers).status_code, 401)

    def test_web_cors_preflight(self):
        response = self.client.options('/tasks/', headers={'Origin': 'http://localhost:8081', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:8081')


if __name__ == '__main__':
    unittest.main(verbosity=2)
