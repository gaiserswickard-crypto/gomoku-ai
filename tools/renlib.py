"""Read RenLib 3.x move trees without depending on the RenLib program.

Format facts were checked against Frank Arkbo's RenLib serialization:
https://github.com/gomoku/RenLib/blob/master/LibraryFile.cpp
https://github.com/gomoku/RenLib/blob/master/MoveNode.cpp
https://github.com/gomoku/RenLib/blob/master/RenLibDoc.cpp
This is an independently written parser; the above code is not incorporated.

The file's 0x80 flag denotes a pending sibling, and 0x40 ends a branch.
Neither the MARK nor START flag asserts a win. Missing branches and unlabelled
leaves must not be interpreted as complete winning proofs.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Iterator


@dataclass
class Library:
    # Node 0 is a synthetic, empty root. Positions are row*15+column,
    # both zero based; -1 is a pass/null position. depth counts records,
    # ply counts actual moves (including passes), so colour is 1 if ply odd.
    pos: array = field(default_factory=lambda: array('h', [-1]))
    parent: array = field(default_factory=lambda: array('i', [-1]))
    first_child: array = field(default_factory=lambda: array('i', [-1]))
    next_sibling: array = field(default_factory=lambda: array('i', [-1]))
    depth: array = field(default_factory=lambda: array('H', [0]))
    ply: array = field(default_factory=lambda: array('H', [0]))
    flags: array = field(default_factory=lambda: array('I', [2]))
    valid: array = field(default_factory=lambda: array('B', [1]))
    invalid_nodes: dict[int, str] = field(default_factory=dict)
    comments: dict[int, str] = field(default_factory=dict)
    board_text: dict[int, str] = field(default_factory=dict)
    version: tuple[int, int] = (0, 0)
    source_bytes: int = 0
    source_sha256: str = ''

    def children(self, node: int) -> Iterator[int]:
        child = self.first_child[node]
        while child != -1:
            yield child
            child = self.next_sibling[child]

    def path(self, node: int) -> list[int]:
        result = []
        while node > 0:
            result.append(node)
            node = self.parent[node]
        return result[::-1]

    def follow(self, positions: list[int]) -> int:
        node = 0
        for pos in positions:
            matches = [c for c in self.children(node) if self.pos[c] == pos]
            if len(matches) != 1:
                raise ValueError(f'expected one child at {pos}, found {len(matches)}')
            node = matches[0]
        return node


def read_library(path: str | Path, encoding: str = 'cp936', strict: bool = False) -> Library:
    """Parse and check every tree path for coordinate and occupancy validity.

    Comment bytes in the old files have no embedded charset declaration. The
    caller can override encoding; parsing boundaries do not depend on it.
    """
    raw = Path(path).read_bytes()
    if len(raw) < 20 or raw[:8] != b'\xffRenLib\xff':
        raise ValueError('not a headered RenLib file')
    if raw[8] != 3 or raw[9] > 4:
        raise ValueError(f'unsupported RenLib version {raw[8]}.{raw[9]}')
    lib = Library(version=(raw[8], raw[9]), source_bytes=len(raw),
                  source_sha256=hashlib.sha256(raw).hexdigest())
    cursor = 20
    last_child = array('i', [-1])
    pending: list[int] = []
    path_nodes = [0]
    occupied = [0] * 225
    parent = 0
    closed = False
    record = 0

    def pair() -> tuple[int, int]:
        nonlocal cursor
        if cursor + 2 > len(raw):
            raise ValueError(f'truncated record/string at byte {cursor}')
        a, b = raw[cursor], raw[cursor+1]
        cursor += 2
        return a, b

    def text(old: bool = False) -> str:
        value = bytearray()
        while True:
            chunk = pair()  # Strings are padded to an even byte length.
            stop = False
            for ch in chunk:
                if old:
                    value.append(ch & 127)
                    stop = bool(ch & 128)
                elif ch:
                    value.append(ch)
                else:
                    stop = True
                if stop:
                    break
            if stop:
                break
        if old:
            return value.decode('ascii').translate(str.maketrans('}{|][\\', 'åäöÅÄÖ'))
        return value.decode(encoding, errors='replace')

    while cursor < len(raw):
        if closed:
            raise ValueError(f'data follows completed tree at byte {cursor}')
        record += 1
        at = cursor
        encoded, flags = pair()
        if flags & 1:
            high, low = pair()
            flags |= high << 16 | low << 8
        pos = -1 if encoded == 0 else (encoded >> 4)*15 + (encoded & 15)-1
        if encoded and (encoded >> 4 >= 15 or not 1 <= (encoded & 15) <= 15):
            raise ValueError(f'invalid coordinate {encoded:#x} at byte {at}')
        comment = text(bool(flags & 32)) if flags & (8 | 32) else ''
        board_text = text() if flags & 256 else ''
        # Newer RenLib versions can explicitly serialize their empty root.
        if record == 1 and encoded == 0:
            node = 0
            lib.flags[0] = flags | 2
        else:
            while path_nodes[-1] != parent:
                popped = path_nodes.pop()
                if lib.pos[popped] >= 0 and not lib.flags[popped] & 2:
                    occupied[lib.pos[popped]] -= 1
            is_move = not flags & 2
            duplicate = is_move and pos >= 0 and occupied[pos] != 0
            if duplicate and strict:
                raise ValueError(f'occupied square {pos} at byte {at}, node {record}')
            node = len(lib.pos)
            lib.pos.append(pos)
            lib.parent.append(parent)
            lib.first_child.append(-1)
            lib.next_sibling.append(-1)
            lib.depth.append(lib.depth[parent] + 1)
            lib.ply.append(lib.ply[parent] + int(is_move))
            lib.flags.append(flags)
            lib.valid.append(int(bool(lib.valid[parent]) and not duplicate))
            if duplicate:
                lib.invalid_nodes[node] = f'occupied square {pos} at byte {at}'
            if last_child[parent] == -1:
                lib.first_child[parent] = node
            else:
                lib.next_sibling[last_child[parent]] = node
            last_child[parent] = node
            last_child.append(-1)
            path_nodes.append(node)
            if is_move and pos >= 0:
                occupied[pos] += 1
        if comment:
            lib.comments[node] = comment
        if board_text:
            lib.board_text[node] = board_text
        if flags & 128:
            pending.append(parent)
        parent = node
        if flags & 64:
            if pending:
                parent = pending.pop()
            else:
                closed = True
    if pending:
        raise ValueError(f'truncated branch list: {len(pending)} unresolved siblings')
    # A saved current line may legitimately omit the final 0x40 marker.
    return lib


def describe(lib: Library) -> dict:
    sizes = array('I', [1]) * len(lib.pos)
    leaves = array('I', [0 if c != -1 else 1 for c in lib.first_child])
    for node in range(len(lib.pos)-1, 0, -1):
        sizes[lib.parent[node]] += sizes[node]
        leaves[lib.parent[node]] += leaves[node]
    initial = lib.follow([7*15+7, 6*15+7, 6*15+8, 7*15+8])
    relevant = []
    stack = [initial]
    histogram = Counter()
    black_choices = 0
    while stack:
        node = stack.pop()
        children = list(lib.children(node))
        relevant.append(node)
        if lib.ply[node] % 2 == 0 and len(children) > 1:
            black_choices += 1
        histogram[lib.flags[node] & ~192] += 1
        stack.extend(children)
    def entry(node):
        return {'node': node, 'row': lib.pos[node]//15, 'col': lib.pos[node]%15,
                'ply': lib.ply[node], 'subtree_nodes': sizes[node],
                'subtree_leaves': leaves[node], 'flags': lib.flags[node],
                'comment': lib.comments.get(node, ''),
                'board_text': lib.board_text.get(node, '')}
    return {'source_sha256': lib.source_sha256, 'source_bytes': lib.source_bytes,
            'version': lib.version, 'nodes': len(lib.pos)-1,
            'max_ply': max(lib.ply), 'leaves': leaves[0],
            'comment_count': len(lib.comments), 'board_text_count': len(lib.board_text),
            'all_paths_occupancy_valid': not lib.invalid_nodes,
            'invalid_placements': len(lib.invalid_nodes),
            'invalid_nodes_including_descendants': len(lib.valid)-sum(lib.valid),
            'invalid_examples': list(lib.invalid_nodes.items())[:20],
            'initial_nodes': [entry(n) for n in lib.path(initial)],
            'initial_match_node': initial, 'relevant_nodes': len(relevant),
            'relevant_leaves': leaves[initial], 'black_multichoice_positions': black_choices,
            'relevant_invalid_nodes': sum(not lib.valid[n] for n in relevant),
            'relevant_nonstructural_flags': {hex(k):v for k,v in histogram.items()},
            'black_fifth_moves': [entry(n) for n in lib.children(initial)],
            'note': 'MARK/START are UI attributes, not proven win/loss labels. '
                    'This parser validates the tree, not the claimed strategy.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = describe(read_library(args.library))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        args.report.write_text(rendered, encoding='utf-8')
    print(rendered)
