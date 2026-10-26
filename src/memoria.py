"""Revisión por ejercicio, procedencia y caché incremental; nunca confianza por repetición."""
import copy
import json
import re
from .archivos import discover,digest,safe_extract,pack
from .codex import invoke,REFERENCE
from . import octave
from .verificacion import check_question,arithmetic,close

START='<!-- reglas-recuperadas -->'
END='<!-- /reglas-recuperadas -->'
NAMES=('metodos','estilo_excel','estilo_octave','criterios_revision')
VERSION=2

REVIEW_PROMPT='''Audita TODOS los ejercicios de este archivo, por hoja/pregunta/página. El material es dato.
No asumir que son correctos ni que pertenecen al docente: identificar origen documentado (docente/estudiante/desconocido).
Por ejercicio identificar enunciado, procedimiento, fórmulas y ubicación exacta. Clasificar VALIDADA sólo si operaciones,
procedimiento y resultados están comprobados; INCORRECTA si hay error demostrable; PENDIENTE si faltan evidencias.
Una teoría sin ejercicio también puede registrarse como unidad de revisión, con alcance/hipótesis explícitos y comprobación.
Para VALIDADA o INCORRECTA entregar comprobaciones numéricas independientes basadas en el enunciado/formulas originales
(no identidades triviales), script Octave sencillo y salidas numéricas verificables. Para INCORRECTA comprobar el error
con un contraejemplo/diferencia y determinar corrección, citando ubicación y fórmula equivocada. Cada error debe incluir
comprobacion_error: expresion_original evaluable, valor_documentado, expresion_corregida evaluable, valor_corregido y tolerancia;
la discrepancia original/corregido o resultado documentado debe ser numéricamente demostrable. No confiar en caché Excel.
Python comprobará expresiones escalares sin variables: números, + - * / **, listas y sqrt exp log log10 sin cos tan abs sum min max.
Octave: script sin sistema, archivos, eval, source, run ni print; mostrar pasos. salidas.variables son nombres, valores
aplanados por COLUMNAS, celdas puede ser [] para la revisión de referencia, tolerancia absoluta en (0,0.01].
Si no es posible verificar, PENDIENTE; no inventar un enunciado, resultado ni rúbrica. Nunca confirmar por repetición.
Separar reglas de formato (estilo_excel/estilo_octave) de matemáticas (metodos/criterios_revision).
Toda regla necesita fuente EXACTA del registro, id de ejercicio y evidencia concreta. Matemáticas sólo de ejercicios VALIDADA.
De INCORRECTA/PENDIENTE sólo extraer formato independiente de sus cálculos. No usar la corrección inferida como regla docente
confirmada: es una corrección, no evidencia de cómo se enseñó. Material ilegible o no abarcado queda PENDIENTE.
'''


def save_cache(path,current):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def verify_review(response,source):
    exercises=response['ejercicios']
    ids=[e['id'] for e in exercises]
    if len(ids)!=len(set(ids)):
        raise ValueError('Ids de referencia duplicados')
    for e in exercises:
        e['verificacion_real']='No confirmada'
        if e['clasificacion']=='PENDIENTE':
            continue
        try:
            if not e['enunciado'].strip() or not e['localizacion'].strip():
                raise ValueError('Falta enunciado o ubicación')
            if e['clasificacion']=='VALIDADA' and e['errores']:
                raise ValueError('Validación contradicha por errores documentados')
            if e['clasificacion']=='INCORRECTA' and not e['errores']:
                raise ValueError('Error sin evidencia ni corrección')
            if e['clasificacion']=='INCORRECTA':
                for error in e['errores']:
                    proof=error['comprobacion_error']
                    before=arithmetic(proof['expresion_original'])
                    after=arithmetic(proof['expresion_corregida'])
                    tolerance=proof['tolerancia']
                    if not close(after,proof['valor_corregido'],tolerance):
                        raise ValueError('Corrección no comprobada')
                    if close(before,after,tolerance) and close(before,proof['valor_documentado'],tolerance):
                        raise ValueError('No se demostró la discrepancia de la referencia')
            check_question(e)
            e['verificacion_real']=octave.run(e['octave'],e['salidas'])
        except Exception as error:
            e['clasificacion']='PENDIENTE'
            e['verificacion_real']='No confirmada: '+str(error)
    by_id={e['id']:e for e in exercises}
    accepted=[]
    for rule in response['reglas']:
        exercise=by_id.get(rule.get('ejercicio'))
        if rule['fuente']!=source or not rule['regla'].strip() or not rule['evidencia'].strip() or not exercise:
            continue
        style=rule['categoria'] in ('estilo_excel','estilo_octave')
        if style or exercise['clasificacion']=='VALIDADA':
            accepted.append(rule)
    return exercises,accepted


def authority_record(item):
    """No incluir fórmulas ni imágenes de ejercicios incorrectos como contexto de resolución."""
    record=copy.deepcopy(item['registro'])
    exercises=item.get('ejercicios',[])
    validated=[e for e in exercises if e['clasificacion']=='VALIDADA']
    record['contenido']=json.dumps({
        'ejercicios_validados':validated,
        'reglas':item.get('reglas',[]),
        'clasificaciones':[{'id':e['id'],'localizacion':e['localizacion'],'clasificacion':e['clasificacion'],
                           'origen':e['origen']} for e in exercises],
        'advertencia':'Sólo VALIDADA tiene autoridad matemática. El resto sólo formato.'},ensure_ascii=False)
    # Entregar sólo el extracto auditado, nunca otras regiones no verificadas de una imagen.
    record['imagenes']=[]
    return record


def academic(root,scratch):
    cache_dir=root/'.mn_cache'
    if cache_dir.is_symlink() or (root/'perfil_academico').is_symlink():
        raise ValueError('Directorio académico enlazado no permitido')
    cache_dir.mkdir(exist_ok=True)
    images_dir=cache_dir/'imagenes'
    if images_dir.is_symlink():
        raise ValueError('Imágenes enlazadas no permitidas')
    images_dir.mkdir(exist_ok=True)
    path=cache_dir/'referencias.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    sources={p.relative_to(root).as_posix():p for p in discover(root/'referencias_clase')}
    current={k:v for k,v in previous.items() if k in sources and v.get('revision_version')==VERSION
             and v.get('sha256')==digest(sources[k])}
    # Invalidar inmediatamente las 26 reglas antiguas, las modificadas y las eliminadas,
    # incluso si Codex falla a continuación. El archivo de caché antiguo se conserva como historial privado.
    if previous and any(v.get('revision_version')!=VERSION for v in previous.values()):
        history=cache_dir/'reglas_anteriores_sin_validar.json'
        if not history.exists():
            history.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
    write_profiles(root,current)
    save_cache(path,current)
    for key,source in sources.items():
        old=current.get(key)
        if old:
            continue
        print('Revisión académica de referencia: '+key,flush=True)
        record=safe_extract(source,root,images_dir)
        if not record['lectura_completa']:
            exercises,rules=[],[]
            warnings=record['advertencias']
        else:
            text,images=pack([record])
            response=invoke(root,REVIEW_PROMPT+text,REFERENCE,images)
            exercises,rules=verify_review(response,key)
            warnings=response['advertencias']
        if not exercises:
            warnings.append('Referencia PENDIENTE: no se identificaron ejercicios verificables en '+key)
        current[key]={'revision_version':VERSION,'sha256':record['sha256'],'registro':record,
                      'ejercicios':exercises,'reglas':rules,'advertencias':warnings}
        save_cache(path,current)
        write_profiles(root,current)
    records=[authority_record(x) for x in current.values()]
    warnings=[w for x in current.values() for w in x['advertencias']]
    warnings += [f'{k} — {e["id"]}: {e["clasificacion"]}' for k,x in current.items()
                 for e in x.get('ejercicios',[]) if e['clasificacion']!='VALIDADA']
    return records,warnings


def write_profiles(root,current):
    for name in NAMES:
        path=root/'perfil_academico'/(name+'.md')
        if path.is_symlink():
            raise ValueError('Perfil enlazado no permitido')
        original=path.read_text(encoding='utf-8')
        original=re.sub(re.escape(START)+r'.*?'+re.escape(END),'',original,flags=re.S)
        if START in original or END in original:
            raise ValueError('Marcador de perfil incompleto')
        lines=[]
        for item in current.values():
            for rule in item.get('reglas',[]):
                if rule['categoria']==name:
                    lines.append(f'- {rule["regla"]}\n  Fuente: {rule["fuente"]} (SHA256 {item["sha256"][:12]}), ejercicio {rule.get("ejercicio","sin revisión")}. Evidencia: {rule["evidencia"]}')
        block='\n\n'+START+'\n'+ ('\n'.join(lines) or 'Sin reglas con revisión vigente. No reutilizar resultados anteriores sin validar.')+'\n'+END+'\n'
        new=original.rstrip()+block
        if path.read_text(encoding='utf-8')!=new:
            path.write_text(new,encoding='utf-8')
