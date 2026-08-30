import os
import sys

# Make the repo root importable (test_vectors/) and allow running the
# test suite straight from a source checkout without installation.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
