#!/usr/bin/env python3
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
from app import main
if __name__ == "__main__":
    main()
