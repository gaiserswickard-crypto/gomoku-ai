// C++17, single-file brain for the 2026 12x12 freestyle Gomoku contest.
// Coordinates are (row, column). All search changes are undone before returning.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace gomoku {
constexpr int N = 12, CELLS = N * N;
constexpr int MATE = 100000000, INF = 110000000;
constexpr int MAX_PLY = 120, TABLE_SIZE = 1 << 20;
constexpr int POW3[8] = {1,3,9,27,81,243,729,2187};
constexpr int DR[4] = {0,1,1,1}, DC[4] = {1,0,1,-1};
using Clock = std::chrono::steady_clock;

struct Pattern {
    int value = 0;
    unsigned char five = 0, wins = 0, three = 0;
};
struct Potential {
    int value = 0;
    unsigned char five = 0, wins = 0, threes = 0;
};
struct Link { short pos; unsigned char dir; short weight; };
struct Move { int pos, order; bool tactical; };
struct TTEntry {
    std::uint64_t key = 0;
    int value = 0;
    short move = -1, depth = -1;
    unsigned char flag = 0;
};

class Engine {
    std::array<int, CELLS> cells_{};
    std::array<int, CELLS> near_{};
    int codes_[3][CELLS][4]{};
    Potential potential_[3][CELLS]{};
    std::array<Pattern, 6561> patterns_{};
    std::array<std::vector<Link>, CELLS> links_;
    std::array<std::vector<int>, CELLS> neighbors_;
    std::uint64_t zobrist_[3][CELLS]{}, sideKey_[3]{};
    std::uint64_t hash_ = 0;
    std::vector<TTEntry> table_;
    int occupied_ = 0;
    int history_[3][CELLS]{};
    int killers_[MAX_PLY][2]{};
    Clock::time_point deadline_, proofDeadline_;
    bool aborted_ = false, proofAborted_ = false;
    std::uint64_t nodes_ = 0, proofNodes_ = 0;
    int completedDepth_ = 0, lastScore_ = 0;

    static bool inside(int r, int c) { return r >= 0 && r < N && c >= 0 && c < N; }
    static std::uint64_t random64(std::uint64_t& x) {
        x += 0x9e3779b97f4a7c15ULL;
        std::uint64_t z = x;
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return z ^ (z >> 31);
    }

    // A line has eight ternary digits around a hypothetical friendly center.
    // Enemy stones and board edges both have digit 2. Deduplicating winning
    // squares distinguishes a straight open four from a single broken four.
    void buildPatterns() {
        std::array<int, 6561> maxStones{};
        for (int code = 0; code < 6561; ++code) {
            int line[9], x = code;
            for (int i = 0; i < 9; ++i) {
                if (i == 4) line[i] = 1;
                else { line[i] = x % 3; x /= 3; }
            }
            unsigned int wins = 0;
            for (int start = 0; start <= 4; ++start) {
                int stones = 0, empty = -1;
                bool blocked = false;
                for (int j = start; j < start + 5; ++j) {
                    if (line[j] == 2) { blocked = true; break; }
                    if (line[j] == 1) ++stones; else empty = j;
                }
                if (blocked) continue;
                maxStones[code] = std::max(maxStones[code], stones);
                if (stones == 5) patterns_[code].five = 1;
                if (stones == 4) wins |= 1U << empty;
            }
            int count = 0;
            for (; wins; wins &= wins - 1) ++count;
            patterns_[code].wins = static_cast<unsigned char>(count);
        }
        for (int code = 0; code < 6561; ++code) {
            Pattern& p = patterns_[code];
            if (p.five) { p.value = 8000000; continue; }
            if (p.wins >= 2) { p.value = 900000; continue; }
            if (p.wins == 1) { p.value = 14000; continue; }
            bool closedThree = false;
            for (int k = 0; k < 8; ++k) if (code / POW3[k] % 3 == 0) {
                const Pattern& next = patterns_[code + POW3[k]];
                if (!next.five && next.wins >= 2) p.three = 1;
                if (next.wins) closedThree = true;
            }
            p.value = p.three ? 3000 : (closedThree ? 400 : 0);
        }
        for (int code = 0; code < 6561; ++code) {
            Pattern& p = patterns_[code];
            if (p.value) continue;
            bool openTwo = false;
            for (int k = 0; k < 8; ++k) if (code / POW3[k] % 3 == 0)
                if (patterns_[code + POW3[k]].three) openTwo = true;
            p.value = openTwo ? 160 : (maxStones[code] >= 2 ? 35 : 3);
        }
    }

    Potential combine(int color, int pos) const {
        Potential result;
        for (int d = 0; d < 4; ++d) {
            const Pattern& p = patterns_[codes_[color][pos][d]];
            result.value += p.value;
            result.five |= p.five;
            result.wins = static_cast<unsigned char>(result.wins + p.wins);
            result.threes = static_cast<unsigned char>(result.threes + p.three);
        }
        if (result.five) result.value = 8000000;
        else if (result.wins >= 2) result.value += 900000;
        else if (result.wins && result.threes) result.value += 180000;
        else if (result.threes >= 2) result.value += 70000;
        return result;
    }

    // Only centers on the four lines through a changed square are affected.
    void update(int pos, int color, int sign) {
        hash_ ^= zobrist_[color][pos];
        occupied_ += sign;
        for (int q : neighbors_[pos]) near_[q] += sign;
        for (const Link& link : links_[pos]) {
            for (int side = 1; side <= 2; ++side) {
                codes_[side][link.pos][link.dir] += sign * link.weight * (side == color ? 1 : 2);
                potential_[side][link.pos] = combine(side, link.pos);
            }
        }
    }

    bool timeUp() {
        ++nodes_;
        if ((nodes_ & 127) == 0 && Clock::now() >= deadline_) aborted_ = true;
        return aborted_;
    }
    int winSquares(int side, int& first) const {
        int count = 0;
        first = -1;
        for (int p = 0; p < CELLS; ++p) if (!cells_[p] && potential_[side][p].five) {
            if (first < 0) first = p;
            ++count;
        }
        return count;
    }

    std::vector<Move> generate(int side, int ply, int depth, int ttMove, bool forcing) const {
        std::vector<Move> moves;
        moves.reserve(CELLS);
        int other = 3 - side;
        for (int p = 0; p < CELLS; ++p) {
            if (cells_[p] || (!near_[p] && occupied_)) continue;
            const Potential& a = potential_[side][p];
            const Potential& b = potential_[other][p];
            if (forcing && !a.wins) continue;
            bool tactical = a.wins || b.wins || a.threes || b.threes;
            int order = 2 * a.value + b.value * 2;
            order += 24 - std::abs(2*(p/N)-11) - std::abs(2*(p%N)-11);
            if (!forcing) {
                order += history_[side][p];
                if (ply < MAX_PLY && (killers_[ply][0] == p || killers_[ply][1] == p)) order += 500;
                if (p == ttMove) order += 50000000;
            }
            moves.push_back({p, order, tactical});
        }
        std::sort(moves.begin(), moves.end(), [](const Move& a, const Move& b) {
            return a.order != b.order ? a.order > b.order : a.pos < b.pos;
        });
        if (!forcing) {
            const int limit = ply == 0 ? 28 : (depth >= 4 ? 20 : 14);
            // Keep every tactical candidate, even when quiet moves are capped.
            int quietKept = 0;
            moves.erase(std::remove_if(moves.begin(), moves.end(), [&](const Move& m) {
                return !m.tactical && ++quietKept > limit;
            }), moves.end());
        }
        return moves;
    }

    int evaluate(int side) const {
        int sum[3]{}, best[3]{};
        for (int p = 0; p < CELLS; ++p) if (!cells_[p] && near_[p]) {
            for (int c = 1; c <= 2; ++c) {
                // Forced wins are resolved by search; cap speculative combinations.
                int v = std::min(potential_[c][p].value, 200000);
                best[c] = std::max(best[c], v);
                sum[c] += v;
            }
        }
        int other = 3 - side;
        return (best[side] * 5 - best[other] * 4) / 4 + (sum[side] - sum[other]) / 12;
    }

    // Tactical leaf search: winning moves, compulsory blocks, continuous fours.
    int quiescence(int side, int alpha, int beta, int ply, int remaining) {
        if (timeUp()) return 0;
        int own, enemy;
        if (winSquares(side, own)) return MATE - ply - 1;
        int enemyCount = winSquares(3-side, enemy);
        if (enemyCount >= 2) return -MATE + ply + 2;
        if (occupied_ == CELLS) return 0;
        if (ply >= MAX_PLY-2) return evaluate(side);
        if (enemyCount == 1) {
            setStone(enemy, side);
            int value = -quiescence(3-side, -beta, -alpha, ply+1, remaining-1);
            undoStone(enemy);
            return value;
        }
        // Creating two distinct immediate winning points is a proved win.
        for (int p = 0; p < CELLS; ++p)
            if (!cells_[p] && potential_[side][p].wins >= 2) return MATE-ply-3;
        int stand = evaluate(side);
        if (remaining <= 0) return stand;
        if (stand >= beta) return stand;
        alpha = std::max(alpha, stand);
        auto moves = generate(side, ply, 0, -1, true);
        for (const Move& m : moves) {
            setStone(m.pos, side);
            int value = -quiescence(3-side, -beta, -alpha, ply+1, remaining-1);
            undoStone(m.pos);
            if (aborted_) return 0;
            if (value >= beta) return value;
            alpha = std::max(alpha, value);
        }
        return alpha;
    }

    static int toTT(int value, int ply) {
        if (value > MATE-1000) return value+ply;
        if (value < -MATE+1000) return value-ply;
        return value;
    }
    static int fromTT(int value, int ply) {
        if (value > MATE-1000) return value-ply;
        if (value < -MATE+1000) return value+ply;
        return value;
    }

    int search(int side, int depth, int alpha, int beta, int ply) {
        if (timeUp()) return 0;
        int own, enemy;
        if (winSquares(side, own)) return MATE-ply-1;
        int enemyCount = winSquares(3-side, enemy);
        if (enemyCount >= 2) return -MATE+ply+2;
        if (occupied_ == CELLS) return 0;
        if (ply >= MAX_PLY-2) return evaluate(side);
        if (depth <= 0) return quiescence(side, alpha, beta, ply, 8);

        std::uint64_t key = hash_ ^ sideKey_[side];
        TTEntry saved = table_[key & (TABLE_SIZE-1)];
        int ttMove = -1, originalAlpha = alpha;
        if (saved.key == key) {
            ttMove = saved.move;
            int value = fromTT(saved.value, ply);
            if (saved.depth >= depth) {
                if (saved.flag == 0) return value;
                if (saved.flag == 1 && value >= beta) return value;
                if (saved.flag == 2 && value <= alpha) return value;
            }
        }
        std::vector<Move> moves;
        if (enemyCount == 1) moves.push_back({enemy, 0, true});
        else {
            for (int p = 0; p < CELLS; ++p) if (!cells_[p] && potential_[side][p].wins >= 2)
                return MATE-ply-3;
            moves = generate(side, ply, depth, ttMove, false);
        }
        if (moves.empty()) return 0;
        int best = -INF, bestMove = moves[0].pos, index = 0;
        for (const Move& move : moves) {
            setStone(move.pos, side);
            // Forced blocks do not consume the normal depth; stone count bounds them.
            int nextDepth = depth - (enemyCount == 1 ? 0 : 1);
            int value;
            if (index == 0) value = -search(3-side, nextDepth, -beta, -alpha, ply+1);
            else {
                int reduction = (depth >= 3 && index >= 5 && !move.tactical) ? 1 : 0;
                if (depth >= 6 && index >= 12 && !move.tactical) ++reduction;
                value = -search(3-side, std::max(0,nextDepth-reduction), -alpha-1, -alpha, ply+1);
                if (!aborted_ && reduction && value > alpha)
                    value = -search(3-side, nextDepth, -alpha-1, -alpha, ply+1);
                if (!aborted_ && value > alpha && value < beta)
                    value = -search(3-side, nextDepth, -beta, -alpha, ply+1);
            }
            undoStone(move.pos);
            if (aborted_) return 0;
            if (value > best) { best = value; bestMove = move.pos; }
            alpha = std::max(alpha, value);
            if (alpha >= beta) {
                if (!move.tactical) {
                    int& h = history_[side][move.pos];
                    h = std::min(2000, h + depth*depth);
                    killers_[ply][1] = killers_[ply][0]; killers_[ply][0] = move.pos;
                }
                break;
            }
            ++index;
        }
        TTEntry& entry = table_[key & (TABLE_SIZE-1)];
        entry.key = key; entry.depth = static_cast<short>(depth);
        entry.move = static_cast<short>(bestMove); entry.value = toTT(best, ply);
        entry.flag = best <= originalAlpha ? 2 : (best >= beta ? 1 : 0);
        return best;
    }

    // VCF = victory by continuous fours. Only forced replies are followed.
    // A timeout or depth limit means "unknown", never a claimed forced loss.
    bool proveFours(int side, int remaining, int& firstMove) {
        ++proofNodes_;
        if ((proofNodes_ & 63) == 0 && Clock::now() >= proofDeadline_) proofAborted_ = true;
        if (proofAborted_) return false;
        int own, enemy;
        if (winSquares(side, own)) { firstMove = own; return true; }
        int enemyCount = winSquares(3-side, enemy);
        if (enemyCount >= 2 || remaining <= 0) return false;
        auto moves = generate(side, 0, 0, -1, true);
        for (const Move& m : moves) {
            if (enemyCount == 1 && m.pos != enemy) continue;
            setStone(m.pos, side);
            int reply, counter;
            int threats = winSquares(side, reply);
            bool success = false;
            if (!winSquares(3-side, counter)) {
                if (threats >= 2) success = true;
                else if (threats == 1) {
                    setStone(reply, 3-side);
                    int ignored = -1;
                    success = proveFours(side, remaining-2, ignored);
                    undoStone(reply);
                }
            }
            undoStone(m.pos);
            if (proofAborted_) return false;
            if (success) { firstMove = m.pos; return true; }
        }
        return false;
    }

public:
    Engine() : table_(TABLE_SIZE) {
        buildPatterns();
        std::uint64_t seed = 0x61bdaed08abc1234ULL;
        for (int c = 1; c <= 2; ++c) {
            sideKey_[c] = random64(seed);
            for (int p = 0; p < CELLS; ++p) zobrist_[c][p] = random64(seed);
        }
        for (int p = 0; p < CELLS; ++p) {
            int r = p/N, c = p%N;
            for (int d = 0; d < 4; ++d) for (int offset = -4; offset <= 4; ++offset) {
                if (!offset) continue;
                int qr = r - offset*DR[d], qc = c - offset*DC[d];
                int digit = offset < 0 ? offset+4 : offset+3;
                if (inside(qr,qc)) links_[p].push_back({static_cast<short>(qr*N+qc),static_cast<unsigned char>(d),static_cast<short>(POW3[digit])});
            }
            for (int dr = -2; dr <= 2; ++dr) for (int dc = -2; dc <= 2; ++dc)
                if ((dr || dc) && inside(r+dr,c+dc)) neighbors_[p].push_back((r+dr)*N+c+dc);
        }
        reset();
    }

    void reset(bool initial = true) {
        cells_.fill(0); near_.fill(0); occupied_ = 0; hash_ = 0;
        for (int c = 1; c <= 2; ++c) for (int p = 0; p < CELLS; ++p) {
            history_[c][p] = 0;
            for (int d = 0; d < 4; ++d) {
                codes_[c][p][d] = 0;
                for (int off = -4; off <= 4; ++off) {
                    if (!off) continue;
                    int digit = off < 0 ? off+4 : off+3;
                    if (!inside(p/N+off*DR[d],p%N+off*DC[d])) codes_[c][p][d] += 2*POW3[digit];
                }
            }
            potential_[c][p] = combine(c,p);
        }
        for (auto& pair : killers_) pair[0] = pair[1] = -1;
        std::fill(table_.begin(), table_.end(), TTEntry{});
        if (initial) {
            setStone(5*N+5,2); setStone(6*N+6,2);
            setStone(5*N+6,1); setStone(6*N+5,1);
        }
    }
    const std::array<int,CELLS>& board() const { return cells_; }
    bool setStone(int pos, int color) {
        if (pos < 0 || pos >= CELLS || cells_[pos] || (color != 1 && color != 2)) return false;
        cells_[pos] = color; update(pos,color,1); return true;
    }
    void undoStone(int pos) {
        if (pos < 0 || pos >= CELLS || !cells_[pos]) return;
        int color = cells_[pos]; cells_[pos] = 0; update(pos,color,-1);
    }
    bool winsAt(int pos) const {
        if (pos < 0 || pos >= CELLS || !cells_[pos]) return false;
        for (int d = 0; d < 4; ++d) {
            int count = 1;
            for (int sign : {-1,1}) for (int step = 1; step < N; ++step) {
                int r = pos/N + sign*step*DR[d], c = pos%N + sign*step*DC[d];
                if (!inside(r,c) || cells_[r*N+c] != cells_[pos]) break;
                ++count;
            }
            if (count >= 5) return true;
        }
        return false;
    }
    bool verifyState() const {
        std::uint64_t h = 0; int count = 0;
        for (int p = 0; p < CELLS; ++p) {
            if (cells_[p]) { h ^= zobrist_[cells_[p]][p]; ++count; }
            int neighbors = 0;
            for (int q : neighbors_[p]) if (cells_[q]) ++neighbors;
            if (neighbors != near_[p]) return false;
            for (int color = 1; color <= 2; ++color) {
                for (int d = 0; d < 4; ++d) {
                    int code = 0;
                    for (int off = -4; off <= 4; ++off) if (off) {
                        int r = p/N+off*DR[d], c = p%N+off*DC[d];
                        int digit = off < 0 ? off+4 : off+3;
                        int value = !inside(r,c) ? 2 : (!cells_[r*N+c] ? 0 : (cells_[r*N+c] == color ? 1 : 2));
                        code += value*POW3[digit];
                    }
                    if (code != codes_[color][p][d]) return false;
                }
                Potential a = combine(color,p), b = potential_[color][p];
                if (a.value != b.value || a.five != b.five || a.wins != b.wins || a.threes != b.threes) return false;
            }
        }
        return h == hash_ && count == occupied_;
    }
    int depth() const { return completedDepth_; }
    int score() const { return lastScore_; }
    std::uint64_t nodes() const { return nodes_+proofNodes_; }

    int chooseMove(int side, int budgetMs = 1400) {
        auto start = Clock::now();
        deadline_ = start + std::chrono::milliseconds(std::max(1,budgetMs));
        aborted_ = proofAborted_ = false; nodes_ = proofNodes_ = 0;
        completedDepth_ = 0; lastScore_ = 0;
        if (occupied_ == CELLS || (side != 1 && side != 2)) return -1;
        for (int c = 1; c <= 2; ++c) for (int p = 0; p < CELLS; ++p) history_[c][p] /= 2;
        int own, enemy;
        if (winSquares(side,own)) return own;
        int enemyCount = winSquares(3-side,enemy);
        if (enemyCount) return enemy;
        for (int p = 0; p < CELLS; ++p)
            if (!cells_[p] && potential_[side][p].wins >= 2) return p;
        auto root = generate(side,0,1,-1,false);
        if (root.empty()) {
            for (int p = 0; p < CELLS; ++p) if (!cells_[p]) return p;
            return -1;
        }
        int bestMove = root[0].pos;
        if (root.size() == 1) return bestMove;
        proofDeadline_ = start + std::chrono::milliseconds(std::max(1,budgetMs/8));
        int proofMove = -1;
        if (proveFours(side,24,proofMove)) { lastScore_ = MATE-25; return proofMove; }
        std::vector<int> previous(CELLS,-INF);
        for (int depth = 1; depth <= 20; ++depth) {
            if (Clock::now() >= deadline_) break;
            std::stable_sort(root.begin(),root.end(),[&](const Move& a,const Move& b) {
                if (a.pos == bestMove) return b.pos != bestMove;
                if (b.pos == bestMove) return false;
                return previous[a.pos] > previous[b.pos];
            });
            int iterationBest = bestMove, valueBest = -INF, alpha = -INF;
            std::vector<int> scores(CELLS,-INF);
            bool complete = true;
            int index = 0;
            for (const Move& move : root) {
                if (Clock::now() >= deadline_) { complete = false; break; }
                setStone(move.pos,side);
                int value;
                if (index == 0) value = -search(3-side,depth-1,-INF,INF,1);
                else {
                    value = -search(3-side,depth-1,-alpha-1,-alpha,1);
                    if (!aborted_ && value > alpha) value = -search(3-side,depth-1,-INF,-alpha,1);
                }
                undoStone(move.pos);
                if (aborted_) { complete = false; break; }
                scores[move.pos] = value;
                if (value > valueBest) { valueBest = value; iterationBest = move.pos; }
                alpha = std::max(alpha,value);
                ++index;
                if (value > MATE-1000) break;
            }
            if (!complete) break;
            bestMove = iterationBest; lastScore_ = valueBest; completedDepth_ = depth;
            previous.swap(scores);
            if (std::abs(valueBest) > MATE-1000) break;
        }
        return bestMove;
    }
};
} // namespace gomoku

#ifndef GOMOKU_NO_MAIN
#ifndef GOMOKU_MOVE_MS
#define GOMOKU_MOVE_MS 1400
#endif
int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    gomoku::Engine engine;
    std::string line;
    int myColor = 0;
    double usedMs = 0.0;
    while (std::getline(std::cin,line)) {
        std::istringstream input(line);
        std::string command;
        input >> command;
        if (command == "START") {
            auto start = gomoku::Clock::now();
            int color;
            if (!(input >> color) || (color != 1 && color != 2)) continue;
            engine.reset(); myColor = color;
            usedMs = std::chrono::duration<double,std::milli>(gomoku::Clock::now()-start).count();
            std::cout << "OK\n" << std::flush;
        } else if (command == "PLACE") {
            int r,c;
            if (myColor && input >> r >> c && r >= 0 && r < 12 && c >= 0 && c < 12)
                engine.setStone(r*12+c,3-myColor);
        } else if (command == "TURN" && myColor) {
            auto start = gomoku::Clock::now();
            int empties = 0;
            for (int c : engine.board()) if (!c) ++empties;
            // Budget all remaining turns, even if the game lasts until full board.
            // 80 s target leaves 10 s for protocol/startup/scheduling overhead.
            int remainingTurns = std::max(1,(empties+1)/2);
            int budget = static_cast<int>(std::max(1.0,(80000.0-usedMs)/remainingTurns));
            budget = std::min(GOMOKU_MOVE_MS,budget);
            int move = engine.chooseMove(myColor,budget);
            if (move < 0) break; // The official referee never asks TURN on a full board.
            engine.setStone(move,myColor);
            usedMs += std::chrono::duration<double,std::milli>(gomoku::Clock::now()-start).count();
#ifdef GOMOKU_DEBUG
            std::cerr << "depth=" << engine.depth() << " score=" << engine.score()
                      << " nodes=" << engine.nodes() << " used_ms=" << usedMs << '\n';
#endif
            std::cout << move/12 << ' ' << move%12 << '\n' << std::flush;
        } else if (command == "END") break;
    }
    return 0;
}
#endif
