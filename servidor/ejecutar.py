"""Subproceso de cálculo: reutiliza el motor existente sin duplicarlo."""
import argparse
import sys
from pathlib import Path
from src.main import run


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operacion',choices=('revisar','respuestas','generar'))
    parser.add_argument('trabajo',type=Path)
    parser.add_argument('academico',type=Path)
    args=parser.parse_args()
    try:
        return run(args.operacion,args.trabajo,academic_root=args.academico)
    except Exception as e:
        print('ERROR: '+str(e),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
