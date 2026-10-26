"""Archivos en tramas JSON sobre stdin/stdout de SSH; sin shell ni SFTP abierto."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import queue
import re
import threading

MAX_TOTAL=100*1024*1024
MAX_FILES=100
CHUNK=48*1024
SUFFIXES={'.pdf','.xlsx','.xlsm','.m','.txt','.md','.csv','.png','.jpg','.jpeg'}


def safe_path(name, prefixes=None):
    if not isinstance(name,str) or len(name)>240 or '\\' in name or ':' in name:
        raise ValueError('Ruta no permitida')
    parts=PurePosixPath(name).parts
    if not parts or PurePosixPath(name).is_absolute() or any(p in ('.','..') or p.startswith('.') or p.endswith((' ','.')) or
        re.search(r'[\x00-\x1f<>"|?*]',p) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?',p,re.I) for p in parts):
        raise ValueError('Ruta no permitida')
    if '/'.join(parts)!=name or (prefixes and (parts[0] not in prefixes or len(parts)<2)):
        raise ValueError('Ruta no permitida')
    if PurePosixPath(name).suffix.lower() not in SUFFIXES:
        raise ValueError('Tipo de archivo no permitido')
    return Path(*parts)


class Channel:
    def __init__(self,reader,writer,timeout=90):
        self.reader,self.writer,self.timeout=reader,writer,timeout
        self.queue=queue.Queue(maxsize=2)
        self.disconnected=threading.Event()
        threading.Thread(target=self._read,daemon=True).start()

    def _read(self):
        try:
            while True:
                line=self.reader.readline(128*1024)
                if not line:
                    break
                if not line.endswith('\n'):
                    self.queue.put(ValueError('Trama demasiado larga o incompleta'));break
                self.queue.put(line)
        except (OSError,ValueError):
            pass
        finally:
            self.disconnected.set()
            self.queue.put(EOFError('Conexión cerrada'))

    def receive(self):
        try:
            value=self.queue.get(timeout=self.timeout)
        except queue.Empty as e:
            raise TimeoutError('Tiempo de transferencia agotado') from e
        if isinstance(value,Exception):
            raise value
        value=json.loads(value)
        if not isinstance(value,dict):
            raise ValueError('Trama inválida')
        return value

    def send(self,**payload):
        self.writer.write(json.dumps(payload,ensure_ascii=True,separators=(',',':'))+'\n')
        self.writer.flush()


def receive_files(channel,folder,prefixes=None):
    total,count,seen=0,0,set()
    while True:
        header=channel.receive()
        if header.get('tipo')=='fin_envio':
            if count==0:
                raise ValueError('Trabajo vacío')
            return
        if header.get('tipo')!='archivo':
            raise ValueError('Se esperaba archivo')
        relative=safe_path(header.get('ruta'),prefixes or {'entrada','resultados'})
        key=str(relative).casefold()
        size=header.get('bytes')
        if type(size) is not int or size<0 or size>MAX_TOTAL or total+size>MAX_TOTAL or count>=MAX_FILES or key in seen:
            raise ValueError('Archivo duplicado o límites excedidos')
        if not re.fullmatch(r'[a-f0-9]{64}',str(header.get('sha256',''))):
            raise ValueError('Hash inválido')
        seen.add(key);total+=size;count+=1
        target=folder/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        actual=hashlib.sha256();received=0
        with target.open('xb') as output:
            while received<size:
                frame=channel.receive()
                if frame.get('tipo')!='datos':
                    raise ValueError('Se esperaban datos')
                data=base64.b64decode(frame.get('base64',''),validate=True)
                if not data or len(data)>CHUNK or received+len(data)>size:
                    raise ValueError('Tamaño de datos inválido')
                output.write(data);actual.update(data);received+=len(data)
        if channel.receive().get('tipo')!='fin_archivo' or actual.hexdigest()!=header['sha256']:
            raise ValueError('Transferencia incompleta o hash diferente')


def send_files(channel,folder):
    paths=[]
    for p in sorted(folder.rglob('*')):
        if p.is_file() and not p.is_symlink() and not any(d.is_symlink() for d in p.parents):
            relative=p.relative_to(folder).as_posix()
            safe_path(relative)
            paths.append((p,relative))
    if len(paths)>MAX_FILES or sum(p.stat().st_size for p,_ in paths)>MAX_TOTAL:
        raise ValueError('Entregables exceden límite de transferencia')
    for path,relative in paths:
        hashed=hashlib.sha256(path.read_bytes()).hexdigest()
        channel.send(tipo='archivo',ruta=relative,bytes=path.stat().st_size,sha256=hashed)
        with path.open('rb') as source:
            while data:=source.read(CHUNK):
                channel.send(tipo='datos',base64=base64.b64encode(data).decode())
        channel.send(tipo='fin_archivo')
