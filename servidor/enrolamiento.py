"""Alta limitada detrás de Tailscale Serve HTTPS. Backend Unix privado, sin TCP propio."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import getpass
import hashlib
from http.server import BaseHTTPRequestHandler
import ipaddress
import json
import os
from pathlib import Path
import re
import socketserver
import struct
import subprocess
import tempfile
from email.header import decode_header,make_header
from .config import default_home

BEGIN='# BEGIN METODOS ENROLAMIENTO'
END='# END METODOS ENROLAMIENTO'


class Denied(ValueError):
    pass


def atomic_json(path,data):
    atomic_text(path,json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def atomic_text(path,text):
    if path.is_symlink():
        raise Denied('Archivo privado enlazado')
    fd,name=tempfile.mkstemp(prefix='.alta-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            os.fchmod(out.fileno(),0o600);out.write(text);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def tail_json(*arguments):
    result=subprocess.run(['tailscale',*arguments],capture_output=True,text=True,timeout=15,check=True)
    return json.loads(result.stdout)


def public_key(text):
    """Validar formato SSH binario ED25519 (nombre + exactamente 32 bytes), no sólo prefijo."""
    if not isinstance(text,str) or len(text)>400 or '\n' in text or '\r' in text:
        raise Denied('Clave pública ED25519 inválida')
    parts=text.strip().split()
    if len(parts) not in (2,3) or parts[0]!='ssh-ed25519':
        raise Denied('Sólo se admiten claves públicas ED25519')
    try:
        blob=base64.b64decode(parts[1],validate=True)
    except (ValueError,TypeError) as e:
        raise Denied('Base64 de clave inválido') from e
    expected=struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',32)
    if len(blob)!=len(expected)+32 or not blob.startswith(expected):
        raise Denied('Estructura ED25519 inválida')
    canonical='ssh-ed25519 '+base64.b64encode(blob).decode()
    fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
    return canonical,fingerprint


def identity(headers,settings,whois=None):
    whois=whois or tail_json
    """Serve sobrescribe XFF e identidad; WhoIs contrasta nodo/usuario reales del daemon."""
    for key in ('X-Forwarded-For','Tailscale-User-Login','X-Forwarded-Proto'):
        if hasattr(headers,'get_all') and len(headers.get_all(key,[]))!=1:
            raise Denied('Cabeceras ausentes o repetidas')
    if headers.get('X-Forwarded-Proto')!='https' or headers.get('Tailscale-Funnel-Request'):
        raise Denied('Se requiere HTTPS privado de Serve; Funnel no está permitido')
    try:
        peer=ipaddress.ip_address(headers.get('X-Forwarded-For',''))
    except ValueError as e:
        raise Denied('Origen Serve no válido') from e
    if not (peer in ipaddress.ip_network('100.64.0.0/10') if peer.version==4 else peer in ipaddress.ip_network('fd7a:115c:a1e0::/48')):
        raise Denied('El origen no pertenece a la tailnet')
    try:
        data=whois('whois','--json',str(peer))
        node,user=data['Node'],data['UserProfile']
        login=str(make_header(decode_header(headers.get('Tailscale-User-Login',''))))
        user_id=str(user['ID']);node_id=node['StableID'];node_user=str(node['User'])
        addresses=[ipaddress.ip_interface(address).ip for address in node['Addresses']]
    except Exception as e:
        raise Denied('No se pudo verificar identidad mediante tailscale whois') from e
    if (node.get('Tags') or not isinstance(node_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',node_id)
        or user_id!=str(settings['owner_user_id']) or node_user!=user_id
        or not login or login!=user['LoginName'] or peer not in addresses):
        raise Denied('Sólo dispositivos personales autenticados del propietario autorizado')
    allowed=settings.get('allowed_nodes',[])
    if allowed and node_id not in allowed:
        raise Denied('Dispositivo fuera de la lista autorizada')
    ips=[str(ip) for ip in addresses if (ip.version==4 and ip in ipaddress.ip_network('100.64.0.0/10')) or
         (ip.version==6 and ip in ipaddress.ip_network('fd7a:115c:a1e0::/48'))]
    return {'node_id':node_id,'user_id':user_id,'addresses':ips}


class Registry:
    def __init__(self,home):
        self.home=home
        self.path=home/'enrolamiento.json'
        self.keys=home/'ssh/authorized_keys'

    @contextmanager
    def locked(self):
        lock=self.home/'enrolamiento.lock'
        if lock.is_symlink():raise Denied('Lock enlazado')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(handle,fcntl.LOCK_UN)

    def load(self):
        if self.path.is_symlink():raise Denied('Registro enlazado')
        return json.loads(self.path.read_text()) if self.path.exists() else {'keys':{},'blocked_nodes':[]}

    def persist(self,data):
        original=self.keys.read_text() if self.keys.exists() else ''
        pattern=re.escape(BEGIN)+r'.*?'+re.escape(END)
        legacy=re.sub(pattern,'',original,flags=re.S).strip()
        if BEGIN in legacy or END in legacy:raise Denied('Marcadores SSH incompletos')
        lines=[]
        for fp,key in sorted(data['keys'].items()):
            if key['node_id'] in data['blocked_nodes'] or key.get('revoked'):continue
            cidrs=','.join(str(ipaddress.ip_network(ip+'/32' if ':' not in ip else ip+'/128')) for ip in key['addresses'])
            canonical,_=public_key(key['public_key'])
            lines.append(f'restrict,from="{cidrs}" {canonical} metodos-{key["node_id"]}')
        text=(legacy+'\n' if legacy else '')+BEGIN+'\n'+'\n'.join(lines)+'\n'+END+'\n'
        atomic_text(self.keys,text)
        atomic_json(self.path,data)

    def enroll(self,peer,text):
        canonical,fp=public_key(text)
        with self.locked():
            data=self.load()
            if peer['node_id'] in data['blocked_nodes']:raise Denied('Dispositivo revocado')
            previous=data['keys'].get(fp)
            if previous and (previous['node_id']!=peer['node_id'] or previous.get('revoked')):
                raise Denied('Clave revocada o vinculada a otro dispositivo')
            original=self.keys.read_text() if self.keys.exists() else ''
            legacy=re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END),'',original,flags=re.S)
            if canonical in legacy:raise Denied('Clave preexistente fuera del registro; requiere revisión local')
            data['keys'][fp]={**peer,'public_key':canonical,'revoked':False}
            self.persist(data)
        return fp

    def revoke(self,node_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',node_id):raise Denied('ID de nodo inválido')
        with self.locked():
            data=self.load()
            if node_id not in data['blocked_nodes']:data['blocked_nodes'].append(node_id)
            for key in data['keys'].values():
                if key['node_id']==node_id:key['revoked']=True
            self.persist(data)

    def check(self,peer):
        with self.locked():
            if peer['node_id'] in self.load()['blocked_nodes']:raise Denied('Dispositivo revocado')


def server_info(home):
    key,fp=public_key((home/'ssh/host_ed25519.pub').read_text().strip())
    settings=json.loads((home/'alta_config.json').read_text())
    return {'servidor':settings['server_ip'],'puerto':2222,'usuario':settings['ssh_user'],
            'huella':fp,'clave_servidor':key}


class Handler(BaseHTTPRequestHandler):
    server_version='MetodosAlta/1'
    def address_string(self):return 'unix'
    def log_message(self,*args):pass  # No registrar cuerpos, cabeceras ni claves.

    def respond(self,status,data):
        content=json.dumps(data,ensure_ascii=True).encode()
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(content)))
        self.end_headers();self.wfile.write(content)

    def handle_action(self,post):
        try:
            settings=json.loads((self.server.home/'alta_config.json').read_text())
            peer=identity(self.headers,settings)
            registry=Registry(self.server.home);registry.check(peer)
            path=self.path
            if path.startswith('/metodos-alta/'):path=path[len('/metodos-alta'):]
            if not post and path=='/info':return self.respond(200,server_info(self.server.home))
            if not post or path!='/enrolar':return self.respond(404,{'error':'Ruta no permitida'})
            if self.headers.get('Transfer-Encoding'):raise Denied('Transfer-Encoding no permitido')
            lengths=self.headers.get_all('Content-Length',[])
            if len(lengths)!=1:raise Denied('Longitud requerida')
            size=int(lengths[0])
            if not 1<=size<=2048:raise Denied('Solicitud demasiado grande')
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict) or set(payload)!={'clave_publica'}:raise Denied('Sólo se admite una clave pública')
            metadata=server_info(self.server.home)
            fp=registry.enroll(peer,payload['clave_publica'])
            return self.respond(200,{**metadata,'clave_cliente':fp})
        except Denied as e:self.respond(403,{'error':str(e)})
        except (ValueError,KeyError,UnicodeError):self.respond(400,{'error':'Solicitud inválida'})
        except Exception:self.respond(503,{'error':'Alta no disponible; no se confirmó el resultado'})

    def do_GET(self):self.handle_action(False)
    def do_POST(self):self.handle_action(True)


class UnixServer(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
    def get_request(self):
        connection,address=super().get_request();connection.settimeout(15);return connection,address


def _serve(home):
    path=home/'alta.sock'
    if len(os.fsencode(path))>103:raise ValueError('Ruta privada demasiado larga para socket Unix')
    if path.exists() or path.is_symlink():
        # systemd mantiene una única instancia. No retirar archivos ajenos o enlaces.
        import stat
        if path.is_symlink() or not stat.S_ISSOCK(path.stat().st_mode) or path.stat().st_uid!=os.getuid():
            raise Denied('La ruta del socket pertenece a otro componente')
        path.unlink()
    with Registry(home).locked():
        registry=Registry(home);registry.persist(registry.load())
    old=os.umask(0o177)
    try:server=UnixServer(str(path),Handler)
    finally:os.umask(old)
    server.home=home;path.chmod(0o600)
    try:server.serve_forever(poll_interval=.5)
    finally:server.server_close();path.unlink(missing_ok=True)


def serve(home):
    lock=home/'alta_service.lock'
    if lock.is_symlink():raise Denied('Lock de servicio enlazado')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as held:
        try:fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:raise Denied('El servicio de alta ya está en ejecución') from e
        try:_serve(home)
        finally:fcntl.flock(held,fcntl.LOCK_UN)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('accion',choices=('servir','revocar','listar'))
    p.add_argument('--home',type=Path,default=default_home());p.add_argument('--nodo')
    args=p.parse_args();home=args.home.resolve()
    if args.accion=='servir':serve(home)
    elif args.accion=='revocar':
        if not args.nodo:p.error('revocar requiere --nodo')
        Registry(home).revoke(args.nodo);print('Nodo revocado; no podrá reenrolarse.')
    else:
        with Registry(home).locked():print(json.dumps(Registry(home).load(),indent=2))


if __name__=='__main__':main()
