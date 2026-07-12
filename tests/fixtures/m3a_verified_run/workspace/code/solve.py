import argparse
import json
import os
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--mode', required=True, choices=['validated'])
args = parser.parse_args()
source = Path('input/input.txt')
if not source.is_file():
    source = Path('../problem/input.txt')
Path('output').mkdir(exist_ok=True)
Path('output/result.json').write_text(json.dumps({'objective': len(source.read_text(encoding='utf-8'))}) + '\n', encoding='utf-8')
Path('output/execution_challenge.json').write_text(json.dumps({'challenge_nonce': os.environ['SHUMO_EXECUTION_CHALLENGE'], 'run_id': os.environ['SHUMO_RUN_ID'], 'execution_id': os.environ['SHUMO_EXECUTION_ID']}) + '\n', encoding='utf-8')
print('formal test')
