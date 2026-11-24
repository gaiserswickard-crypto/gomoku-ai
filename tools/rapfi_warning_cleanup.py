"""Conservative, checked source rewrites for the optional Rapfi warning cleanup.

These edits change declarations and spelling, not parameters, weights or search
decisions. Exact-match counts deliberately fail when the upstream port changes.
"""
import re


def clean_warnings(text):
    changes = []

    def replace(old, new, count=1, label=None):
        nonlocal text
        actual = text.count(old)
        if actual != count:
            raise ValueError(f'warning cleanup anchor {label or old[:70]!r}: {actual} != {count}')
        text = text.replace(old, new)
        changes.append({'change': label or old[:90], 'occurrences': count})

    # Preserve the enum's uint8_t representation and sentinel's Pattern type.
    # Only real patterns (DEAD..F5, 0..15) are stored in the four-bit fields.
    replace('    F5,\n    PATTERN_NB\n};',
            '    F5\n};\ninline constexpr Pattern PATTERN_NB = static_cast<Pattern>(16);\n'
            'static_assert(F5 == 15 && PATTERN_NB == 16);', label='pattern count outside enumerators')
    replace('    return ((unsigned __int128)a * (unsigned __int128)b) >> 64;',
            '    __extension__ typedef unsigned __int128 UInt128;\n'
            '    return (static_cast<UInt128>(a) * static_cast<UInt128>(b)) >> 64;',
            label='explicit GNU 128-bit extension, same multiplication')
    replace('constexpr int arraySize(ElemType (&arr)[Size])',
            'constexpr int arraySize(ElemType (&)[Size])')
    replace('for (size_t backIndex = 0; backIndex < arraySize(plyBack); backIndex++)',
            'for (int backIndex = 0; backIndex < arraySize(plyBack); backIndex++)')
    replace('bool checkP4(const Board *board)', '[[maybe_unused]] bool checkP4(const Board *board)')
    # All seven members are explicitly initialized to their former zero values.
    # CandArea's normal default constructor is intentionally not substituted.
    replace('    std::memset(&st, 0, sizeof(StateInfo));',
            '    st = StateInfo {0, CandArea(0, 0, 0, 0), Pos::NONE, {}, {}, {}, VALUE_ZERO};',
            label='StateInfo exact member-wise zero initialization')
    replace('Value          bestValue = -VALUE_INFINITE, value;',
            'Value          bestValue = -VALUE_INFINITE, value = VALUE_NONE;',
            label='explicit search scratch value initialization')

    # Parentheses follow existing C++ precedence (&& binds more tightly than ||).
    replace('|| pattern4(posi, BLACK) == FORBID && pattern(posi, BLACK, dir) == F4\n'
            '                           && !checkForbiddenPoint(posi)',
            '|| (pattern4(posi, BLACK) == FORBID && pattern(posi, BLACK, dir) == F4\n'
            '                           && !checkForbiddenPoint(posi))', 2)
    replace('|| p4 == FORBID\n'
            '                       && (board.pattern(pos, side, 0) >= B4 || board.pattern(pos, side, 1) >= B4\n'
            '                           || board.pattern(pos, side, 2) >= B4\n'
            '                           || board.pattern(pos, side, 3) >= B4)',
            '|| (p4 == FORBID\n'
            '                       && (board.pattern(pos, side, 0) >= B4 || board.pattern(pos, side, 1) >= B4\n'
            '                           || board.pattern(pos, side, 2) >= B4\n'
            '                           || board.pattern(pos, side, 3) >= B4))')
    replace('|| R == RENJU && board.pattern4(pos, oppo) == FORBID && checkRenjuF4(pos)',
            '|| (R == RENJU && board.pattern4(pos, oppo) == FORBID && checkRenjuF4(pos))', 2)
    replace('|| R == Rule::RENJU && defendP4 == FORBID\n'
            '                                       && !board.checkForbiddenPoint(defendMove)',
            '|| (R == Rule::RENJU && defendP4 == FORBID\n'
            '                                       && !board.checkForbiddenPoint(defendMove))')
    replace('!PvNode && dbCut || db.labelBound == BOUND_LOWER && db.value >= beta\n'
            '            || db.labelBound == BOUND_UPPER && db.value <= alpha',
            '(!PvNode && dbCut) || (db.labelBound == BOUND_LOWER && db.value >= beta)\n'
            '            || (db.labelBound == BOUND_UPPER && db.value <= alpha)')
    replace('|| PvNode && ss->ply <= 1 + isLoss\n'
            '                   && options.multiPV > 1\n'
            '            || ss->ply <= writePly - isWin\n'
            '                   && (db.hit || depth >= writeDepth + isWin)\n'
            '            || db.hit && (isWin || isLoss)\n'
            '            || PvNode && db.hit\n'
            '                   && ss->ply\n'
            '                          <= (exact ? dbParams.exactOverwritePly : dbParams.nonExactOverwritePly)',
            '|| (PvNode && ss->ply <= 1 + isLoss\n'
            '                   && options.multiPV > 1)\n'
            '            || (ss->ply <= writePly - isWin\n'
            '                   && (db.hit || depth >= writeDepth + isWin))\n'
            '            || (db.hit && (isWin || isLoss))\n'
            '            || (PvNode && db.hit\n'
            '                   && ss->ply\n'
            '                          <= (exact ? dbParams.exactOverwritePly : dbParams.nonExactOverwritePly))')
    replace('|| mt.distSelf <= 4 && ss->moveP4[self] >= J_FLEX2_2X',
            '|| (mt.distSelf <= 4 && ss->moveP4[self] >= J_FLEX2_2X)')
    replace('ss->ttPv = PvNode || ttHit && ttIsPv;',
            'ss->ttPv = PvNode || (ttHit && ttIsPv);')
    replace('|| db.bound == BOUND_LOWER && db.value >= beta\n'
            '                  || db.bound == BOUND_UPPER && db.value <= alpha',
            '|| (db.bound == BOUND_LOWER && db.value >= beta)\n'
            '                  || (db.bound == BOUND_UPPER && db.value <= alpha)')
    replace('if (options.maxNodes && engine->nodesSearched() >= options.maxNodes\n'
            '        || options.timeLimit && engine->searcher()->checkTimeupCondition(timectl))',
            'if ((options.maxNodes && engine->nodesSearched() >= options.maxNodes)\n'
            '        || (options.timeLimit && engine->searcher()->checkTimeupCondition(timectl)))')

    # Name the previously anonymous TT payload. Storage and offsets are unchanged.
    old_tt = '''struct TTEntry
{
    uint32_t key32;
    union {
        struct
        {
            int16_t  value16;
            int16_t  eval16;
            uint16_t pvBoundBest16;
            uint8_t  depth8;
            uint8_t  generation8;
        };
        uint32_t data[2];
    };
    uint32_t key() const { return key32 ^ data[0] ^ data[1]; }
};'''
    new_tt = '''struct TTEntry
{
    struct Fields {
        int16_t  value16;
        int16_t  eval16;
        uint16_t pvBoundBest16;
        uint8_t  depth8;
        uint8_t  generation8;
    };
    uint32_t key32;
    union {
        Fields fields;
        uint32_t data[2];
    };
    uint32_t key() const { return key32 ^ data[0] ^ data[1]; }
};
static_assert(sizeof(TTEntry::Fields) == 8 && alignof(TTEntry) == 4);
static_assert(offsetof(TTEntry, fields) == 4 && offsetof(TTEntry, data) == 4);
static_assert(offsetof(TTEntry::Fields, value16) == 0 && offsetof(TTEntry::Fields, eval16) == 2);
static_assert(offsetof(TTEntry::Fields, pvBoundBest16) == 4);
static_assert(offsetof(TTEntry::Fields, depth8) == 6 && offsetof(TTEntry::Fields, generation8) == 7);'''
    replace(old_tt, new_tt, label='named TT payload with invariant offsets')
    start = text.index('// BEGIN Rapfi/search/hashtable.cpp')
    end = text.index('// END Rapfi/search/hashtable.cpp', start)
    block = text[start:end]
    block, count = re.subn(r'(\.|->)(value16|eval16|pvBoundBest16|depth8|generation8)\b',
                          r'\1fields.\2', block)
    if count != 18:
        raise ValueError(f'Unexpected TT member reference count: {count}')
    text = text[:start] + block + text[end:]
    changes.append({'change': 'qualify TT payload members', 'occurrences': count})

    replace('''        for (int i = -plyBeforeRoot; i < maxPly + plyAfterMax; i++)
            push_back(SearchStack {nextTriPvIndex(i), i});''',
            '''        for (int i = -plyBeforeRoot; i < maxPly + plyAfterMax; i++)
            push_back(SearchStack {nextTriPvIndex(i), i, 0, 0.0f, 0, 0, VALUE_ZERO,
                                   Pos::NONE, Pos::NONE, {}, {}, 0, false, false});''',
            label='fully initialized SearchStack aggregate')
    replace('{Database::LABEL_NULL, 0, 0};', '{Database::LABEL_NULL, 0, 0, {}};', 2)
    for method in ['beforeMove', 'afterMove', 'beforeUndo', 'afterUndo']:
        replace(f'virtual void {method}(const Board &board, Pos pos) {{}};',
                f'virtual void {method}(const Board &, Pos) {{}};')
    for method in ['afterPass', 'afterUndoPass']:
        replace(f'virtual void {method}(const Board &board) {{}};',
                f'virtual void {method}(const Board &) {{}};')
    replace('makeSearchData(SearchThread &th) override\n', 'makeSearchData(SearchThread &) override\n')
    replace('void ABSearchData::clearData(SearchThread &th)\n',
            'void ABSearchData::clearData(SearchThread &)\n')
    replace('void HistoryTracker::updateBestmoveStats(Depth depth, Pos bestMove, Value bestValue)\n',
            'void HistoryTracker::updateBestmoveStats(Depth depth, Pos bestMove, Value)\n')
    replace('[onStop = std::move(onStop)](SearchThread &th) { onStop(); }',
            '[onStop = std::move(onStop)](SearchThread &) { onStop(); }')

    # The port intentionally has no Piskvork stdout printer. Its no-op API keeps
    # argument types/signatures but does not need parameter identifiers.
    pattern = r'((?:void|bool) SearchPrinter::\w+)\((.*?)\)(\s*\{\s*(?:return false;\s*)?\})'
    def unnamed(match):
        params = ','.join(re.sub(r'\b[A-Za-z_]\w*\s*$', '', p) for p in match[2].split(','))
        return f'{match[1]}({params}){match[3]}'
    text, count = re.subn(pattern, unnamed, text, flags=re.S)
    if count != 13:
        raise ValueError(f'Unexpected no-op printer method count: {count}')
    changes.append({'change': 'unnamed no-op printer parameters', 'occurrences': count})
    # Track the start of the optional NNUE object's lifetime explicitly. This
    # keeps its storage uninitialized when using the classical evaluator.
    replace('PolicyBuffer       *policyBuf = reinterpret_cast<PolicyBuffer *>(&policyBufferStorage);',
            'PolicyBuffer       *policyBuf = nullptr;')
    replace('new (policyBuf) Evaluation::PolicyBuffer(board.size());',
            'policyBuf = new (&policyBufferStorage) Evaluation::PolicyBuffer(board.size());')
    replace('''    if (useNormalizedPolicy) {
        if (hasPolicy) {
            assert(evaluator);
            policyBuf->applySoftmax();''',
            '''    if (useNormalizedPolicy) {
        if (useEvaluatorPolicy) {
            assert(evaluator);
            policyBuf->applySoftmax();''',
            label='guard optional policy access by same-call construction condition')
    return text, changes
