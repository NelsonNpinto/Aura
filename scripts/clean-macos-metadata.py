"""Remove only AppleDouble metadata within AURA sources before external-drive Docker builds."""
import os
from pathlib import Path
root=Path(__file__).resolve().parent.parent
count=0
for dirname, dirs, files in os.walk(root):
    dirs[:]=[d for d in dirs if d not in {'.git','.venv','node_modules','dist','__pycache__'}]
    for name in files:
        if name.startswith('._'):
            path=Path(dirname)/name
            with path.open('rb') as stream:
                if stream.read(4)==b'\x00\x05\x16\x07':
                    path.unlink()
                    count+=1
print(f'Removed {count} AppleDouble metadata files; source contents preserved.')
