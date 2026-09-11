"""Argument-preserving Windows learning command dispatcher."""
from pathlib import Path
import runpy
import sys

scripts = {'train':'train_guidance.py','export':'export_guidance.py','verify':'verify_guidance.py'}
if len(sys.argv) < 2 or sys.argv[1] not in scripts:
    raise SystemExit('expected train, export or verify')
path = Path(__file__).resolve().parent/scripts[sys.argv[1]]
sys.argv = [str(path),*sys.argv[2:]]
runpy.run_path(str(path),run_name='__main__')
