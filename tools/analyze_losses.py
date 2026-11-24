"""Offline rule-based analysis of the downloaded platform games.

This tool does not use the engine evaluation. It enumerates length-five
segments directly. VCF proofs follow only compulsory replies; unknown is not
a proof of safety. Ply 1 means the first move after the four preset stones.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

N = 12
FULL = (1 << (N*N)) - 1
SEGMENTS = []
for r in range(N):
    for c in range(N):
        for dr, dc in ((0,1),(1,0),(1,1),(1,-1)):
            if 0 <= r+4*dr < N and 0 <= c+4*dc < N:
                SEGMENTS.append(sum(1 << ((r+k*dr)*N+c+k*dc) for k in range(5)))


def positions(bits):
    while bits:
        bit = bits & -bits
        yield bit.bit_length()-1
        bits ^= bit


def coordinates(bits):
    return [[p//N,p%N] for p in positions(bits)]


def win_points(own, other):
    result = 0
    for window in SEGMENTS:
        if window & other:
            continue
        empty = window & ~own
        if empty and not empty & (empty-1):
            result |= empty
    return result


def has_five(own):
    return any(own & w == w for w in SEGMENTS)


def attack_candidates(own, other):
    result = 0
    for window in SEGMENTS:
        if not window & other and (window & own).bit_count() == 3:
            result |= window & ~own
    return result


def winning_forks(own, other):
    """Non-winning moves leaving >=2 distinct wins, with no opponent win."""
    result = 0
    direct = win_points(own, other)
    enemy = win_points(other, own)
    if enemy.bit_count() >= 2:
        return 0
    candidates = attack_candidates(own, other) & ~direct
    if enemy:
        candidates &= enemy
    for p in positions(candidates):
        bit = 1 << p
        if win_points(own|bit,other).bit_count() >= 2:
            result |= bit
    return result


class VCF:
    def __init__(self, max_nodes=20000, max_plies=24):
        self.max_nodes = max_nodes
        self.max_plies = max_plies
        self.nodes = 0
        self.exhausted = False
        self.failed = set()

    def solve(self, own, other, depth=None):
        if depth is None:
            depth = self.max_plies
        self.nodes += 1
        if self.nodes > self.max_nodes:
            self.exhausted = True
            return None
        direct = win_points(own, other)
        if direct:
            return [{"attack":coordinates(direct)[0],"terminal":"five"}]
        enemy = win_points(other, own)
        if enemy.bit_count() >= 2 or depth <= 0:
            return None
        key = (own,other,depth)
        if key in self.failed:
            return None
        candidates = attack_candidates(own,other)
        if enemy:
            candidates &= enemy
        ordered = []
        for p in positions(candidates):
            wins = win_points(own|(1<<p),other)
            if wins:
                ordered.append((wins.bit_count(),p,wins))
        ordered.sort(reverse=True)
        for count,p,wins in ordered:
            move = [p//N,p%N]
            if count >= 2:
                return [{"attack":move,"terminal":"two_winning_points",
                         "winning_points":coordinates(wins)}]
            q = next(positions(wins))
            tail = self.solve(own|(1<<p),other|(1<<q),depth-2)
            if tail is not None:
                return [{"attack":move,"forced_reply":[q//N,q%N]}]+tail
            if self.exhausted:
                return None
        self.failed.add(key)
        return None


def recorded_quiet_move_proof(own, other, max_nodes=20000, max_plies=24):
    """After an attack, quantify over EVERY legal defender reply.

    Only called for the actual next opponent move from the log. Thus a proof
    establishes that this move wins, but failure says nothing about other
    opponent choices. Never infer a win by replaying a fixed defender line.
    """
    empty = FULL & ~(own|other)
    if not empty or win_points(other,own):
        return {'status':'not_proved','reason':'draw_or_defender_can_win'}
    checked = 0
    max_attacks = 0
    for p in positions(empty):
        solver = VCF(max_nodes,max_plies)
        proof = solver.solve(own,other|(1<<p))
        if proof is None:
            return {'status':'not_proved','first_unproved_reply':[p//N,p%N],
                    'checked_proved_replies':checked,
                    'node_limit':solver.exhausted}
        checked += 1
        max_attacks = max(max_attacks,len(proof))
    return {'status':'proved','all_legal_defender_replies_checked':checked,
            'max_vcf_attacks_in_suffix_proofs':max_attacks,
            'max_suffix_plies':max_plies}


def verify_vcf_proof(own, other, proof):
    for i, step in enumerate(proof):
        r,c = step['attack']; bit = 1 << (r*N+c)
        assert not bit & (own|other)
        own |= bit
        if has_five(own):
            assert step.get('terminal')=='five' and i==len(proof)-1
            return
        assert not win_points(other,own), 'Defender could win instead of blocking'
        threats = win_points(own,other)
        if step.get('terminal')=='two_winning_points':
            assert threats.bit_count() >= 2 and i==len(proof)-1
            assert coordinates(threats)==step['winning_points']
            return
        assert threats.bit_count()==1
        assert coordinates(threats)[0]==step['forced_reply']
        other |= threats
    raise AssertionError('Proof has no terminal')


def compare_all_replies_to_vcf(game, ply, max_plies=30):
    """At the recorded pre-ply board, reject moves with explicit enemy VCF."""
    bits = [0,0,0]
    for r,row in enumerate(game['initial_board']):
        for c,color in enumerate(row):
            if color:
                bits[color] |= 1 << (r*N+c)
    for move in game['moves'][:ply-1]:
        bits[move['color']] |= 1 << (move['row']*N+move['col'])
    color = game['moves'][ply-1]['color']
    result = {'round_id':game['round_id'],'before_ply':ply,'color':color,
              'max_search_plies':max_plies,'proved_vcf_losing_count':0,
              'unrefuted_moves':[],'node_limited_moves':[]}
    for p in positions(FULL & ~(bits[1]|bits[2])):
        own = bits[color]|(1<<p)
        solver = VCF(50000,max_plies)
        proof = None if has_five(own) else solver.solve(bits[3-color],own)
        if proof is not None:
            verify_vcf_proof(bits[3-color],own,proof)
            result['proved_vcf_losing_count'] += 1
        elif solver.exhausted:
            result['node_limited_moves'].append([p//N,p%N])
        else:
            result['unrefuted_moves'].append([p//N,p%N])
    return result


def analyze_game(game, directory):
    lines = [json.loads(x) for x in (directory/(game['round_id']+'.log')).read_text(encoding='utf-8').splitlines() if x]
    config = next(x['data']['brainsConfig'] for x in lines if x['data'].get('action')=='initialize')
    user = config['1']['field']
    bits = [0,0,0]
    for r,row in enumerate(game['initial_board']):
        for c,color in enumerate(row):
            if color:
                bits[color] |= 1 << (r*N+c)
    records = []
    for ply, move in enumerate(game['moves'],1):
        color = move['color']; other = 3-color
        p = move['row']*N+move['col']; bit = 1<<p
        assert not (bits[1]|bits[2]) & bit, (game['round_id'],ply,'occupied')
        own_wins = win_points(bits[color],bits[other])
        enemy_wins = win_points(bits[other],bits[color])
        own_forks = winning_forks(bits[color],bits[other])
        enemy_forks = winning_forks(bits[other],bits[color])
        rec = {'ply':ply,'color':color,'user_move':color==user,
               'move':[move['row'],move['col']],
               'own_immediate_wins_before':coordinates(own_wins),
               'enemy_immediate_wins_before':coordinates(enemy_wins),
               'own_winning_forks_before':coordinates(own_forks),
               'enemy_winning_forks_before':coordinates(enemy_forks),
               'missed_immediate_win':bool(own_wins and not own_wins & bit),
               'missed_unique_block':bool(not own_wins and enemy_wins.bit_count()==1 and not enemy_wins & bit),
               'already_faces_two_immediate_wins':bool(not own_wins and enemy_wins.bit_count()>=2),
               'missed_proved_fork':bool(not own_wins and own_forks and not own_forks & bit)}
        bits[color] |= bit
        rec['formed_five'] = has_five(bits[color])
        rec['own_immediate_wins_after'] = coordinates(win_points(bits[color],bits[other]))
        rec['enemy_winning_forks_after'] = coordinates(winning_forks(bits[other],bits[color]))
        if color == user and not rec['formed_five']:
            solver = VCF()
            proof = solver.solve(bits[other],bits[color])
            if proof is not None:
                verify_vcf_proof(bits[other],bits[color],proof)
            rec['opponent_vcf_after'] = {
                'status':'proved' if proof is not None else ('node_limit' if solver.exhausted else 'not_found_within_depth'),
                'max_plies':solver.max_plies,'nodes':solver.nodes,'proof':proof}
            if proof is None and ply < len(game['moves']):
                follow = game['moves'][ply]
                attack = 1 << (follow['row']*N+follow['col'])
                quiet = recorded_quiet_move_proof(bits[other]|attack,bits[color])
                quiet['opponent_ply'] = ply+1
                quiet['opponent_move'] = [follow['row'],follow['col']]
                rec['recorded_next_attack_then_vcf'] = quiet
        records.append(rec)
    final = [row[:] for row in game['final_board']]
    for r in range(N):
        for c in range(N):
            p = r*N+c
            actual = 1 if bits[1] & (1<<p) else (2 if bits[2] & (1<<p) else 0)
            assert final[r][c] == actual, (game['round_id'],'final mismatch')
    winner = next((color for color in (1,2) if has_five(bits[color])),0)
    summary = next(x['data']['data'] for x in lines if x['data'].get('action')=='summary')
    return {'round_id':game['round_id'],'source_url':game['source_url'],
            'user_brain_id':'1','user_color_from_log':user,'winner_color':winner,
            'user_result':'draw' if not winner else ('win' if winner==user else 'loss'),
            'user_elapsed_ms_from_log':summary['elapsedRoundTime']['1'],
            'exit_cause_from_log':summary['exitCausedBy'],
            'plies':len(records),'records':records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path(__file__).resolve().parents[1]/'results'/'platform')
    args = parser.parse_args()
    games = json.loads((args.directory/'games.json').read_text(encoding='utf-8'))
    report = {'coordinate_order':'row,column, zero-based',
              'ply_definition':'First move after the four initial stones is ply 1.',
              'vcf_meaning':'Proved means a forcing proof with compulsory replies. Not found is unknown, not a safety guarantee.',
              'games':[]}
    for game in games:
        result = analyze_game(game,args.directory)
        report['games'].append(result)
        mine = [r for r in result['records'] if r['user_move']]
        direct = [r['ply'] for r in mine if r['missed_immediate_win'] or r['missed_unique_block'] or r['missed_proved_fork']]
        doomed = [r['ply'] for r in mine if r['already_faces_two_immediate_wins']]
        proofs = [r['ply'] for r in mine if r.get('opponent_vcf_after',{}).get('status')=='proved']
        forks = [r['ply'] for r in mine if r['enemy_winning_forks_after']]
        quiet = [r['ply'] for r in mine if r.get('recorded_next_attack_then_vcf',{}).get('status')=='proved']
        print(result['round_id'],'user_color=',result['user_color_from_log'],'result=',result['user_result'],
              'direct_errors=',direct,'already_two_wins=',doomed,'leaves_fork=',forks,'vcf_after=',proofs,
              'actual_next_attack_then_vcf_after=',quiet,flush=True)
        (args.directory/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    focus = {'6ae867f9e905020013cc8875':10,'6ae86267e905020013cc866b':18}
    report['focused_all_move_comparisons'] = [compare_all_replies_to_vcf(g,focus[g['round_id']])
                                            for g in games if g['round_id'] in focus]
    for scan in report['focused_all_move_comparisons']:
        print('Focus',scan,flush=True)
    (args.directory/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
