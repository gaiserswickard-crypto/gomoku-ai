"""Build a standalone C++17 brain with the relevant public RenLib subtree.

No third-party engine/decoder is copied. The data is a move tree, not a proof
that its omitted replies or its unlabelled leaves are winning.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from renlib import read_library

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 1048576


def uleb(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return result


def won(board, pos, side):
    row, col = divmod(pos, 12)
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        count = 1
        for sign in (-1, 1):
            r, c = row + dr * sign, col + dc * sign
            while 0 <= r < 12 and 0 <= c < 12 and board[r * 12 + c] == side:
                count += 1
                r += dr * sign
                c += dc * sign
        if count >= 5:
            return True
    return False


def make_tree(library):
    initial = library.follow([7 * 15 + 7, 6 * 15 + 7, 6 * 15 + 8, 7 * 15 + 8])
    board = [0] * 144
    for pos, side in ((5 * 12 + 6, 1), (6 * 12 + 5, 1),
                      (5 * 12 + 5, 2), (6 * 12 + 6, 2)):
        board[pos] = side
    moves, counts = [255], [0]
    stats = {'invalid_source_subtrees': 0, 'out_of_bounds_subtrees': 0,
             'non_move_subtrees': 0, 'terminal_black': 0, 'terminal_white': 0,
             'terminal_descendants_cut': 0, 'maximum_extra_plies': 0}

    def visit(node, depth):
        if not library.valid[node]:
            stats['invalid_source_subtrees'] += 1
            return False
        source_pos = library.pos[node]
        if source_pos < 0 or library.flags[node] & 2:
            stats['non_move_subtrees'] += 1
            return False
        # H8,H9,I9,I8 -> (5,6),(5,5),(6,5),(6,6).
        old_r, old_c = divmod(source_pos, 15)
        r, c = old_c - 2, old_r - 1
        if not (0 <= r < 12 and 0 <= c < 12):
            stats['out_of_bounds_subtrees'] += 1
            return False
        pos = r * 12 + c
        if board[pos] or depth > 140:
            raise ValueError('converted path contains duplicate stones or exceeds board')
        side = 1 if depth % 2 else 2
        if side != (1 if library.ply[node] % 2 else 2):
            raise ValueError('source move parity mismatch')
        board[pos] = side
        index = len(moves)
        moves.append(pos)
        counts.append(0)
        stats['maximum_extra_plies'] = max(stats['maximum_extra_plies'], depth)
        if won(board, pos, side):
            stats['terminal_black' if side == 1 else 'terminal_white'] += 1
            if library.first_child[node] != -1:
                stats['terminal_descendants_cut'] += 1
        else:
            for child in library.children(node):
                if visit(child, depth + 1):
                    counts[index] += 1
        board[pos] = 0
        return True

    for child in library.children(initial):
        if visit(child, 1):
            counts[0] += 1
    raw = bytearray()
    for pos, count in zip(moves, counts):
        raw.append(pos)
        raw.extend(uleb(count))
    stats.update({'source_root_node': initial, 'compiled_nodes_including_root': len(moves),
                  'root_choices': counts[0], 'raw_bytes': len(raw)})
    return bytes(raw), stats


def render(raw):
    base = (ROOT / 'src/engine.cpp').read_text(encoding='utf-8')
    runtime = (ROOT / 'tools/book_runtime.inc').read_text(encoding='utf-8')
    encoded = base64.b85encode(raw + bytes((-len(raw)) % 4)).decode('ascii')
    chunks = '\n'.join('    "' + encoded[i:i+4000] + '",' for i in range(0, len(encoded), 4000))
    data = f'''
// Public move data: https://587.renju.org.tw/program/1/D4-2.rar
// Fixed-start subtree; filtered for legal 12x12 paths. This is NOT a proof of
// exhaustive winning coverage. Generator and provenance: tools/build_book.py.
namespace gomoku_book {{
static const char* const kChunks[] = {{
{chunks}
}};
inline const Book& openingBook() {{
    static const Book book = [] {{
        Book value;
        value.load(kChunks, sizeof(kChunks)/sizeof(kChunks[0]), {len(raw)});
        return value;
    }}();
    return book;
}}
}} // namespace gomoku_book
'''
    base = base.replace('namespace gomoku {', runtime + '\n' + data + '\nnamespace gomoku {', 1)
    base = base.replace('int completedDepth_ = 0, lastScore_ = 0;',
                        'int completedDepth_ = 0, lastScore_ = 0;\n    bool bookUsed_ = false;', 1)
    base = base.replace('int depth() const {', 'bool usedBook() const { return bookUsed_; }\n    int depth() const {', 1)
    base = base.replace('completedDepth_ = 0; lastScore_ = 0;',
                        'completedDepth_ = 0; lastScore_ = 0; bookUsed_ = false;', 1)
    hook = '''
#ifndef GOMOKU_DISABLE_BOOK
        if (side == 1) {
            auto suggestions = gomoku_book::openingBook().candidates(cells_,side,8,3);
            if (!suggestions.empty()) {
                bool forkThreat = false;
                auto safeDefenses = forkDefenses(side,forkThreat);
                for (int candidate : suggestions) {
                    if (Clock::now() >= deadline_) break;
                    if (forkThreat && std::none_of(safeDefenses.begin(),safeDefenses.end(),
                            [candidate](const Move& m) { return m.pos == candidate; })) continue;
                    // A book leaf is not a win certificate. Reject any candidate
                    // for which the opponent has a proved continuous-four win.
                    proofDeadline_ = std::min(deadline_,Clock::now()+
                        std::chrono::milliseconds(std::max(1,std::min(20,budgetMs/20))));
                    proofAborted_ = false;
                    setStone(candidate,side);
                    int attack = -1;
                    bool refuted = proveFours(3-side,24,attack);
                    undoStone(candidate);
                    if (!refuted) { bookUsed_ = true; return candidate; }
                }
                proofAborted_ = false;
            }
        }
#endif
'''
    marker = '        if (hasFork(side)) return firstFork(side);'
    if base.count(marker) != 1:
        raise ValueError('unexpected baseline: book insertion point is not unique')
    base = base.replace(marker, marker + '\n' + hook, 1)
    base = base.replace('std::cerr << "depth="', 'std::cerr << "book=" << engine.usedBook() << " depth="', 1)
    result = base.encode('utf-8')
    if len(result) > LIMIT:
        raise ValueError(f'generated source is {len(result)} bytes, exceeds {LIMIT}')
    return result, len(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=ROOT/'tmp/book_research/flower_public.lib')
    parser.add_argument('--output', type=Path, default=ROOT/'book_candidate.cpp')
    args = parser.parse_args()
    args.output = args.output.resolve()
    library = read_library(args.library)
    raw, stats = make_tree(library)
    directory = ROOT/'results/book'
    directory.mkdir(exist_ok=True)
    (directory/'book.bin').write_bytes(raw)
    source, encoded_size = render(raw)
    args.output.write_bytes(source)
    report = {'client_date': '2026-11-03', 'source_url': 'https://587.renju.org.tw/program/1/D4-2.rar',
              'library_sha256': library.source_sha256,
              'engine_source': 'src/engine.cpp',
              'engine_sha256': hashlib.sha256((ROOT/'src/engine.cpp').read_bytes()).hexdigest(),
              'output': str(args.output.relative_to(ROOT)),
              'source_bytes': len(source), 'source_limit_bytes': LIMIT,
              'source_sha256': hashlib.sha256(source).hexdigest(),
              'raw_sha256': hashlib.sha256(raw).hexdigest(), 'base85_bytes': encoded_size,
              'tree': stats, 'complete_winning_strategy_proved': False,
              'note': 'Book annotations contain no win/loss certificates. Missing replies, filtered branches and unmatched boards fall back to the v2 search engine. White uses search.'}
    (directory/'build_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
