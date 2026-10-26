"""Configuración privada, contraseña y exclusión mutua. Sólo biblioteca estándar."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path


def default_home():
    if os.environ.get('METODOS_SERVIDOR_HOME'):
        return Path(os.environ['METODOS_SERVIDOR_HOME']).expanduser().resolve()
    base = Path(os.environ.get('LOCALAPPDATA', Path.home())) if os.name == 'nt' else Path.home()/'.local/share'
    return base/'metodos-servidor'


def password_record(password):
    if not password or len(password) > 256:
        raise ValueError('Contraseña vacía o demasiado larga')
    salt = os.urandom(32)
    return {'sal': base64.b64encode(salt).decode(), 'iteraciones': 600000,
            'verificador': hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000).hex()}


def authorized(password, record):
    if not isinstance(password,str) or not 0 < len(password) <= 256:
        return False
    actual=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.b64decode(record['sal']),record['iteraciones']).hex()
    return hmac.compare_digest(actual,record['verificador'])


def load(home):
    path=home/'config.json'
    if path.is_symlink():
        raise ValueError('Configuración enlazada no permitida')
    return json.loads(path.read_text(encoding='utf-8'))


class Busy(Exception):
    pass


@contextmanager
def exclusive(home):
    path=home/'trabajos.lock'
    if path.is_symlink():
        raise ValueError('Lock enlazado no permitido')
    with open(path,'a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:
            lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:
            raise Busy('Servidor ocupado; no se recibió ni procesó el trabajo.') from e
        try:
            yield
        finally:
            lock.seek(0)
            if os.name=='nt':
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(lock,fcntl.LOCK_UN)
