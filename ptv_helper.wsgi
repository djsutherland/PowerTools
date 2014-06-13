import os
dir = os.path.abspath(os.path.dirname(__file__))

activate_this = os.path.join(dir, 'venv/bin/activate_this.py')
execfile(activate_this, dict(__file__=activate_this))

import sys
sys.path.insert(0, dir)

from server import app as application
