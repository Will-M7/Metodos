"""Aritmética limitada: no ejecuta Python generado por IA ni usa eval."""
import ast
import math
import operator
import re

FUNCTIONS = {k: getattr(math, k) for k in ('sqrt', 'exp', 'log', 'log10', 'sin', 'cos', 'tan', 'acos', 'asin', 'atan', 'floor', 'ceil')}
FUNCTIONS.update(abs=abs, sum=sum, min=min, max=max, mean=lambda values: sum(values)/len(values))
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}


def arithmetic(expression):
    if len(expression) > 4000:
        raise ValueError('Expresión demasiado larga')
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as e:
        raise ValueError('Expresión matemática inválida') from e
    if len(list(ast.walk(tree))) > 600:
        raise ValueError('Expresión demasiado compleja')

    def calc(n):
        if isinstance(n, ast.Expression):
            return calc(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            if not math.isfinite(n.value) or abs(n.value) > 1e100:
                raise ValueError('Número fuera de rango')
            return n.value
        if isinstance(n, (ast.List, ast.Tuple)):
            return [calc(x) for x in n.elts]
        if isinstance(n, ast.Name) and n.id in ('pi', 'e'):
            return getattr(math, n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -calc(n.operand) if isinstance(n.op, ast.USub) else calc(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = calc(n.left), calc(n.right)
            if type(a) not in (int, float) or type(b) not in (int, float):
                raise ValueError('Operación no escalar')
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise ValueError('Exponente fuera de rango')
            return OPS[type(n.op)](a, b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCTIONS and not n.keywords:
            return FUNCTIONS[n.func.id](*[calc(x) for x in n.args])
        raise ValueError('Expresión no admitida: ' + expression)
    try:
        value = calc(tree)
    except (ArithmeticError, TypeError) as e:
        raise ValueError('Operación matemática inválida: ' + str(e)) from e
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Resultado no finito o no escalar')
    return value


def close(actual, expected, tolerance):
    if not 0 < tolerance <= 0.01:
        raise ValueError('Tolerancia fuera de (0, 0.01]')
    return math.isfinite(actual) and math.isfinite(expected) and abs(actual - expected) <= tolerance


def check_question(q):
    if not q['comprobaciones'] or not q['salidas']:
        raise ValueError('Faltan comprobaciones numéricas o salidas Octave')
    for c in q['comprobaciones']:
        if not close(arithmetic(c['expresion']), c['esperado'], c['tolerancia']):
            raise ValueError('Falló comprobación Python: ' + c['nombre'])


class FormulaBook:
    """Subconjunto explícito de Excel. Lo desconocido queda pendiente, nunca PASS."""
    def __init__(self, sheet):
        self.sheet, self.cache, self.visiting = sheet, {}, set()

    def value(self, address):
        address = address.replace('$', '').upper()
        if address in self.cache:
            return self.cache[address]
        if address in self.visiting:
            raise ValueError('Referencia circular: ' + address)
        self.visiting.add(address)
        value = self.sheet[address].value
        if isinstance(value, str) and value.startswith('='):
            expression = value[1:].upper().replace('^', '**')
            functions = {'SUM': 'sum', 'ABS': 'abs', 'SQRT': 'sqrt', 'EXP': 'exp', 'LN': 'log',
                         'LOG10': 'log10', 'AVERAGE': 'mean', 'SIN': 'sin', 'COS': 'cos', 'TAN': 'tan', 'MIN': 'min', 'MAX': 'max'}
            # Expandir rangos antes de referencias individuales.
            ranges = {}
            def expand(m):
                key = f'__RANGE_{len(ranges)}__'
                from openpyxl.utils.cell import range_boundaries
                x1, y1, x2, y2 = range_boundaries(m.group().replace('$', ''))
                if (x2-x1+1)*(y2-y1+1) > 10000:
                    raise ValueError('Rango demasiado grande')
                ranges[key] = repr([self.value(self.sheet.cell(r, c).coordinate)
                                    for r in range(y1, y2+1) for c in range(x1, x2+1)])
                return key
            expression = re.sub(r'\$?[A-Z]{1,3}\$?[1-9][0-9]*:\$?[A-Z]{1,3}\$?[1-9][0-9]*', expand, expression)
            expression = re.sub(r'(?<![A-Z0-9_])\$?[A-Z]{1,3}\$?[1-9][0-9]*\b(?!\s*\()',
                                lambda m: repr(self.value(m.group())), expression)
            for key, val in ranges.items():
                expression = expression.replace(key, val)
            for name, replacement in functions.items():
                expression = re.sub(r'\b' + name + r'(?=\s*\()', replacement, expression)
            value = arithmetic(expression)
        if value is None:
            value = 0  # Semántica de referencia a celda vacía en operaciones aritméticas.
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Celda no numérica: ' + address)
        self.visiting.remove(address)
        self.cache[address] = value
        return value
