#!/usr/bin/env python3
"""Install one selected platform; run without options for the interactive wizard."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from llm_eval.workflow import main
if __name__=='__main__':raise SystemExit(main('setup'))
