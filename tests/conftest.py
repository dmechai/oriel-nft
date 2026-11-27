import os
from pathlib import Path

os.environ["ORIEL_DATA"] = str(Path("/tmp/oriel-pytest"))
