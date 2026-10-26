"""Ejecuciones reales de Octave y captura opcional de su ventana en Windows."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from .verificacion import close

MARK = '__MN_RESULTADO__'


def executable():
    override = os.environ.get('METODOS_OCTAVE')
    if override:
        path = Path(override)
        if not path.is_file():
            raise ValueError('METODOS_OCTAVE no apunta a un ejecutable')
        return str(path)
    for name in ('octave-cli', 'octave', 'octave-cli.exe', 'octave.exe'):
        found = shutil.which(name)
        if found:
            return found
    if os.name == 'nt':
        for base in ('C:/Program Files/GNU Octave', 'C:/Program Files'):
            for path in sorted(Path(base).glob('Octave*/mingw64/bin/octave-cli.exe'), reverse=True):
                return str(path)
    raise RuntimeError('Falta GNU Octave. Instalar y añadir su carpeta bin al PATH; ver README.')


def vet(code):
    # Filtro preventivo, no se presenta como un sandbox de seguridad de Octave.
    forbidden = r'\b(system|unix|dos|eval|evalin|feval|builtin|str2func|fopen|fclose|fwrite|fprintf_file|save|load|delete|unlink|rmdir|mkdir|movefile|copyfile|cd|chdir|addpath|path|source|run|java\w*|python|popen\w*|url\w*|web\w*|input|keyboard|quit|exit|diary|imwrite|print|dlmwrite|csvwrite|xlswrite|fdisp|setenv|getenv)\b'
    if len(code) > 100000:
        raise ValueError('Script demasiado grande')
    checked = []
    for line in code.splitlines():
        if re.search(r'\bpkg\b', line, re.I):
            if not re.fullmatch(r'\s*pkg\s+load\s+[a-zA-Z][\w]*\s*;?\s*', line):
                raise ValueError('Sólo se permite pkg load de paquetes ya instalados')
        else:
            checked.append(line)
    filtered = '\n'.join(checked)
    if re.search(forbidden, filtered, re.I) or re.search(r'^\s*!', filtered, re.M):
        raise ValueError('Script requiere instrucciones fuera del subconjunto matemático automático; conservar para revisión manual')


def run(code, outputs=(), plot_dir=None, timeout=90):
    vet(code)
    fields = []
    for out in outputs:
        name = out['variable']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
            raise ValueError('Variable Octave inválida')
        fields.append(f"'{name}', {name}(:).' ")
    payload = 'struct(' + ', '.join(fields) + ')'
    tail = f"\nprintf('\\n{MARK}%s\\n', jsonencode({payload}));\n"
    if plot_dir:
        # Sólo el wrapper, nunca el modelo, decide los archivos escritos.
        folder = str(Path(plot_dir).resolve()).replace("'", "''").replace('\\', '/')
        tail += f"mn_figs = findall(0, 'type', 'figure');\nfor mn_i = 1:numel(mn_figs)\nprint(mn_figs(mn_i), sprintf('{folder}/grafica_%02d.png', mn_i), '-dpng');\nendfor\n"
    with tempfile.TemporaryDirectory(prefix='mn_octave_') as d:
        script = Path(d) / 'ejecutar.m'
        script.write_text("set(0, 'defaultfigurevisible', 'off');\n" + code + tail, encoding='utf-8')
        try:
            process = subprocess.run([executable(), '--no-gui', '--no-init-file', '--no-site-file', '--quiet', str(script)],
                                     cwd=d, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError('Octave excedió el tiempo permitido') from e
    log = process.stdout + process.stderr
    if process.returncode:
        raise RuntimeError('Octave falló:\n' + log[-3000:])
    matches = re.findall(re.escape(MARK) + r'([^\r\n]+)', process.stdout)
    if not matches:
        raise ValueError('Octave no produjo datos de verificación')
    actual = json.loads(matches[-1])
    for out in outputs:
        values = actual.get(out['variable'])
        if isinstance(values, (int, float)):
            values = [values]
        if not isinstance(values, list) or len(values) != len(out['valores']):
            raise ValueError('Dimensión Octave incorrecta: ' + out['variable'])
        for a, b in zip(values, out['valores']):
            if type(a) not in (int, float) or not close(a, b, out['tolerancia']):
                raise ValueError('Resultado Octave distinto: ' + out['variable'])
    return "CODIGO_SALIDA_OCTAVE: 0\n" + log


def capture(root, script, target):
    if os.name != 'nt':
        return False, 'Captura pendiente: requiere escritorio interactivo Windows.'
    if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
        return False, 'Captura pendiente: sesión SSH sin escritorio utilizable.'
    shell = shutil.which('powershell') or shutil.which('pwsh')
    if not shell:
        return False, 'Captura pendiente: PowerShell no disponible.'
    binary = Path(executable())
    candidates = [binary.parent / 'octave-gui.exe', binary.parent / 'octave.exe']
    gui = next((p for p in candidates if p.is_file()), None)
    if not gui:
        return False, 'Captura pendiente: ejecutable gráfico de Octave ausente.'
    try:
        p = subprocess.run([shell, '-NoProfile', '-File', str(Path(__file__).resolve().parents[1] / 'sistema' / 'capturar.ps1'),
                            '-Octave', str(gui), '-Script', str(script.resolve()), '-Destino', str(target.resolve())],
                           capture_output=True, text=True, timeout=45)
        if p.returncode == 0 and target.is_file():
            return True, 'Captura real guardada; revisar visualmente que muestre comandos y resultados completos.'
        return False, 'Captura pendiente: ' + (p.stderr or p.stdout)[-500:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, 'Captura pendiente: ' + str(e)
