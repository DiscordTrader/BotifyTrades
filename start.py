import os
import sys

os.execvp(sys.executable, [sys.executable, '-u', 'src/selfbot_webull.py'] + sys.argv[1:])
