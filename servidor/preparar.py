"""Alta privada e idempotente del servidor. Nunca recibe contraseñas por argumentos."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import venv
from .config import default_home,password_record,load

REPO=Path(__file__).resolve().parents[1]


def copy_verified(source,target,remove=False):
    if source.is_symlink() or target.is_symlink():
        raise ValueError('No migrar enlaces')
    files=[p for p in source.rglob('*') if p.is_file()] if source.exists() else []
    for p in files:
        if p.is_symlink() or any(a.is_symlink() for a in p.parents):
            raise ValueError('No migrar enlaces')
        dest=target/p.relative_to(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if dest.read_bytes()!=p.read_bytes():
                raise ValueError('Destino distinto; no sobrescrito: '+str(dest))
        else:
            shutil.copy2(p,dest)
        if hashlib.sha256(dest.read_bytes()).digest()!=hashlib.sha256(p.read_bytes()).digest():
            raise ValueError('La copia no coincide: '+str(p))
    # No eliminar un original antes de comprobar TODO el lote.
    if remove:
        for p in files:
            p.unlink()
        for p in sorted(source.rglob('*'),key=lambda p:len(p.parts),reverse=True):
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
    return len(files)


def initialize(home,password=None,migrate=False,repo=REPO):
    home,repo=home.resolve(),repo.resolve()
    if home==repo or repo in home.parents or home in repo.parents:
        raise ValueError('El directorio privado debe estar fuera del repositorio')
    if home.is_symlink():
        raise ValueError('El directorio privado no puede ser enlace')
    home.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name!='nt':
        home.chmod(0o700)
    else:
        who=os.environ.get('USERDOMAIN','')+'\\'+os.environ['USERNAME']
        subprocess.run(['icacls',str(home),'/inheritance:r','/grant:r',who+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],check=True,capture_output=True)
    for folder in ('referencias_clase','perfil_academico','trabajos','ssh'):
        (home/folder).mkdir(exist_ok=True)
    for name in ('AGENTS.md',):
        shutil.copy2(repo/name,home/name)
    config=home/'config.json'
    settings=load(home) if config.exists() else {}
    if not settings:
        if password is None:
            password=getpass.getpass('Contraseña inicial acordada para operaciones: ')
            if password!=getpass.getpass('Repetir contraseña: '):
                raise ValueError('Las contraseñas no coinciden')
        settings['autenticacion']=password_record(password)
    settings['repositorio']=str(repo)
    config.write_text(json.dumps(settings,indent=2),encoding='utf-8')
    if os.name!='nt':
        config.chmod(0o600)
    (repo/'.servidor.local').write_text(json.dumps({'home':str(home)}),encoding='utf-8')
    copy_verified(repo/'perfil_academico',home/'perfil_academico') if not any((home/'perfil_academico').iterdir()) else None
    # Guardar la memoria anterior sin considerarla autoridad matemática.
    if (repo/'.mn_cache').exists():
        copy_verified(repo/'.mn_cache',home/'legado_cache',remove=migrate)
        legacy=home/'legado_cache/referencias.json'
        active=home/'.mn_cache/referencias.json'
        if legacy.exists() and not active.exists():
            active.parent.mkdir(exist_ok=True)
            shutil.copy2(legacy,active)
    count=copy_verified(repo/'referencias_clase',home/'referencias_clase',remove=migrate)
    return count


def prepare_venv(home,install=False):
    folder=home/'venv'
    python=folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        if not install:
            return Path(sys.executable)
        venv.EnvBuilder(with_pip=True).create(folder)
    result=subprocess.run([str(python),'-c','import openpyxl,pypdf,pypdfium2,PIL'],capture_output=True)
    if result.returncode and install:
        subprocess.run([str(python),'-m','pip','install','-r',str(REPO/'requirements.txt')],check=True)
    return python


def tailscale_ip():
    binary=shutil.which('tailscale')
    if not binary and os.name=='nt':
        candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Tailscale/tailscale.exe'
        if candidate.exists():
            binary=str(candidate)
    if not binary:
        return None
    try:
        p=subprocess.run([binary,'ip','-4'],capture_output=True,text=True,timeout=15)
        import ipaddress
        ip=p.stdout.strip().splitlines()[0]
        return ip if ipaddress.ip_address(ip) in ipaddress.ip_network('100.64.0.0/10') else None
    except (OSError,IndexError,ValueError,subprocess.TimeoutExpired):
        return None


def configure_ssh(home,python,public_key,port=2222):
    ip=tailscale_ip()
    if not ip:
        raise ValueError('Falta Tailscale conectado: iniciar sesión con tailscale up')
    sshkeygen=shutil.which('ssh-keygen')
    if not sshkeygen:
        raise ValueError('Falta OpenSSH / ssh-keygen')
    key=home/'ssh/host_ed25519'
    if not key.exists():
        subprocess.run([sshkeygen,'-t','ed25519','-f',str(key),'-N',''],check=True,capture_output=True)
    if public_key:
        line=Path(public_key).read_text(encoding='utf-8').strip()
        import re
        if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?',line):
            raise ValueError('Se requiere clave pública ED25519, nunca la privada')
        auth=home/'ssh/authorized_keys'
        existing=auth.read_text(encoding='utf-8').splitlines() if auth.exists() else []
        if line not in existing:
            auth.write_text('\n'.join(existing+[line])+'\n',encoding='utf-8')
        if os.name!='nt':
            auth.chmod(0o600)
    if not (home/'ssh/authorized_keys').exists():
        raise ValueError('Falta enrolar la clave pública de un cliente con --clave-publica')
    quote=lambda p: '"'+str(p).replace('\\','/').replace('"','')+'"'
    command=quote(python)+' -B '+quote(REPO/'servidor/worker.py')+' --home '+quote(home)
    config=f'''Port {port}
ListenAddress {ip}
HostKey {quote(key)}
PidFile {quote(home/'ssh/sshd.pid')}
AuthorizedKeysFile {quote(home/'ssh/authorized_keys')}
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers {getpass.getuser()}
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTTY no
PermitTunnel no
ClientAliveInterval 15
ClientAliveCountMax 3
ForceCommand {command}
'''
    if os.name!='nt':
        config+='UsePAM no\n'
    path=home/'ssh/sshd_config';path.write_text(config,encoding='utf-8')
    sshd=shutil.which('sshd') or ('/usr/sbin/sshd' if Path('/usr/sbin/sshd').exists() else None)
    if not sshd:
        win=Path(os.environ.get('WINDIR','C:/Windows'))/'System32/OpenSSH/sshd.exe'
        sshd=str(win) if win.exists() else None
    if not sshd:
        raise ValueError('Falta OpenSSH Server; instalar componente oficial. No se abrió ningún puerto')
    subprocess.run([sshd,'-t','-f',str(path)],check=True,capture_output=True)
    fingerprint=subprocess.run([sshkeygen,'-lf',str(key)+'.pub','-E','sha256'],capture_output=True,text=True,check=True).stdout.strip()
    print('IP privada:',ip,'Puerto:',port,'Usuario:',getpass.getuser())
    print('Huella que debe verificar el cliente:',fingerprint)
    print('Configuración SSH privada:',path)
    return sshd,path,ip


def activate(home,sshd,path,ip,port):
    # Instancia propia, enlazada EXCLUSIVAMENTE a la IP Tailscale. No tocar sshd ajeno.
    if os.name=='nt':
        script=REPO/'servidor/activar_ssh.ps1'
        subprocess.run(['powershell','-NoProfile','-File',str(script),'-Ejecutable',sshd,'-Configuracion',str(path),'-Direccion',ip,'-Puerto',str(port)],check=True)
    else:
        service=home/'ssh/metodos-ssh.service'
        escaped=lambda v: str(v).replace('\\','\\\\').replace('"','\\"').replace('%','%%')
        service.write_text('[Unit]\nDescription=Metodos SSH privado\nAfter=network-online.target\n[Service]\nExecStart="'+escaped(sshd)+'" -D -e -f "'+escaped(path)+'"\nRestart=on-failure\n[Install]\nWantedBy=default.target\n')
        subprocess.run(['systemctl','--user','link',str(service)],check=True)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','enable','--now','metodos-ssh.service'],check=True)
        print('Servicio propio de usuario habilitado. Para sobrevivir al cierre de sesión: administrador puede habilitar loginctl enable-linger para este usuario.')


def health(home,probe=False):
    from src import octave,codex
    checks={}
    for module in ('openpyxl','pypdf','pypdfium2','PIL'):
        try:
            __import__(module);checks[module]=True
        except ImportError:
            checks[module]=False
    try:
        octave.run('clc\nclear\nx = 2+2',[{'variable':'x','valores':[4],'celdas':[],'tolerancia':1e-8}]);checks['Octave real']=True
    except Exception:
        checks['Octave real']=False
    checks['Codex instalado']=bool(shutil.which('codex'))
    if probe:
        try:
            codex.invoke(home,'Prueba mínima: sin herramientas, devuelve reglas vacías y advertencias vacías.',codex.PROFILE)
            checks['Codex exec real']=True
        except Exception as e:
            checks['Codex exec real']=False
            print('Codex pendiente:',e)
    print('\nComprobaciones:',json.dumps(checks,ensure_ascii=False))
    print('Componentes de cálculo:', 'VERIFICADOS' if probe and all(checks.values()) else 'PENDIENTES de comprobaciones indicadas')
    return all(checks.values()) and probe


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--home',type=Path,default=default_home())
    p.add_argument('--instalar-paquetes',action='store_true')
    p.add_argument('--migrar-referencias',action='store_true')
    p.add_argument('--clave-publica',type=Path)
    p.add_argument('--activar-ssh',action='store_true')
    p.add_argument('--puerto',type=int,default=2222)
    p.add_argument('--probar-codex',action='store_true')
    p.add_argument('--revisar-referencias',action='store_true')
    args=p.parse_args()
    if not 1024<=args.puerto<=65535:
        p.error('Usar puerto no privilegiado 1024..65535')
    try:
        home=args.home.resolve()
        count=initialize(home,migrate=args.migrar_referencias)
        print('Directorio privado:',home,'Archivos originales copiados y verificados:',count)
        python=prepare_venv(home,args.instalar_paquetes)
        if args.instalar_paquetes and Path(sys.prefix).resolve()!=(home/'venv').resolve():
            # Reentrar para probar con el mismo intérprete que usará SSH, sin reinstalar ni volver a pedir contraseña.
            command=[str(python),'-B','-m','servidor.preparar','--home',str(home),'--puerto',str(args.puerto)]
            if args.clave_publica:command+=['--clave-publica',str(args.clave_publica.resolve())]
            if args.activar_ssh:command+=['--activar-ssh']
            if args.probar_codex:command+=['--probar-codex']
            if args.revisar_referencias:command+=['--revisar-referencias']
            return subprocess.run(command,cwd=REPO).returncode
        healthy=health(home,args.probar_codex)
        if args.revisar_referencias:
            from src.memoria import academic
            with tempfile.TemporaryDirectory(prefix='mn_revision_inicial_') as d:
                records,warnings=academic(home,Path(d))
            print('Referencias revisadas:',len(records))
            for warning in warnings:print('REFERENCIA:',warning)
        try:
            sshd,path,ip=configure_ssh(home,python,args.clave_publica,args.puerto)
            if args.activar_ssh:
                activate(home,sshd,path,ip,args.puerto)
            with socket.create_connection((ip,args.puerto),timeout=3) as connection:
                if not connection.recv(256).startswith(b'SSH-'):
                    raise ValueError('Puerto no responde como SSH')
            print('SSH privado responde. Falta probar autorización y entrega desde el cliente.')
        except Exception as e:
            print('SSH PENDIENTE:',e);return 2
        return 0 if healthy else 2
    except Exception as e:
        print('Preparación incompleta:',e,file=sys.stderr);return 1


if __name__=='__main__':
    raise SystemExit(main())
