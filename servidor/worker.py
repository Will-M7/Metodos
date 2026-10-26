"""Despachador invocado por un comando forzado de OpenSSH. No escucha puertos."""
import argparse
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import uuid

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from servidor.config import default_home,load,authorized,exclusive,Busy
from servidor.protocolo import Channel,receive_files,send_files

OPERATIONS={'revisar','respuestas','generar'}
REPO=Path(__file__).resolve().parents[1]


def stop_tree(process):
    if process.poll() is not None:
        return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    else:
        try:
            os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name!='nt':
            os.killpg(process.pid,signal.SIGKILL)
        process.kill();process.wait()


def run_engine(mode,job,home,channel):
    log=job/'ejecucion.log'
    kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
    command=[sys.executable,'-B','-m','servidor.ejecutar',mode,str(job),str(home)]
    with log.open('w',encoding='utf-8') as output:
        process=subprocess.Popen(command,cwd=REPO,stdout=output,stderr=subprocess.STDOUT,**kwargs)
        try:
            started=heartbeat=time.monotonic()
            while process.poll() is None:
                if channel.disconnected.is_set():
                    raise EOFError('Cliente desconectado; trabajo cancelado')
                now=time.monotonic()
                if now-started>3600:
                    raise TimeoutError('Tiempo máximo del trabajo agotado')
                if now-heartbeat>=5:
                    channel.send(tipo='progreso',texto='Procesando en la laptop...')
                    heartbeat=now
                time.sleep(.1)
        finally:
            stop_tree(process)
    text=log.read_text(encoding='utf-8')
    marker={'revisar':'========== REVISION ACADEMICA','respuestas':'========== RESPUESTAS'}.get(mode)
    if marker and marker in text:
        text=text[text.index(marker):]
    return process.returncode,text[-200000:]


def session(home,channel,engine=run_engine):
    job=None
    try:
        request=channel.receive()
        mode=request.get('operacion')
        if request.get('v')!=1 or mode not in OPERATIONS:
            channel.send(tipo='error',texto='Operación no permitida');return 1
        settings=load(home)
        if not authorized(request.get('clave'),settings['autenticacion']):
            channel.send(tipo='rechazado',texto='Contraseña incorrecta');return 1
        probe=request.get('comprobar') is True
        request.clear()
        with exclusive(home):
            if probe:
                channel.send(tipo='disponible');return 0
            identifier=uuid.uuid4().hex
            jobs=home/'trabajos'
            if jobs.is_symlink():
                raise ValueError('Carpeta de trabajos inválida')
            jobs.mkdir(exist_ok=True)
            job=jobs/identifier;job.mkdir()
            channel.send(tipo='listo',trabajo=identifier)
            receive_files(channel,job,prefixes={'entrada','resultados'} if mode=='revisar' else {'entrada'})
            code,text=engine(mode,job,home,channel)
            for offset in range(0,len(text),8000):
                channel.send(tipo='salida',texto=text[offset:offset+8000])
            channel.send(tipo='resultado',codigo=code,texto='')
            if mode=='generar' and (job/'resultados').exists():
                send_files(channel,job/'resultados')
            channel.send(tipo='fin',trabajo=identifier)
            ack=channel.receive()
            if ack.get('tipo')!='recibido' or ack.get('trabajo')!=identifier:
                raise ValueError('Falta confirmación de entrega')
            shutil.rmtree(job);job=None
            channel.send(tipo='cerrado')
            return code
    except Busy as e:
        channel.send(tipo='ocupado',texto=str(e));return 3
    except (EOFError,BrokenPipeError,ConnectionError,TimeoutError):
        return 4
    except Exception as e:
        try:
            channel.send(tipo='error',texto=str(e))
        except (OSError,ValueError):
            pass
        return 1
    finally:
        if job and job.exists():
            shutil.rmtree(job)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,default=default_home())
    args=parser.parse_args()
    if os.environ.get('SSH_CONNECTION') and os.environ.get('SSH_ORIGINAL_COMMAND')!='metodos-v1':
        print('{"tipo":"error","texto":"Comando SSH no permitido"}')
        return 1
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    return session(args.home.resolve(),Channel(sys.stdin,sys.stdout))


if __name__=='__main__':
    raise SystemExit(main())
