"""Compare choices on recorded positions, without treating changed continuations as games."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def query(process, board, color, budget):
    stones = [(r*12+c,v) for r,row in enumerate(board) for c,v in enumerate(row) if v]
    message = f'{len(stones)} {color} {budget}\n' + ''.join(f'{p} {v}\n' for p,v in stones)
    process.stdin.write(message)
    process.stdin.flush()
    line = process.stdout.readline()
    if not line: raise RuntimeError('probe exited unexpectedly')
    return json.loads(line)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine', required=True)
    ap.add_argument('--budget',type=int,default=250)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--round',default='')
    ap.add_argument('--plies',default='')
    args = ap.parse_args()
    selected = {int(v) for v in args.plies.split(',') if v}
    games = json.loads((ROOT/'results/platform/games.json').read_text(encoding='utf-8'))
    results = []
    with subprocess.Popen([args.engine],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as process:
        try:
            for game in games:
                if args.round and not game['round_id'].endswith(args.round): continue
                records = [json.loads(l) for l in (ROOT/'results/platform'/f"{game['round_id']}.log").read_text().splitlines()]
                config = next(e['data']['brainsConfig'] for e in records if e.get('data',{}).get('action') == 'initialize')
                color = config['1']['field']
                board = [row[:] for row in game['initial_board']]
                for ply,m in enumerate(game['moves'],1):
                    if m['color'] == color and (not selected or ply in selected):
                        answer = query(process,board,color,args.budget)
                        result = {'round_id':game['round_id'],'ply':ply,'color':color,
                                  'recorded_move':[m['row'],m['col']],**answer}
                        results.append(result)
                        print(json.dumps(result),flush=True)
                    board[m['row']][m['col']] = m['color']
        finally:
            process.stdin.close()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'engine':args.engine,'budget_ms':args.budget,'positions':results},indent=2)+'\n')

if __name__ == '__main__': main()
