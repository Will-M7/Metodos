"""Protocolo real en pipes; transporte SSH/Tailscale requiere dos máquinas y se prueba aparte."""
import base64
import contextlib
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from servidor.config import password_record,authorized,exclusive,Busy
from servidor import worker
from servidor.preparar import initialize,copy_verified
from servidor.protocolo import Channel,safe_path
from src import main,memoria,codex
from test_sistema import fixture,question,work,ROOT


def reference(status='VALIDADA'):
    q=question()
    return {'ejercicios':[{'id':'1','localizacion':'Hoja1 B2:B4','enunciado':'4*x+2*y=6;2*x+3*y=5',
        'procedimiento':'Sistema de prueba','formulas':['4*x+2*y=6','2*x+3*y=5'],'origen':'estudiante',
        'clasificacion':status,'errores':([{'ubicacion':'B3','formula_incorrecta':'2+2=5','correccion':'2+2=4','evidencia':'diferencia=1','comprobacion_error':{'expresion_original':'2+2','valor_documentado':5,'expresion_corregida':'2+2','valor_corregido':4,'tolerancia':1e-8}}] if status=='INCORRECTA' else []),
        'comprobaciones':q['comprobaciones'],'octave':q['octave'],'salidas':q['salidas']}],
        'reglas':[{'categoria':category,'regla':text,'fuente':'referencias_clase/ejemplo.md','evidencia':'Hoja1','ejercicio':'1'}
                  for category,text in [('metodos','regla matemática'),('estilo_excel','tabla sencilla')]],'advertencias':[]}


class Peer:
    """Dos pipes OS reales, equivalente a stdin/stdout antes del cifrado de SSH."""
    def __init__(self,home,engine):
        server_read,client_write=os.pipe()
        client_read,server_write=os.pipe()
        self.writer=os.fdopen(client_write,'w',encoding='utf-8',buffering=1)
        self.reader=os.fdopen(client_read,'r',encoding='utf-8')
        sr=os.fdopen(server_read,'r',encoding='utf-8')
        sw=os.fdopen(server_write,'w',encoding='utf-8',buffering=1)
        self.channel=Channel(sr,sw,timeout=2)
        self.result=None
        def serve():
            try:self.result=worker.session(home,self.channel,engine)
            finally:sw.close()
        self.thread=threading.Thread(target=serve,daemon=True);self.thread.start()
        self.output=queue.Queue()
        def read():
            for line in self.reader:self.output.put(json.loads(line))
            self.output.put(None)
        threading.Thread(target=read,daemon=True).start()

    def send(self,value):
        self.writer.write(json.dumps(value)+'\n');self.writer.flush()

    def get(self):
        return self.output.get(timeout=5)

    def login(self,mode='respuestas',password='clave-prueba',probe=False):
        self.send({'v':1,'operacion':mode,'clave':password,'comprobar':probe})
        return self.get()

    def file(self,path='entrada/problema.txt',data=b'ejercicio',wrong_hash=False):
        self.send({'tipo':'archivo','ruta':path,'bytes':len(data),'sha256':('0'*64 if wrong_hash else hashlib.sha256(data).hexdigest())})
        if data:self.send({'tipo':'datos','base64':base64.b64encode(data).decode()})
        self.send({'tipo':'fin_archivo'})

    def finish(self,identifier):
        self.send({'tipo':'fin_envio'})
        events=[]
        while True:
            event=self.get();events.append(event)
            if event is None or event['tipo']=='error':break
            if event['tipo']=='fin':
                self.send({'tipo':'recibido','trabajo':identifier})
                events.append(self.get());break
        return events

    def close(self):
        if not self.writer.closed:self.writer.close()
        self.thread.join(timeout=5)
        self.reader.close()
        self.channel.disconnected.wait(2)
        self.channel.reader.close()


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)/'privado';self.home.mkdir()
        fixture(self.home)
        (self.home/'config.json').write_text(json.dumps({'autenticacion':password_record('clave-prueba')}))
        self.peers=[];self.jobs=[]

    def tearDown(self):
        for peer in self.peers:peer.close()
        self.temp.cleanup()

    def engine(self,mode,job,home,channel):
        self.jobs.append(job)
        self.assertEqual((job/'entrada/problema.txt').read_bytes(),b'ejercicio')
        return 0,'Pregunta 1: 4\n'

    def peer(self,engine=None):
        peer=Peer(self.home,engine or self.engine);self.peers.append(peer);return peer

    def test_password_is_checked_before_upload_or_engine(self):
        peer=self.peer();self.assertEqual(peer.login(password='mala')['tipo'],'rechazado')
        peer.thread.join(3)
        self.assertEqual(self.jobs,[])
        self.assertFalse((self.home/'trabajos').exists())

    def test_operation_allowlist_and_shell_injection_rejected(self):
        for mode in ('limpiar','revisar;whoami','powershell','../generar'):
            peer=self.peer();self.assertEqual(peer.login(mode)['tipo'],'error')
        self.assertEqual(self.jobs,[])

    def test_received_processed_returned_and_removed(self):
        peer=self.peer();ready=peer.login();self.assertEqual(ready['tipo'],'listo')
        peer.file();events=peer.finish(ready['trabajo']);peer.thread.join(3)
        self.assertIn('Pregunta 1: 4',''.join(e.get('texto','') for e in events if e))
        self.assertEqual(events[-1]['tipo'],'cerrado')
        self.assertEqual(peer.result,0)
        self.assertFalse(self.jobs[0].exists())

    def test_busy_and_jobs_never_mix(self):
        first=self.peer();one=first.login()
        second=self.peer();self.assertEqual(second.login()['tipo'],'ocupado')
        self.assertEqual(self.jobs,[])
        first.file();first.finish(one['trabajo']);first.thread.join(3)
        third=self.peer();two=third.login();third.file();third.finish(two['trabajo']);third.thread.join(3)
        self.assertNotEqual(one['trabajo'],two['trabajo'])
        self.assertEqual(len(self.jobs),2)
        self.assertFalse(any((self.home/'trabajos').iterdir()))

    def test_probe_authenticates_without_work_or_ai(self):
        peer=self.peer();self.assertEqual(peer.login(probe=True)['tipo'],'disponible')
        self.assertEqual(self.jobs,[])

    def test_disconnect_cleans_job_and_unlocks(self):
        peer=self.peer();ready=peer.login();peer.writer.close();peer.thread.join(3)
        self.assertEqual(peer.result,4)
        self.assertFalse((self.home/'trabajos'/ready['trabajo']).exists())
        with exclusive(self.home):pass
        self.assertTrue((self.home/'config.json').exists())

    @unittest.skipIf(os.name=='nt','Requiere verificar taskkill en Windows')
    def test_disconnect_during_computation_cancels_child_and_cleans(self):
        real_popen=subprocess.Popen
        started=threading.Event();children=[]
        def launch(command,**kwargs):
            child=real_popen([sys.executable,'-c','import time;time.sleep(30)'],**kwargs)
            children.append(child);started.set();return child
        with patch('servidor.worker.subprocess.Popen',side_effect=launch):
            peer=self.peer(worker.run_engine);ready=peer.login();peer.file();peer.send({'tipo':'fin_envio'})
            self.assertTrue(started.wait(3))
            peer.writer.close();peer.thread.join(5)
        self.assertEqual(peer.result,4)
        self.assertIsNotNone(children[0].poll())
        self.assertFalse((self.home/'trabajos'/ready['trabajo']).exists())
        with exclusive(self.home):pass

    def test_corrupt_transfer_never_starts_engine(self):
        peer=self.peer();peer.login();peer.file(wrong_hash=True)
        self.assertEqual(peer.get()['tipo'],'error');peer.thread.join(3)
        self.assertEqual(self.jobs,[])
        self.assertFalse(any((self.home/'trabajos').iterdir()))

    def test_reference_directory_cannot_be_uploaded(self):
        peer=self.peer();peer.login()
        peer.send({'tipo':'archivo','ruta':'referencias_clase/a.pdf','bytes':0,'sha256':hashlib.sha256(b'').hexdigest()})
        self.assertEqual(peer.get()['tipo'],'error')
        self.assertEqual(self.jobs,[])

    @unittest.skipUnless(shutil.which('octave-cli') or shutil.which('octave'),'Octave no disponible')
    def test_real_engine_excel_octave_transferred_with_ai_double(self):
        def engine(mode,job,home,channel):
            self.jobs.append(job)
            q=question();q['requiere_captura']=False
            def answer(root,prompt,schema,images=()):
                return work(q) if schema is codex.WORK else {'preguntas':[{'numero':'1','correcta':True,'captura_legible':False,'observaciones':[]}]}
            terminal=io.StringIO()
            with patch('src.codex.invoke',side_effect=answer),contextlib.redirect_stdout(terminal):
                code=main.run(mode,job,academic_root=home)
            return code,terminal.getvalue()
        peer=self.peer(engine);ready=peer.login('generar');peer.file();events=peer.finish(ready['trabajo']);peer.thread.join(3)
        headers=[e for e in events if e and e['tipo']=='archivo']
        self.assertTrue(any(e['ruta'].endswith('.xlsx') for e in headers))
        self.assertTrue(any(e['ruta'].endswith('.m') for e in headers))
        self.assertTrue(any(e['ruta'].endswith('.salida.txt') for e in headers))
        self.assertFalse(any('referencias_clase' in e['ruta'] for e in headers))
        for index,event in enumerate(events):
            if event and event['tipo']=='archivo':
                content=b''
                for data in events[index+1:]:
                    if data['tipo']=='fin_archivo':break
                    content+=base64.b64decode(data['base64'])
                self.assertEqual(hashlib.sha256(content).hexdigest(),event['sha256'])
        self.assertEqual(peer.result,0)


class SafetyTests(unittest.TestCase):
    def test_forced_ssh_rejects_arbitrary_original_command(self):
        with patch.dict(os.environ,{'SSH_CONNECTION':'private connection','SSH_ORIGINAL_COMMAND':'powershell -Command whoami'}), patch('sys.argv',['worker']), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(worker.main(),1)
        self.assertIn('Comando SSH no permitido',output.getvalue())

    def test_paths(self):
        for name in ('../personal.txt','entrada/../../a.pdf','/a.m','C:/a.m','entrada\\a.m','entrada/CON.pdf','entrada/.oculto.txt','entrada/x.exe'):
            with self.assertRaises(ValueError):safe_path(name,{'entrada'})
        self.assertEqual(str(safe_path('entrada/sub/pregunta.pdf',{'entrada'})),os.path.join('entrada','sub','pregunta.pdf'))

    def test_salted_server_password_no_plaintext(self):
        a=password_record('prueba');b=password_record('prueba')
        self.assertNotEqual(a['verificador'],b['verificador'])
        self.assertNotIn('prueba',json.dumps(a))
        self.assertTrue(authorized('prueba',a));self.assertFalse(authorized('otra',a))

    @unittest.skipIf(os.name=='nt','Validación de grupo POSIX; Windows requiere taskkill en máquina de prueba')
    def test_disconnect_terminates_real_process_group(self):
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
        worker.stop_tree(process)
        self.assertIsNotNone(process.poll())

    def test_migration_preserves_originals_until_full_verification(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'origen';dest=root/'privado'
            source.mkdir();dest.mkdir()
            (source/'a.pdf').write_bytes(b'a');(source/'b.xlsx').write_bytes(b'b')
            (dest/'b.xlsx').write_bytes(b'diferente')
            with self.assertRaises(ValueError):copy_verified(source,dest,remove=True)
            self.assertTrue((source/'a.pdf').exists());self.assertTrue((source/'b.xlsx').exists())
            (dest/'b.xlsx').unlink()
            self.assertEqual(copy_verified(source,dest,remove=True),2)
            self.assertEqual((dest/'a.pdf').read_bytes(),b'a')
            self.assertEqual(list(source.iterdir()),[])

    def test_private_setup_idempotent_and_outside_repo(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);repo=root/'repo';repo.mkdir();fixture(repo)
            home=root/'privado'
            initialize(home,password='prueba',repo=repo)
            one=json.loads((home/'config.json').read_text())['autenticacion']
            initialize(home,repo=repo)
            self.assertEqual(one,json.loads((home/'config.json').read_text())['autenticacion'])
            self.assertTrue((repo/'.servidor.local').exists())
            with self.assertRaises(ValueError):initialize(repo/'inseguro',password='prueba',repo=repo)


class ReferenceTests(unittest.TestCase):
    def test_wrong_arithmetic_downgrades_validation(self):
        data=reference();data['ejercicios'][0]['comprobaciones'][0]['esperado']=99
        exercises,rules=memoria.verify_review(data,'referencias_clase/ejemplo.md')
        self.assertEqual(exercises[0]['clasificacion'],'PENDIENTE')
        self.assertEqual([r['categoria'] for r in rules],['estilo_excel'])

    @unittest.skipUnless(shutil.which('octave-cli') or shutil.which('octave'),'Octave no disponible')
    def test_incorrect_reference_only_contributes_style(self):
        data=reference('INCORRECTA')
        exercises,rules=memoria.verify_review(data,'referencias_clase/ejemplo.md')
        self.assertEqual(exercises[0]['clasificacion'],'INCORRECTA')
        self.assertEqual([r['categoria'] for r in rules],['estilo_excel'])
        item={'registro':{'contenido':'2+2=5 ERROR','imagenes':['incorrecta.png']},'ejercicios':exercises,'reglas':rules}
        sanitized=memoria.authority_record(item)
        self.assertNotIn('2+2=5',sanitized['contenido']);self.assertEqual(sanitized['imagenes'],[])

    @unittest.skipUnless((ROOT/'referencias_clase/MetodosNumericosGabriela.xlsx').exists() and (shutil.which('octave-cli') or shutil.which('octave')), 'Requiere el material original privado y Octave')
    def test_real_lagrange_reference_error_and_correction(self):
        from openpyxl import load_workbook
        from src.verificacion import FormulaBook
        source=ROOT/'referencias_clase/MetodosNumericosGabriela.xlsx'
        original=hashlib.sha256(source.read_bytes()).hexdigest()
        book=load_workbook(source);sheet=book['Hoja1'];calc=FormulaBook(sheet)
        before=calc.value('O16')
        x=sheet['P5'].value;nodes=[sheet[f'O{r}'].value for r in (7,8,9,10)]
        a,b,c,d=nodes
        corrected=f'(({x}-{a})*({x}-{c})*({x}-{d}))/(({b}-{a})*({b}-{c})*({b}-{d}))'
        error_expression=f'(({x}-{a})*({x}-{c})*({x}-{d}))/(({b}-{a})*({b}-{c})*({d}))'
        data=reference('INCORRECTA');exercise=data['ejercicios'][0]
        exercise['localizacion']='Hoja1 O16'
        exercise['enunciado']='Lagrange grado 3, nodos '+str(nodes)+', x='+str(x)
        exercise['errores']=[{'ubicacion':'Hoja1 O16','formula_incorrecta':sheet['O16'].value,
            'correccion':'Producto de diferencias respecto del nodo de L1', 'evidencia':'La suma original de bases no es 1',
            'comprobacion_error':{'expresion_original':error_expression,'valor_documentado':before,
              'expresion_corregida':corrected,'valor_corregido':0.5625,'tolerancia':1e-8}}]
        exercise['comprobaciones']=[{'nombre':'Base corregida L1','expresion':corrected,'esperado':0.5625,'tolerancia':1e-8}]
        exercise['octave']='incorrecta = '+error_expression+'\ncorrecta = '+corrected+'\n'
        exercise['salidas']=[{'variable':name,'valores':[value],'celdas':[],'tolerancia':1e-8} for name,value in [('incorrecta',before),('correcta',0.5625)]]
        exercises,rules=memoria.verify_review(data,'referencias_clase/ejemplo.md')
        self.assertEqual(exercises[0]['clasificacion'],'INCORRECTA')
        self.assertEqual([r['categoria'] for r in rules],['estilo_excel'])
        book.close()
        self.assertEqual(original,hashlib.sha256(source.read_bytes()).hexdigest())

    def test_legacy_rules_invalidated_even_when_codex_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root);(root/'.mn_cache').mkdir()
            (root/'referencias_clase/ejemplo.md').write_text('No asumir correcto')
            (root/'.mn_cache/referencias.json').write_text(json.dumps({'referencias_clase/ejemplo.md':{'sha256':'old','reglas':[{'categoria':'metodos','regla':'2+2=5'}]}}))
            p=root/'perfil_academico/metodos.md';p.write_text(p.read_text()+'\n'+memoria.START+'\n2+2=5\n'+memoria.END)
            with patch('src.memoria.invoke',side_effect=RuntimeError('sin conexión')):
                with self.assertRaises(RuntimeError):memoria.academic(root,root)
            self.assertNotIn('2+2=5',p.read_text())
            self.assertTrue((root/'.mn_cache/reglas_anteriores_sin_validar.json').exists())


if __name__=='__main__':unittest.main()
