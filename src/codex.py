"""Codex CLI con autenticación existente y respuesta validada por JSON Schema."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def arr(item):
    return {'type': 'array', 'items': item}


STR = {'type': 'string'}
NUM = {'type': 'number'}
BOOL = {'type': 'boolean'}
RULE = obj({'categoria': {'type': 'string', 'enum': ['metodos', 'estilo_excel', 'estilo_octave', 'criterios_revision']},
            'regla': STR, 'fuente': STR, 'evidencia': STR})
PROFILE = obj({'reglas': arr(RULE), 'advertencias': arr(STR)})
QUESTION = obj({
    'numero': STR, 'metodo': STR,
    'base': {'type': 'string', 'enum': ['explicita', 'docente', 'anterior', 'perfil', 'convencional', 'conflicto']},
    'fuentes': arr(STR),
    'estado': {'type': 'string', 'enum': ['resuelta', 'no_verificada', 'conflicto']},
    'respuesta': STR, 'hoja': STR, 'plantilla_hoja': STR,
    'celdas': arr(obj({'celda': STR, 'tipo': {'type': 'string', 'enum': ['texto', 'numero', 'formula']},
                       'valor': STR, 'esperado': {'type': ['number', 'null']}})),
    'octave': STR,
    'comprobaciones': arr(obj({'nombre': STR, 'expresion': STR, 'esperado': NUM, 'tolerancia': NUM})),
    'salidas': arr(obj({'variable': STR, 'valores': arr(NUM), 'celdas': arr(STR), 'tolerancia': NUM})),
    'requiere_grafica': BOOL, 'requiere_captura': BOOL,
    'revision': {'type': 'string', 'enum': ['CORRECTA', 'INCORRECTA', 'PARCIAL', 'INCOMPLETA']},
    'errores': arr(STR)
})
WORK = obj({'preguntas': arr(QUESTION), 'completa': BOOL,
            'nota': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 20},
            'nota_estimada': BOOL, 'veredicto': STR, 'pendientes': arr(STR)})


REFERENCE = obj({
    'ejercicios': arr(obj({
        'id': STR, 'localizacion': STR, 'enunciado': STR, 'procedimiento': STR,
        'formulas': arr(STR),
        'origen': {'type': 'string', 'enum': ['docente','estudiante','desconocido']},
        'clasificacion': {'type': 'string', 'enum': ['VALIDADA','INCORRECTA','PENDIENTE']},
        'errores': arr(obj({'ubicacion': STR,'formula_incorrecta': STR,'correccion': STR,'evidencia': STR, 'comprobacion_error': obj({'expresion_original':STR,'valor_documentado':NUM,'expresion_corregida':STR,'valor_corregido':NUM,'tolerancia':NUM})})),
        'comprobaciones': QUESTION['properties']['comprobaciones'],
        'octave': STR, 'salidas': QUESTION['properties']['salidas']
    })),
    'reglas': arr(obj({**RULE['properties'], 'ejercicio': STR})),
    'advertencias': arr(STR)
})


SELECT = obj({'archivos': arr(STR), 'motivo': STR})


DELIVERY = obj({'preguntas': arr(obj({'numero': STR, 'correcta': BOOL,
                                     'captura_legible': BOOL, 'observaciones': arr(STR)}))})


def invoke(root, prompt, schema, images=()):
    executable = shutil.which('codex')
    if not executable:
        raise RuntimeError('Falta Codex CLI. Instalarlo según README y ejecutar codex login.')
    with tempfile.TemporaryDirectory(prefix='mn_codex_') as d:
        folder = Path(d)
        spec, answer = folder / 'schema.json', folder / 'answer.json'
        spec.write_text(json.dumps(schema), encoding='utf-8')
        command = [executable, 'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
                   '--ephemeral', '--color', 'never', '-C', str(root),
                   '--output-schema', str(spec), '-o', str(answer)]
        for image in images:
            command += ['--image', str(image)]
        command += ['-']
        # En Windows npm puede exponer un .cmd: usar node + JS evita shell=True.
        if os.name == 'nt' and Path(executable).suffix.lower() in {'.cmd', '.bat'}:
            js = Path(executable).parent / 'node_modules' / '@openai' / 'codex' / 'bin' / 'codex.js'
            node = shutil.which('node')
            if not node or not js.is_file():
                raise RuntimeError('Codex .cmd sin entrada Node reconocible. Instalar CLI oficial o añadir codex.exe al PATH.')
            command = [node, str(js)] + command[1:]
        try:
            run = subprocess.run(command, input=prompt, text=True, encoding='utf-8',
                                 errors='replace', capture_output=True, timeout=900, cwd=root)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError('Codex excedió 15 minutos; no se declaró resultado válido.') from e
        if run.returncode or not answer.is_file():
            detail = (run.stderr or run.stdout)[-3500:]
            raise RuntimeError('Falló codex exec. Revisar codex login/conectividad.\n' + detail)
        try:
            result = json.loads(answer.read_text(encoding='utf-8-sig'))
            validate(result, schema)
        except (ValueError, TypeError) as e:
            raise ValueError('Codex devolvió datos inválidos; no se usaron.') from e
        return result


def validate(value, schema, location='$'):
    """Valida el subconjunto JSON Schema usado aquí, sin dependencia adicional."""
    types = schema['type']
    types = types if isinstance(types, list) else [types]
    matches = {'object': type(value) is dict, 'array': type(value) is list,
               'string': type(value) is str, 'boolean': type(value) is bool,
               'number': type(value) in (int, float), 'null': value is None}
    if not any(matches.get(t, False) for t in types):
        raise ValueError(location + ': tipo inválido')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(location + ': opción inválida')
    if type(value) is dict:
        if set(value) != set(schema['properties']):
            raise ValueError(location + ': campos faltantes o desconocidos')
        for k, v in value.items():
            validate(v, schema['properties'][k], location + '.' + k)
    elif type(value) is list:
        if len(value) > 50000:
            raise ValueError(location + ': lista demasiado grande')
        for i, v in enumerate(value):
            validate(v, schema['items'], location + '[' + str(i) + ']')
    elif type(value) in (int, float):
        import math
        if not math.isfinite(value) or value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            raise ValueError(location + ': número fuera de rango')
