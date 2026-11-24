#!/usr/bin/env python3
"""Reproduce the standalone, single-threaded course port of Rapfi.

Only classical evaluation and alpha-beta search are linked. The upstream
checkout is read-only; all changes are explicit here or in rapfi_port/.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'reference' / 'rapfi' / 'Rapfi'
PORT = ROOT / 'rapfi_port'
COMMIT = '1387d11312190ec66665d361ff07a7c70221b78a'
SOURCES = [
    'core/hash.cpp', 'core/iohelper.cpp', 'core/utils.cpp', 'core/platform.cpp',
    'eval/classicalpolicy.cpp', 'eval/eval.cpp', 'eval/evaluator.cpp',
    'game/pattern.cpp', 'game/board.cpp', 'game/movegen.cpp',
    'search/hashtable.cpp', 'search/movepick.cpp', 'search/opening.cpp',
    'search/searchcommon.cpp', 'search/searchconfig.cpp',
    'search/searchthread.cpp', 'search/timecontrol.cpp',
    'search/ab/history.cpp', 'search/ab/search.cpp', 'search/searchoutput.cpp',
    'search/searchengine.cpp',
]

DBSTORAGE = '''#pragma once
namespace Database { class DBStorage { public: virtual ~DBStorage() = default; }; }
'''
DBCLIENT = '''#pragma once
#include "dbstorage.h"
#include "dbtypes.h"
class Board;
namespace Database {
inline bool checkOverwrite(const DBRecord&, const DBRecord&, OverwriteRule, int, int) { return false; }
inline bool checkOverwrite(const DBRecord&, const DBRecord&, OverwriteRule) { return false; }
class DBClient {
    DBStorage& storage;
public:
    DBClient(DBStorage& s, DBRecordMask, size_t=0, size_t=0): storage(s) {}
    DBStorage& getStorage() const { return storage; }
    bool query(const Board&, Rule, DBRecord&) { return false; }
    std::vector<std::pair<Pos,DBRecord>> queryChildren(const Board&, Rule) { return {}; }
    bool save(const Board&, Rule, const DBRecord&, OverwriteRule) { return false; }
    void sync(bool=true) {}
};
}
'''
PLATFORM = '''#include "platform.h"
#include <cstdlib>
#include <limits>
namespace Numa { NumaNodeId bindThisThread(size_t) { return DefaultNumaNodeId; } }
namespace MemAlloc {
void* alignedAlloc(size_t alignment, size_t size) {
    alignment = std::max(alignment, sizeof(void*));
    if (size > std::numeric_limits<size_t>::max() - alignment - sizeof(void*)) return nullptr;
    void* raw = std::malloc(size + alignment + sizeof(void*));
    if (!raw) return nullptr;
    uintptr_t addr = (reinterpret_cast<uintptr_t>(raw) + sizeof(void*) + alignment-1) & ~(alignment-1);
    void* aligned = reinterpret_cast<void*>(addr);
    reinterpret_cast<void**>(aligned)[-1] = raw;
    return aligned;
}
void alignedFree(void* p) { if(p) std::free(reinterpret_cast<void**>(p)[-1]); }
void* alignedLargePageAlloc(size_t size) { return alignedAlloc(4096, size); }
void alignedLargePageFree(void* p) { alignedFree(p); }
}
'''

def replace_function(text, signature, body):
    """Replace exactly one body, retaining its signature."""
    start = text.index(signature)
    left = text.index('{', start)
    depth = 1
    right = left + 1
    while depth:
        depth += (text[right] == '{') - (text[right] == '}')
        right += 1
    return text[:left] + '{' + body + '}' + text[right:]

def transformed(rel):
    if rel == 'database/dbstorage.h': return DBSTORAGE
    if rel == 'database/dbclient.h': return DBCLIENT
    if rel == 'core/platform.cpp': return PLATFORM
    text = (UPSTREAM / rel).read_text(encoding='utf-8-sig')
    # Optional training instrumentation is never part of a competition binary.
    text = re.sub(r'^\s*#\s*include\s+"[^"\n]*tuning/[^"\n]*".*$', '', text, flags=re.M)
    if rel == 'core/hash.h':
        text = text.replace('#include <xxhash.h>', '')
        begin = text.index('class XXHasher')
        end = text.index('/// Per-(color', begin)
        text = text[:begin] + text[end:]
    elif rel == 'core/utils.cpp':
        text = '#include "string.h"\n#include "time.h"\n#include <chrono>\n#include <algorithm>\n' + text[text.index('Time now()'):text.index('// String encoding conversion')]
    elif rel == 'core/iohelper.cpp':
        text = re.sub(r'#include <mutex>', '', text)
        begin = text.index('namespace {')
        end = text.index('SyncOutputStream::SyncOutputStream', begin)
        text = text[:begin] + text[end:]
        text = text.replace('syncIOMutex().lock();', '').replace('syncIOMutex().unlock();', '')
    elif rel == 'core/iohelper.h':
        # Diagnostics never share the course protocol's stdout.
        text = text.replace('sync_cout() << "MESSAGE ', 'std::cerr << "MESSAGE ')
        text = text.replace('sync_cout() << "ERROR ', 'std::cerr << "ERROR ')
    elif rel == 'search/searchengine.cpp':
        text = text.replace('#include "mcts/searcher.h"', '')
        text = re.sub(r'    if \(searcherName == "MCTS"\)\s*return std::make_unique<MCTS::MCTSSearcher>\(\);', '', text)
    elif rel == 'search/opening.cpp':
        # PASS has no physical coordinates. Imported test positions and null
        # histories may contain it before a real edge opening stone.
        old = '        Pos pos = board.getHistoryMove(i);\n\n        if (isNearBorder'
        new = '        Pos pos = board.getHistoryMove(i);\n        if (pos == Pos::PASS) continue;\n\n        if (isNearBorder'
        if text.count(old) != 1:
            raise RuntimeError('Upstream opening pass guard anchor changed')
        text = text.replace(old, new)
    elif rel == 'search/hashtable.cpp':
        text = text.replace('#include "../core/compressor.h"', '')
        text = replace_function(text, 'void HashTable::dump', '\n    (void)outStream;\n')
        text = replace_function(text, 'bool HashTable::load', '\n    (void)inStream; return false;\n')
    elif rel == 'search/searchoutput.cpp':
        # Retain the public API without any Piskvork output or file dependencies.
        methods = list(re.finditer(r'(?:void|bool) SearchPrinter::\w+\(', text))
        for match in reversed(methods):
            text = replace_function(text, match.group(0), ' return false; ' if match.group(0).startswith('bool') else '')
    return text

def strip_comments(text):
    # Tokenize strings before comments so comment-like text in literals survives.
    token = re.compile(r'R"([^ ()\\\t\r\n]{0,16})\([\s\S]*?\)\1"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')
    return token.sub(lambda m: '\n' * m.group(0).count('\n') if m.group(0).startswith(('//','/*')) else m.group(0), text)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='builtin', choices=['builtin', 'trained'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--keep-comments', action='store_true')
    parser.add_argument('--clean-warnings', action='store_true',
                        help='Generate a separate warning-clean candidate; preserve v4 defaults')
    args = parser.parse_args()
    if args.clean_warnings and args.keep_comments:
        parser.error('--clean-warnings requires the normalized source (omit --keep-comments)')
    if args.output is None:
        args.output = PORT / ('rapfi_warning_clean.cpp' if args.clean_warnings else
                              'rapfi_trained.cpp' if args.model == 'trained' else 'rapfi_classical.cpp')
    seen = set()
    ordered = []

    def expand(rel):
        rel = Path(rel).as_posix()
        if rel in seen: return ''
        seen.add(rel)
        ordered.append(rel)
        text = transformed(rel)
        def include(match):
            path = (UPSTREAM / rel).parent / match.group(1)
            path = path.resolve().relative_to(UPSTREAM.resolve()).as_posix()
            return expand(path)
        text = re.sub(r'^\s*#\s*include\s+"([^"\n]+)"[^\n]*$', include, text, flags=re.M)
        text = re.sub(r'^\s*#pragma once[^\n]*$', '', text, flags=re.M)
        if not args.keep_comments:
            text = strip_comments(text)
            text = '\n'.join(line.rstrip() for line in text.splitlines() if line.strip())
        return f'\n// BEGIN Rapfi/{rel}\n{text}\n// END Rapfi/{rel}\n'

    # Headers before definitions establish shared declarations consistently.
    pieces = [expand(p) for p in ['config.h', 'eval/evalconfig.h', 'eval/scoretables.h', 'database/dbconfig.h']]
    pieces.append('''
namespace Config { GeneralConfig GeneralCfg; }
namespace Evaluation {
EvaluatorConfig EvalCfg;
Eval EVALS[RULE_NB+1][PCODE_NB];
Eval EVALS_THREAT[RULE_NB+1][THREAT_NB];
MoveScorePair P4SCORES[RULE_NB+1][PCODE_NB];
}
namespace Database { DatabaseConfig DatabaseCfg; }
''')
    pieces += [expand(p) for p in SOURCES]
    pieces.append((PORT / 'assets' / f'classical_{args.model}.inc').read_text(encoding='utf-8-sig'))
    pieces.append('''
namespace CoursePort {
void initializeCore() {
    static const bool initialized = [] {
        initializeEmbeddedClassicalModel();
        Config::GeneralCfg.messageMode = MsgMode::NONE;
        Config::GeneralCfg.defaultThreadNum = 1;
        Search::Engine.setNumThreads(1);
        Search::Engine.searcher()->setMemoryLimit(64 * 1024);
        return true;
    }();
    (void)initialized;
}
}
''')
    pieces.append((PORT / 'course_protocol.inc').read_text(encoding='utf-8-sig'))
    license_text = (UPSTREAM / 'game/board.cpp').read_text(encoding='utf-8-sig').split('*/', 1)[0] + '*/\n'
    preamble = f'''// Course adaptation of https://github.com/dotb1ue/rapfi
// Upstream revision: {COMMIT}
// Generated by gomoku/tools/build_rapfi.py; classical model: {args.model}.
// Changes: one synchronous thread; embedded classical evaluation; course I/O;
// no NNUE/MCTS/database/filesystem/model loading; portable memory and time;
// no Piskvork output; no persistent hash import/export. GPL-3.0-or-later.
// Opening candidate expansion skips PASS sentinel positions.
// See accompanying COPYING and AUTHORS for license and contributors.
#if !defined(NDEBUG) && !defined(RAPFI_COURSE_DEBUG)
#define NDEBUG
#endif
#ifdef MULTI_THREADING
#undef MULTI_THREADING
#endif
#include <algorithm>
#include <cctype>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <iostream>
#include <limits>
#include <sstream>
#include <vector>
'''
    result = license_text + preamble + ''.join(pieces)
    warning_changes = []
    if args.clean_warnings:
        from rapfi_warning_cleanup import clean_warnings
        result, warning_changes = clean_warnings(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding='utf-8', newline='\n')
    size = len(result.encode('utf-8'))
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        'upstream_repository': 'https://github.com/dotb1ue/rapfi',
        'upstream_revision': COMMIT,
        'source_license': 'GPL-3.0-or-later',
        'classical_model': args.model,
        'output': args.output.name,
        'bytes': size,
        'lines': len(result.splitlines()),
        'sha256': digest(args.output),
        'required_language': 'C++17',
        'worker_threads': 0,
        'transposition_table_kib': 64 * 1024,
        'runtime_external_files': [],
        'upstream_inputs': {p: digest(UPSTREAM / p) for p in ordered},
        'port_inputs': {p: digest(PORT / p) for p in [
            'course_protocol.inc', f'assets/classical_{args.model}.inc']},
    }
    if args.clean_warnings:
        manifest['warning_cleanup'] = warning_changes
        manifest['warning_cleanup_script_sha256'] = digest(ROOT / 'tools/rapfi_warning_cleanup.py')
    args.output.with_suffix('.manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{args.output}: {size:,} bytes, {len(result.splitlines()):,} lines, {len(ordered)} upstream files')
    if size > 1048576:
        raise SystemExit('Source exceeds the 1 MiB course limit')

if __name__ == '__main__':
    main()
