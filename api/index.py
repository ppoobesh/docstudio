import os
import sys

# Append project root directory to sys.path so 'app.py' imports seamlessly
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app

# Vercel needs the 'app' callable exposed at module level
app = app