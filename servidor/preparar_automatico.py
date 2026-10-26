"""Configuración única de Ubuntu: conserva motor/datos y automatiza el alta privada."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shlex
import socket
import ssl
import subprocess
import sys
import urllib.request
from .config import default_home,exclusive
from .enrolamiento import atomic_json,atomic_text,tail_json
from .preparar import REPO,initialize,prepare_venv,configure_ssh,health

SERVER_IP='100.116.157.0'


def unit_text(description,command,repo,path):
    def quote(value):
        if '\n' in str(value) or '\r' in str(value):raise ValueError('Ruta inválida para systemd')
        return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    return ('[Unit]\nDescription='+description+'\nAfter=network-online.target\n[Service]\nType=simple\n'
            +'WorkingDirectory='+str(repo)+'\nEnvironment='+quote('PATH='+path)+'\n'
            +'ExecStart='+' '.join(quote(v) for v in command)+'\nRestart=on-failure\nRestartSec=5\nUMask=0077\n'
            +'[Install]\nWantedBy=default.target\n')


def prepare_services(home,python,settings):
    # Forzar el PATH verificado también dentro de la sesión no interactiva de sshd.
    launcher=home/'ssh/despachar.sh'
    atomic_text(launcher,'#!/bin/sh\nexport PATH='+shlex.quote(os.environ['PATH'])+'\nexec '+
                ' '.join(shlex.quote(str(x)) for x in [python,'-B',REPO/'servidor/worker.py','--home',home])+'\n')
    launcher.chmod(0o700)
    sshd,config,ip=configure_ssh(home,python,None,allow_empty=True,launcher=launcher)
    if ip!=settings['server_ip']:raise ValueError('La IP de esta laptop no coincide con la configurada')
    specs={
        'metodos-ssh.service':('Metodos SSH privado',[sshd,'-D','-e','-f',str(config)]),
        'metodos-alta.service':('Metodos alta privada',[str(python),'-B','-m','servidor.enrolamiento','servir','--home',str(home)])}
    for name,(description,command) in specs.items():
        target=home/'ssh'/name
        text=unit_text(description,command,REPO,os.environ['PATH'])
        if target.exists() and ('Description='+description+'\n') not in target.read_text():
            raise ValueError('Unidad con propietario ambiguo: '+name)
        target.write_text(text,encoding='utf-8');target.chmod(0o600)
        subprocess.run(['systemctl','--user','link',str(target)],check=True)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    for name in specs:
        subprocess.run(['systemctl','--user','enable','--now',name],check=True)
        subprocess.run(['systemctl','--user','restart',name],check=True)
        subprocess.run(['systemctl','--user','is-active','--quiet',name],check=True)
        subprocess.run(['systemctl','--user','is-enabled','--quiet',name],check=True)


def configure_serve(home):
    # Sólo el subpath propio; nunca resetear Serve, activar Funnel o tocar otras aplicaciones.
    existing=tail_json('serve','status','--json')
    target='unix:'+str(home/'alta.sock')
    for web in existing.get('Web',{}).values():
        for path,handler in web.get('Handlers',{}).items():
            if path.rstrip('/')=='/metodos-alta' and handler.get('Proxy') not in (target,'http://'+target):
                raise ValueError('El path de Serve pertenece a otra configuración; no se sobrescribió')
    command=['tailscale','serve','--bg','--https=443','--set-path=/metodos-alta',target]
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if result.returncode and any(s in (result.stderr+result.stdout).lower() for s in ('access denied','permission denied')):
        result=subprocess.run(['sudo',*command],text=True,timeout=120)
    if result.returncode:raise RuntimeError('No se confirmó Serve HTTPS; revisar permiso/consentimiento TLS en la tailnet')
    status=tail_json('serve','status','--json')
    found=any(path.rstrip('/')=='/metodos-alta' and handler.get('Proxy') in (target,'http://'+target)
              for web in status.get('Web',{}).values() for path,handler in web.get('Handlers',{}).items())
    if not found:raise RuntimeError('Serve no devolvió la ruta/backend HTTPS esperados')
    if any(status.get('AllowFunnel',{}).values()):
        raise RuntimeError('Existe Funnel en esta máquina; revisar exposición antes de declarar el alta privada lista')


def settings_from_status(status,expected_ip):
    self_node=status['Self']
    if status['BackendState']!='Running' or expected_ip not in status['TailscaleIPs'] or self_node.get('Tags'):
        raise ValueError('Se requiere la laptop personal autenticada con la IP Tailscale esperada')
    dns=self_node['DNSName'].rstrip('.')
    import re
    if not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9.-]+\.ts\.net',dns,re.I):raise ValueError('DNS Tailscale no válido')
    user_id=str(self_node['UserID'])
    if not user_id.isdecimal() or int(user_id)<=0:raise ValueError('No se pudo determinar propietario de la laptop')
    return {'owner_user_id':user_id,'server_ip':expected_ip,'ssh_user':getpass.getuser(),'dns':dns,'allowed_nodes':[]}


def verify_services(home,settings):
    for name in ('metodos-ssh.service','metodos-alta.service'):
        subprocess.run(['systemctl','--user','is-active','--quiet',name],check=True)
        subprocess.run(['systemctl','--user','is-enabled','--quiet',name],check=True)
    linger=subprocess.run(['loginctl','show-user',getpass.getuser(),'-p','Linger','--value'],check=True,capture_output=True,text=True).stdout.strip()
    if linger!='yes':raise RuntimeError('Linger no confirmado')
    with socket.create_connection((settings['server_ip'],2222),timeout=5) as remote:
        if not remote.recv(256).startswith(b'SSH-'):raise RuntimeError('No se recibió banner SSH')
    # Certificado HTTPS real, sin desactivar verificación ni inyectar cabeceras de identidad.
    url='https://'+settings['dns']+'/metodos-alta/info'
    with urllib.request.urlopen(url,context=ssl.create_default_context(),timeout=15) as response:
        data=json.load(response)
    from .enrolamiento import server_info
    if data!=server_info(home):raise RuntimeError('HTTPS no devolvió la identidad SSH local esperada')


def diagnose():
    checks={}
    for label,command in [('Tailscale',['tailscale','status','--json']),
                          ('systemd usuario',['systemctl','--user','show-environment']),
                          ('linger',['loginctl','show-user',getpass.getuser(),'-p','Linger','--value'])]:
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=15)
            checks[label]=result.returncode==0
            if result.returncode:print(label+': PENDIENTE — '+result.stderr.strip()[:400])
        except (OSError,subprocess.TimeoutExpired):checks[label]=False
    # Prueba Codex real/Octave sin crear configuración, migrar referencias ni tocar servicios.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='metodos-comprobar-') as temp:
        checks['motor']=health(Path(temp),probe=True)
    print('Diagnóstico:',json.dumps(checks,ensure_ascii=False))
    return 0 if all(checks.values()) else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,default=default_home())
    parser.add_argument('--ip',default=SERVER_IP)
    parser.add_argument('--comprobar',action='store_true')
    args=parser.parse_args()
    if args.comprobar:return diagnose()
    try:
        if os.name!='posix' or os.geteuid()==0:raise ValueError('Ejecutar como usuario propietario de Ubuntu')
        home=args.home.resolve()
        settings=settings_from_status(tail_json('status','--json'),args.ip)
        initialize(home,migrate=False)  # Esta corrección nunca retira ni altera referencias existentes.
        config=home/'alta_config.json'
        if config.exists():
            previous=json.loads(config.read_text())
            if previous['owner_user_id']!=settings['owner_user_id']:raise ValueError('Cambio de propietario: requiere revisión local explícita')
            settings['allowed_nodes']=previous.get('allowed_nodes',[])
        atomic_json(config,settings)
        python=prepare_venv(home,install=True)
        if Path(sys.prefix).resolve()!=(home/'venv').resolve():
            return subprocess.run([str(python),'-B','-m','servidor.preparar_automatico','--home',str(home),'--ip',args.ip],cwd=REPO).returncode
        with exclusive(home):
            prepare_services(home,python,settings)
            configure_serve(home)
            verify_services(home,settings)
            mathematics=health(home,probe=True)
            atomic_json(home/'disponibilidad.json',{'motor_verificado':mathematics})
            if not mathematics:raise RuntimeError('SSH/alta configurados, motor real pendiente; no declarar el sistema listo')
        print('SSH y alta HTTPS privados reiniciados y comprobados; linger y arranque habilitados.')
        print('Ubuntu preparado. Falta validar el ciclo completo desde Windows real.')
        print('Alta:', 'https://'+settings['dns']+'/metodos-alta')
        return 0
    except Exception as error:
        print('PREPARACIÓN INCOMPLETA:',error,file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
