"""Alta privada: identidades documentadas, revocaciones y configuración. Sin fingir Serve real."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from email.message import Message
import io
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

LINUX=os.name=='posix'
if LINUX:
    from servidor import enrolamiento as alta
    from servidor.preparar_automatico import settings_from_status,unit_text,configure_serve
    from servidor.preparar import configure_ssh


def key(index=1):
    blob=struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',32)+bytes([index])*32
    return 'ssh-ed25519 '+base64.b64encode(blob).decode()+' equipo'


def headers():
    m=Message()
    m['X-Forwarded-For']='100.90.1.2'
    m['X-Forwarded-Proto']='https'
    m['Tailscale-User-Login']='owner@example.test'
    return m


def whois():
    # Campos de tailcfg.Node / apitype.WhoIsResponse; nunca enviados por el cliente.
    return {'Node':{'StableID':'nowner1','User':123,'Name':'pc.tail.test.ts.net.',
                    'Addresses':['100.90.1.2/32','fd7a:115c:a1e0::1/128'],'Tags':[]},
            'UserProfile':{'ID':123,'LoginName':'owner@example.test'}}


@unittest.skipUnless(LINUX,'El backend automático es Unix/Ubuntu')
class IdentityTests(unittest.TestCase):
    def test_real_fields_resolved_through_whois(self):
        with patch('servidor.enrolamiento.tail_json',return_value=whois()) as api:
            peer=alta.identity(headers(),{'owner_user_id':'123'})
        api.assert_called_once_with('whois','--json','100.90.1.2')
        self.assertEqual(peer['node_id'],'nowner1')
        self.assertEqual(peer['addresses'],['100.90.1.2','fd7a:115c:a1e0::1'])

    def test_other_owner_tagged_mismatch_and_unlisted_node_rejected(self):
        variants=[]
        a=whois();a['UserProfile']['ID']=999;variants.append(a)
        a=whois();a['Node']['Tags']=['tag:server'];variants.append(a)
        a=whois();a['UserProfile']['LoginName']='forged@example.test';variants.append(a)
        a=whois();a['Node']['Addresses']=['100.90.1.3/32'];variants.append(a)
        a=whois();del a['Node']['StableID'];variants.append(a)
        for data in variants:
            with self.subTest(data=data),self.assertRaises(alta.Denied):
                alta.identity(headers(),{'owner_user_id':'123'},lambda *a:data)
        with self.assertRaises(alta.Denied):
            alta.identity(headers(),{'owner_user_id':'123','allowed_nodes':['not-this-node']},lambda *a:whois())

    def test_headers_alone_or_funnel_cannot_authorize(self):
        for modify in ('missing','duplicate','funnel','plain','spoofed-chain'):
            h=headers()
            if modify=='missing':del h['Tailscale-User-Login']
            elif modify=='duplicate':h['Tailscale-User-Login']='attacker'
            elif modify=='funnel':h['Tailscale-Funnel-Request']='?1'
            elif modify=='plain':h.replace_header('X-Forwarded-Proto','http')
            else:h.replace_header('X-Forwarded-For','100.90.1.2, 100.90.1.3')
            with self.subTest(modify=modify),self.assertRaises(alta.Denied):alta.identity(h,{'owner_user_id':'123'},lambda *a:whois())
        def unavailable(*args):raise OSError('LocalAPI no accesible')
        with self.assertRaises(alta.Denied):alta.identity(headers(),{'owner_user_id':'123'},unavailable)

    def test_binary_ed25519_not_just_prefix(self):
        canonical,fp=alta.public_key(key())
        self.assertEqual(canonical.split()[0],'ssh-ed25519');self.assertTrue(fp.startswith('SHA256:'))
        for value in ('ssh-ed25519 invalid!', 'ssh-rsa AAAA', 'command="sh" '+key(),key()+'\n'+key(), 'ssh-ed25519 '+base64.b64encode(b'ssh-ed25519'+b'x'*32).decode()):
            with self.subTest(value=value),self.assertRaises(alta.Denied):alta.public_key(value)


@unittest.skipUnless(LINUX,'Backend Unix')
class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        (self.home/'ssh').mkdir();self.registry=alta.Registry(self.home)
        self.peer={'node_id':'nowner1','user_id':'123','addresses':['100.90.1.2']}
    def tearDown(self):self.temp.cleanup()

    def test_idempotent_add_permissions_and_revoke(self):
        fp=self.registry.enroll(self.peer,key())
        self.assertEqual(fp,self.registry.enroll(self.peer,key()))
        text=self.registry.keys.read_text()
        self.assertEqual(text.count('metodos-nowner1'),1)
        self.assertIn('restrict,from="100.90.1.2/32"',text)
        self.assertEqual(stat.S_IMODE(self.registry.path.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(self.registry.keys.stat().st_mode),0o600)
        self.registry.revoke('nowner1')
        self.assertNotIn(alta.public_key(key())[0],self.registry.keys.read_text())
        for value in (key(),key(2)):
            with self.assertRaises(alta.Denied):self.registry.enroll(self.peer,value)
        with self.assertRaises(alta.Denied):self.registry.check(self.peer)

    def test_key_cannot_move_to_other_device_and_legacy_is_preserved(self):
        legacy=alta.public_key(key(9))[0]+' previo\n'
        self.registry.keys.write_text(legacy)
        self.registry.enroll(self.peer,key())
        other={**self.peer,'node_id':'nother'}
        with self.assertRaises(alta.Denied):self.registry.enroll(other,key())
        with self.assertRaises(alta.Denied):self.registry.enroll(self.peer,key(9))
        self.registry.revoke('nowner1')
        self.assertTrue(self.registry.keys.read_text().startswith(legacy))

    def test_parallel_requests_do_not_lose_authorizations(self):
        def add(i):return self.registry.enroll({**self.peer,'node_id':'nowner'+str(i)},key(i))
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(add,range(1,13)))
        self.assertEqual(len(self.registry.load()['keys']),12)
        self.assertEqual(self.registry.keys.read_text().count('restrict,from='),12)

    def test_http_accepts_only_key_and_rejects_commands(self):
        alta.atomic_json(self.home/'alta_config.json',{'owner_user_id':'123'})
        request=alta.Handler.__new__(alta.Handler)
        request.server=SimpleNamespace(home=self.home)
        request.path='/metodos-alta/enrolar';request.headers=headers()
        body=json.dumps({'clave_publica':key(),'comando':'whoami'}).encode()
        request.headers['Content-Length']=str(len(body));request.rfile=io.BytesIO(body)
        replies=[];request.respond=lambda status,data:replies.append((status,data))
        with patch('servidor.enrolamiento.tail_json',return_value=whois()):request.handle_action(True)
        self.assertEqual(replies[0][0],403);self.assertFalse(self.registry.path.exists())

    def test_http_success_and_revoked_info_rejection(self):
        alta.atomic_json(self.home/'alta_config.json',{'owner_user_id':'123','server_ip':'100.116.157.0','ssh_user':'owner'})
        (self.home/'ssh/host_ed25519.pub').write_text(key(22))
        request=alta.Handler.__new__(alta.Handler);request.server=SimpleNamespace(home=self.home)
        request.path='/enrolar';request.headers=headers()
        body=json.dumps({'clave_publica':key()}).encode()
        request.headers['Content-Length']=str(len(body));request.rfile=io.BytesIO(body)
        replies=[];request.respond=lambda status,data:replies.append((status,data))
        with patch('servidor.enrolamiento.tail_json',return_value=whois()):request.handle_action(True)
        self.assertEqual(replies[-1][0],200)
        self.assertEqual(replies[-1][1]['servidor'],'100.116.157.0')
        self.assertNotIn('clave_privada',replies[-1][1])
        self.registry.revoke('nowner1');request.path='/info'
        with patch('servidor.enrolamiento.tail_json',return_value=whois()):request.handle_action(False)
        self.assertEqual(replies[-1][0],403)


@unittest.skipUnless(LINUX,'Configuración Ubuntu')
class ConfigurationTests(unittest.TestCase):
    def test_owner_derived_from_actual_status_and_expected_ip(self):
        status={'BackendState':'Running','TailscaleIPs':['100.116.157.0'],
                'Self':{'UserID':123,'DNSName':'home.tail123.ts.net.','Tags':[]}}
        settings=settings_from_status(status,'100.116.157.0')
        self.assertEqual(settings['owner_user_id'],'123')
        for field,value in [('BackendState','Stopped'),('TailscaleIPs',['100.1.1.1'])]:
            bad=deepcopy(status);bad[field]=value
            with self.assertRaises(ValueError):settings_from_status(bad,'100.116.157.0')

    def test_units_preserve_path_and_restart_without_open_terminal(self):
        text=unit_text('Metodos alta privada',['/venv/python','-m','servidor.enrolamiento'],'/repo','/nvm/bin:/usr/bin')
        self.assertIn('WantedBy=default.target',text);self.assertIn('Restart=on-failure',text)
        self.assertIn('Environment="PATH=/nvm/bin:/usr/bin"',text)
        self.assertNotIn('0.0.0.0',text)

    def test_serve_does_not_reset_or_replace_other_app(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)
            with patch('servidor.preparar_automatico.tail_json',return_value={'Web':{'host:443':{'Handlers':{'/metodos-alta':{'Proxy':'http://another-app'}}}}}),patch('servidor.preparar_automatico.subprocess.run') as command:
                with self.assertRaises(ValueError):configure_serve(home)
                command.assert_not_called()

    @unittest.skipUnless(shutil.which('sshd') or Path('/usr/sbin/sshd').exists(),'OpenSSH Server no instalado')
    def test_real_sshd_syntax_accepts_initial_empty_keys(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);(home/'ssh').mkdir()
            with patch('servidor.preparar.tailscale_ip',return_value='100.116.157.0'):
                _,config,_=configure_ssh(home,Path('/usr/bin/python3'),None,allow_empty=True)
            self.assertEqual((home/'ssh/authorized_keys').read_text(),'')
            text=config.read_text()
            self.assertIn('ListenAddress 100.116.157.0',text)
            self.assertIn('Port 2222',text);self.assertIn('PasswordAuthentication no',text)
            self.assertNotIn('0.0.0.0',text)



# Compilar los scripts requiere PowerShell, pero no instala nada ni conecta con la laptop.
PS=shutil.which('pwsh') or shutil.which('powershell')
@unittest.skipUnless(PS,'PowerShell no disponible para validar parser e interfaz nativos')
class PowerShellSyntaxTests(unittest.TestCase):
    def test_bootstrap_auto_and_installer_parameters(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/'parse.ps1'
            paths=[root/'inicio.ps1',root/'cliente/auto.ps1',root/'cliente/instalar.ps1']
            literals=','.join("'"+str(p).replace("'","''")+"'" for p in paths)
            script.write_text("$ErrorActionPreference='Stop'\nforeach ($p in @("+literals+")) { $tokens=$null; $errors=$null; [void][Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors); if ($errors.Count) { throw ($errors | Out-String) } }\n$cmd=Get-Command '"+str(paths[-1]).replace("'","''")+"'\nforeach ($p in @('SinPrueba','PreparacionAutomatica','SoloPreparar')) { if (-not $cmd.Parameters.ContainsKey($p)) { throw ('Parametro inexistente: '+$p) } }\n",encoding='utf-8')
            result=subprocess.run([PS,'-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
