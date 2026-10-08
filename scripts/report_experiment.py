#!/usr/bin/env python3
"""Generate an experiment report and optionally push a results pull request."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from llm_eval.reporting.cli import main
if __name__=='__main__':
    args=['--input' if a=='--experiment-dir' else a for a in sys.argv[1:]]
    raise SystemExit(main(['report',*args]))
