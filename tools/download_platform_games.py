"""Download only round/log links observed in the three selected match pages."""
import json
from pathlib import Path
from urllib.request import urlopen
from read_platform import BASE, OUT, Document, fetch

MATCHES = ['6ae867f9e6cd403666e99202','6ae86bf5e6cd403666ea157f','6ae86267e6cd403666e92289']
games = []
for match_id in MATCHES:
    source = OUT / (match_id + '.html')
    match = Document(source.read_text(encoding='utf-8')).root
    rounds = match.find(lambda n:n.tag == 'a' and n.attrs.get('href','').startswith('/match/') and '/round/' in n.attrs['href'])
    for link in rounds:
        path = link.attrs['href']
        round_id = path.rsplit('/',1)[-1]
        source = OUT / (round_id + '.html')
        page = Document(source.read_text(encoding='utf-8')).root if source.exists() else fetch(path)
        log_link = page.find(lambda n:n.tag == 'a' and n.attrs.get('href','').endswith('/logs'))[0].attrs['href']
        log_file = OUT / (round_id + '.log')
        if not log_file.exists():
            with urlopen(BASE+log_link,timeout=20) as response:
                log_file.write_bytes(response.read())
        entries = [json.loads(line) for line in log_file.read_text(encoding='utf-8').splitlines() if line.strip()]
        initial = next(e['data']['board'] for e in entries if e.get('data',{}).get('action') == 'clearBoard')
        board_states = [e['data']['board'] for e in entries if e.get('data',{}).get('action') == 'getBoardMap']
        moves = []
        for entry in entries:
            d = entry.get('data',{})
            if isinstance(d,dict) and d.get('action') == 'place':
                row,col = map(int,d['position'].split())
                moves.append({'color':d['field'],'row':row,'col':col,'timestamp':entry['at']})
        game = {'match_id':match_id,'round_id':round_id,'source_url':BASE+path,
                'log_url':BASE+log_link,'initial_board':initial,'final_board':board_states[-1],
                'moves':moves,'metadata':[e for e in entries if e.get('type') != 'debug']}
        games.append(game)
        print(round_id,len(moves),'moves', 'saved',flush=True)
(OUT / 'games.json').write_text(json.dumps(games,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
