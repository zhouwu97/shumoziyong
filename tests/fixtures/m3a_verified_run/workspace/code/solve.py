import json
from pathlib import Path
source = Path('input/input.txt')
if not source.is_file():
    source = Path('../problem/input.txt')
Path('output').mkdir(exist_ok=True)
Path('output/result.json').write_text(json.dumps({'objective': len(source.read_text(encoding='utf-8'))}) + '\n', encoding='utf-8')
print('formal test')
