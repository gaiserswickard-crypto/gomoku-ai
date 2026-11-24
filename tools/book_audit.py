"""Independent structural and freestyle-rule audit of an embedded opening tree.

Input is preorder (move:uint8, childCount:ULEB128), with move 255 at the
implicit four-stone root. This is deliberately separate from the C++ reader
and the RenLib converter. Missing white replies and nonterminal leaves are
reported as unproved, never silently treated as a complete winning strategy.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

N = 12
INITIAL = {5*12+6: 1, 6*12+5: 1, 5*12+5: 2, 6*12+6: 2}
WINDOWS = []
AFFECTED = [[] for _ in range(144)]
for r in range(N):
    for c in range(N):
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            if 0 <= r+4*dr < N and 0 <= c+4*dc < N:
                ps = [(r+k*dr)*N+c+k*dc for k in range(5)]
                index = len(WINDOWS)
                WINDOWS.append(sum(1 << p for p in ps))
                for p in ps:
                    AFFECTED[p].append(index)


def decode(raw):
    """Return compact arrays and subtree ends; reject malformed encodings."""
    move, count, depth, parent, end = (array('i') for _ in range(5))
    cursor = 0
    stack = []  # [node, unconsumed direct children]
    while cursor < len(raw):
        p = raw[cursor]
        cursor += 1
        value = shift = 0
        while True:
            if cursor == len(raw) or shift >= 21:
                raise ValueError('truncated or overlong child count')
            b = raw[cursor]
            cursor += 1
            value |= (b & 127) << shift
            if b < 128:
                break
            shift += 7
        if value > 140:
            raise ValueError('more children than remaining legal squares')
        node = len(move)
        if node == 0:
            if p != 255:
                raise ValueError('root move must be 255')
            par, dep = -1, 0
        else:
            if not stack or p >= 144:
                raise ValueError('extra node or out-of-range move')
            par, dep = stack[-1][0], len(stack)
            stack[-1][1] -= 1
            if dep > 140:
                raise ValueError('path exceeds board capacity')
        move.append(p)
        count.append(value)
        depth.append(dep)
        parent.append(par)
        end.append(-1)
        stack.append([node, value])
        while stack and stack[-1][1] == 0:
            closing, _ = stack.pop()
            end[closing] = node+1
    if not move or stack:
        raise ValueError('empty or incomplete tree')
    return move, count, depth, parent, end


class Rules:
    """Incremental counts over independent five-cell windows, not engine LUTs."""
    def __init__(self):
        self.bits = [0, 0, 0]
        self.board = [0]*144
        self.wins = [0, 0, 0]
        self.fives = [0, 0, 0]
        self.multiplicity = [[0]*144 for _ in range(3)]
        self.contribution = [[-1]*len(WINDOWS) for _ in range(3)]
        for p, c in INITIAL.items():
            self.change(p, c)

    def change(self, p, color):
        previous = self.board[p]
        if previous:
            self.bits[previous] ^= 1 << p
        if color:
            self.bits[color] |= 1 << p
        self.board[p] = color
        occupied = self.bits[1] | self.bits[2]
        for index in AFFECTED[p]:
            window = WINDOWS[index]
            for side in (1, 2):
                old = self.contribution[side][index]
                if old == -2:
                    self.fives[side] -= 1
                elif old >= 0:
                    self.multiplicity[side][old] -= 1
                    if not self.multiplicity[side][old]:
                        self.wins[side] &= ~(1 << old)
                new = -1
                if not window & self.bits[3-side]:
                    empty = window & ~occupied
                    if not empty:
                        new = -2
                        self.fives[side] += 1
                    elif not empty & (empty-1):
                        new = empty.bit_length()-1
                        self.multiplicity[side][new] += 1
                        self.wins[side] |= empty
                self.contribution[side][index] = new


def audit(path, output, example_limit=12, vcf_samples=0):
    start = time.perf_counter()
    raw = path.read_bytes()
    move, count, depth, parent, end = decode(raw)
    rules = Rules()
    counters = Counter()
    leaf_types = Counter()
    examples = {}
    active = []
    samples = []

    def record(kind, node):
        counters[kind] += 1
        if len(examples.setdefault(kind, [])) < example_limit:
            examples[kind].append({'node': node, 'ply': depth[node],
                                   'moves': [[move[i]//12, move[i]%12] for i in active]+[[move[node]//12, move[node]%12]]})

    for node in range(len(move)):
        if node:
            while len(active) >= depth[node]:
                rules.change(move[active.pop()], 0)
            p = move[node]
            side = 1 if depth[node] % 2 else 2
            if rules.board[p]:
                raise ValueError(f'node {node} repeats an occupied square')
            if rules.fives[1] or rules.fives[2]:
                record('continuation_after_terminal', node)
            if side == 1:
                if rules.wins[1] and not rules.wins[1] & (1 << p):
                    record('black_does_not_take_immediate_win', node)
                if not rules.wins[1] and rules.wins[2].bit_count() == 1 and not rules.wins[2] & (1 << p):
                    record('black_misses_unique_block', node)
            rules.change(p, side)
            if side == 1 and not rules.fives[1] and rules.wins[2]:
                record('black_allows_immediate_white_win', node)
            if side == 1 and vcf_samples and len(samples) < vcf_samples and 1 <= depth[node] <= 12 and not rules.fives[1] and not rules.fives[2]:
                samples.append((node, rules.bits[1], rules.bits[2]))
            active.append(node)
        counters['nodes'] += 1
        if not count[node]:
            if rules.fives[1]:
                leaf_types['black_five'] += 1
            elif rules.fives[2]:
                leaf_types['white_five'] += 1
            elif depth[node] % 2 == 1 and rules.wins[1].bit_count() >= 2 and not rules.wins[2]:
                leaf_types['black_two_winning_points'] += 1
            elif depth[node] % 2 == 0 and rules.wins[1]:
                leaf_types['black_to_move_immediate_win'] += 1
            else:
                leaf_types['unproved_nonterminal'] += 1
        elif depth[node] % 2 == 1 and not rules.fives[1] and not rules.fives[2]:
            # The next player is White. Enumerate listed children rather than
            # assuming their count includes every defense.
            listed = []
            child = node+1
            while child < end[node]:
                listed.append(move[child])
                child = end[child]
            if len(set(listed)) != len(listed):
                counters['duplicate_white_children'] += 1
            unlisted = 140-depth[node]-len(set(listed))
            if unlisted:
                counters['white_nodes_with_unlisted_legal_replies'] += 1
                counters['unlisted_white_replies_total'] += unlisted
                missing = ((1 << 144)-1) & ~(rules.bits[1] | rules.bits[2])
                for p in listed:
                    missing &= ~(1 << p)
                immediate_refutations = 0
                if rules.wins[1].bit_count() >= 2:
                    immediate_refutations = (missing & ~rules.wins[2]).bit_count()
                elif rules.wins[1]:
                    immediate_refutations = (missing & ~rules.wins[2] & ~rules.wins[1]).bit_count()
                counters['unlisted_white_replies_refuted_by_immediate_black_win'] += immediate_refutations
                counters['unlisted_white_replies_unresolved_by_this_audit'] += unlisted-immediate_refutations

    vcf = {'sample_count': len(samples), 'proved_losing_candidates': [], 'node_limited_candidates': 0}
    if samples:
        from analyze_losses import VCF, verify_vcf_proof
        for node, black, white in samples:
            solver = VCF(max_nodes=20000, max_plies=24)
            proof = solver.solve(white, black)
            if proof is not None:
                verify_vcf_proof(white, black, proof)
                vcf['proved_losing_candidates'].append({'node': node, 'ply': depth[node], 'proof': proof})
            elif solver.exhausted:
                vcf['node_limited_candidates'] += 1
    report = {'raw_file': str(path), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
              'raw_bytes': len(raw), 'max_plies_after_initial': max(depth),
              'counts': dict(counters), 'leaf_types': dict(leaf_types), 'examples': examples,
              'vcf_screen': vcf, 'elapsed_seconds': time.perf_counter()-start,
              'scope': 'Independent 12x12 freestyle legality and immediate-tactic audit; missing white replies and nonterminal leaves are NOT certified winning.',
              'full_black_win_proven': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('raw_bytes','max_plies_after_initial','counts','leaf_types','elapsed_seconds')}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vcf-samples', type=int, default=0)
    args = parser.parse_args()
    audit(args.raw, args.output, vcf_samples=args.vcf_samples)
