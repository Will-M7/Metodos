"""Opt-in para entornos externos reales. No confundir pipes locales con cifrado SSH."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PS=shutil.which('powershell') or shutil.which('pwsh')
WINDOWS=os.name=='nt' and bool(PS)


@unittest.skipUnless(WINDOWS and os.environ.get('METODOS_VM_LIMPIA')=='1',
                     'Requiere VM Windows limpia y autorización interactiva de UAC/Tailscale')
class CleanWindowsTests(unittest.TestCase):
    def test_install_and_idempotent_reuse(self):
        command=[PS,'-NoProfile','-File',str(ROOT/'instalar.ps1'),'-SoloPreparar']
        self.assertEqual(subprocess.run(command).returncode,0)
        key=ROOT/'.cliente/id_ed25519'
        previous=key.read_bytes()
        self.assertEqual(subprocess.run(command).returncode,0)
        self.assertEqual(previous,key.read_bytes())
        # El cliente nunca importa ni instala los motores del servidor.
        self.assertTrue((ROOT/'.cliente/propiedad.json').exists())


@unittest.skipUnless(WINDOWS and os.environ.get('METODOS_PROBAR_REMOTO')=='1',
                     'Requiere cliente Windows enrolado, laptop accesible y contraseña en entorno privado')
class RealSSHTests(unittest.TestCase):
    def test_encrypted_ssh_and_remote_authorization(self):
        self.assertTrue(os.environ.get('METODOS_CLAVE_PRUEBA'))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'probe.ps1'
            path.write_text(". '"+str(ROOT/'cliente/comun.ps1').replace("'","''")+"'\nfunction Read-Host { ConvertTo-SecureString $env:METODOS_CLAVE_PRUEBA -AsPlainText -Force }\nexit (Invoke-Metodos -Modo respuestas -Comprobar)\n",encoding='utf-8')
            result=subprocess.run([PS,'-NoProfile','-File',str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('autorizacion remota comprobada',result.stdout)

    @unittest.skipUnless(os.environ.get('METODOS_HOST_APAGADO'), 'Requiere IP privada de una laptop de prueba apagada')
    def test_offline_laptop_connection_fails(self):
        host=os.environ['METODOS_HOST_APAGADO']
        import ipaddress
        self.assertIn(ipaddress.ip_address(host),ipaddress.ip_network('100.64.0.0/10'))
        result=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=3','-p','2222',host,'metodos-v1'],capture_output=True,text=True,timeout=15)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('connect to host',result.stderr)

    def test_remote_wrong_password_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'probe.ps1'
            path.write_text(". '"+str(ROOT/'cliente/comun.ps1').replace("'","''")+"'\nfunction Read-Host { ConvertTo-SecureString ('incorrecta-'+[guid]::NewGuid()) -AsPlainText -Force }\ntry { Invoke-Metodos -Modo respuestas -Comprobar; exit 0 } catch { exit 1 }\n",encoding='utf-8')
            self.assertNotEqual(subprocess.run([PS,'-NoProfile','-File',str(path)],capture_output=True,timeout=60).returncode,0)



@unittest.skipUnless(WINDOWS and os.environ.get('METODOS_PROBAR_ALTA')=='1',
                     'Requiere Windows propietario en la tailnet y Serve HTTPS real configurado')
class AutomaticEnrollmentTests(unittest.TestCase):
    def test_auto_enroll_fingerprint_and_no_token_probe(self):
        self.assertTrue(os.environ.get('METODOS_CLAVE_PRUEBA'))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'auto-real.ps1'
            path.write_text("function global:Read-Host { ConvertTo-SecureString $env:METODOS_CLAVE_PRUEBA -AsPlainText -Force }\n& '"+str(ROOT/'cliente/auto.ps1').replace("'","''")+"'\nexit $LASTEXITCODE\n",encoding='utf-8')
            result=subprocess.run([PS,'-NoProfile','-File',str(path)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
