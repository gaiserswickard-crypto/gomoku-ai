// Threat-defense regression tests using direct board rules, not the engine LUT.
#define GOMOKU_TEST_ACCESS
#define GOMOKU_NO_MAIN
#include "../versions/v3/main.cpp"

#include <algorithm>
#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Board = std::array<int, 144>;
using gomoku::Engine;
constexpr int directions[4][2] = {{0,1},{1,0},{1,1},{1,-1}};

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

bool inside(int r, int c) { return r >= 0 && r < 12 && c >= 0 && c < 12; }

bool winsAt(const Board& b, int p) {
    if (!b[p]) return false;
    for (const auto& d : directions) {
        int run = 1;
        for (int sign : {-1,1}) {
            int r = p/12 + sign*d[0], c = p%12 + sign*d[1];
            while (inside(r,c) && b[r*12+c] == b[p]) {
                ++run;
                r += sign*d[0]; c += sign*d[1];
            }
        }
        if (run >= 5) return true;
    }
    return false;
}

bool anyCurrentWin(const Board& b) {
    for (int p = 0; p < 144; ++p) if (winsAt(b,p)) return true;
    return false;
}

std::vector<int> immediateWins(Board b, int side) {
    std::vector<int> result;
    for (int p = 0; p < 144; ++p) if (!b[p]) {
        b[p] = side;
        if (winsAt(b,p)) result.push_back(p);
        b[p] = 0;
    }
    return result;
}

// Before the move at changed, this color has no immediate winning square.
// Any new five must therefore include changed. Enumerate the empty squares
// on its four lines and test actual complete lines after each hypothetical play.
// This avoids millions of unrelated squares without consulting engine patterns.
int newWinningCount(Board& b, int side, int changed, int stopAt) {
    int count = 0;
    for (const auto& d : directions) for (int delta = -4; delta <= 4; ++delta) {
        if (!delta) continue;
        int r = changed/12 + delta*d[0], c = changed%12 + delta*d[1];
        if (!inside(r,c)) continue;
        int p = r*12+c;
        if (b[p]) continue;
        b[p] = side;
        const bool winning = winsAt(b,p);
        b[p] = 0;
        if (winning && ++count >= stopAt) return count;
    }
    return count;
}

std::vector<int> forkMoves(Board b, int side, bool firstOnly = false) {
    std::vector<int> result;
    for (int p = 0; p < 144; ++p) if (!b[p]) {
        b[p] = side;
        if (newWinningCount(b,side,p,2) >= 2) {
            result.push_back(p);
            if (firstOnly) return result;
        }
        b[p] = 0;
    }
    return result;
}

std::vector<int> legalDefenses(Board b, int side) {
    std::vector<int> result;
    // Check every one of the 144 coordinates; do not use the engine's anchor,
    // neighborhood filtering, original-fork list, move order or threat scores.
    for (int p = 0; p < 144; ++p) if (!b[p]) {
        b[p] = side;
        const bool counterFour = newWinningCount(b,side,p,1) != 0;
        const bool eliminatesAllForks = counterFour || forkMoves(b,3-side,true).empty();
        b[p] = 0;
        if (eliminatesAllForks) result.push_back(p);
    }
    return result;
}

void load(Engine& e, const Board& b) {
    e.reset(false);
    for (int p = 0; p < 144; ++p) if (b[p])
        require(e.setStone(p,b[p]), "fixture placement rejected");
    require(e.verifyState(), "fixture state inconsistent");
}

void preconditions(const Board& b, int side, const std::string& label) {
    require(!anyCurrentWin(b), label+": fixture already contains five");
    require(immediateWins(b,1).empty() && immediateWins(b,2).empty(),
            label+": fixture contains an immediate win");
    require(forkMoves(b,side).empty(), label+": own fork masks defense");
    require(!forkMoves(b,3-side).empty(), label+": no enemy fork threat");
}

std::vector<int> compareDefenses(Engine& e, const Board& b, int side,
                               const std::string& label, bool checkRoot = false) {
    preconditions(b,side,label);
    load(e,b);
    const auto expected = legalDefenses(b,side);
    const auto hashBefore = e.hash_;
    bool threatened = false;
    auto generated = e.forkDefenses(side,threatened);
    require(threatened, label+": fork threat not recognized");
    std::vector<int> actual;
    for (const auto& move : generated) {
        require(move.tactical, label+": defense not marked tactical");
        actual.push_back(move.pos);
    }
    std::sort(actual.begin(),actual.end());
    require(actual == expected, label+": defense set differs from exhaustive oracle");
    require(e.board() == b && e.hash_ == hashBefore && e.verifyState(),
            label+": forkDefenses did not restore state");
    if (checkRoot && !expected.empty()) {
        // The assertion is independent of elapsed time and completed depth.
        // A fallback, partial result or completed search must all be legal defenses.
        const int selected = e.chooseMove(side,1);
        require(std::binary_search(expected.begin(),expected.end(),selected),
                label+": root returned a move outside the legal defense set");
        require(e.board() == b && e.hash_ == hashBefore && e.verifyState(),
                label+": chooseMove did not restore state");
    }
    return actual;
}

Board twoOpenThrees() {
    Board b{};
    for (int row : {3,8}) for (int col : {4,5,6}) b[row*12+col] = 2;
    for (int p : {0,2,9,132,141,143}) b[p] = 1;
    return b;
}

void deterministicCases(Engine& e) {
    Board b = twoOpenThrees();
    require(compareDefenses(e,b,1,"independent open threes").empty(),
            "independent open threes unexpectedly have a defense");
    e.deadline_ = gomoku::Clock::now() + std::chrono::seconds(1);
    e.aborted_ = false; e.nodes_ = 0;
    const auto hashBefore = e.hash_;
    const int value = e.quiescence(1,-gomoku::INF,gomoku::INF,0,8);
    require(!e.aborted_, "simple forced-loss qsearch unexpectedly timed out");
    require(value <= -gomoku::MATE+10, "qsearch stood pat in a forced-loss position");
    require(e.board() == b && e.hash_ == hashBefore && e.verifyState(),
            "forced-loss qsearch did not restore state");

    b.fill(0);
    for (int col : {4,5,6}) b[5*12+col] = 2;
    auto actual = compareDefenses(e,b,1,"single open three",true);
    require(actual == std::vector<int>({5*12+3,5*12+7}),
            "single open three did not retain both end blocks");

    b.fill(0);
    for (int col : {1,2,3}) b[5*12+col] = 2;
    actual = compareDefenses(e,b,1,"edge open three",true);
    require(actual == std::vector<int>({5*12,5*12+4,5*12+5}),
            "edge defense at opposite end of attacking line was omitted");

    b = twoOpenThrees();
    for (int col : {2,3,4}) b[10*12+col] = 1;
    b[10*12+1] = 2;
    actual = compareDefenses(e,b,1,"forcing counter-four",true);
    require(std::binary_search(actual.begin(),actual.end(),10*12+5) &&
            std::binary_search(actual.begin(),actual.end(),10*12+6),
            "a straight or broken counter-four was omitted");
}

Board transformed(const Board& b, int symmetry) {
    Board out{};
    for (int p = 0; p < 144; ++p) {
        int r = p/12, c = p%12;
        if (symmetry & 4) c = 11-c;
        for (int k = 0; k < (symmetry & 3); ++k) {
            const int oldR = r; r = c; c = 11-oldR;
        }
        out[r*12+c] = b[p];
    }
    return out;
}

void randomCases(Engine& e) {
    std::mt19937 random(0xDEF2026U);
    int accepted = 0, attempted = 0, noDefense = 0, withDefense = 0;
    while (accepted < 48 && attempted++ < 2000) {
        const int side = 1 + (accepted % 2), enemy = 3-side;
        Board b{};
        if (accepted % 3 == 0) {
            for (int row : {3,8}) for (int col : {4,5,6}) b[row*12+col] = enemy;
        } else {
            const int row = 3 + static_cast<int>(random()%6);
            const int first = accepted % 3 == 1 ? 1 : 4;
            for (int col = first; col < first+3; ++col) b[row*12+col] = enemy;
        }
        const int noise = 4 + static_cast<int>(random()%13);
        for (int i = 0; i < noise; ++i) {
            int p;
            do { p = static_cast<int>(random()%144); } while (b[p]);
            b[p] = 1 + static_cast<int>(random()%2);
        }
        b = transformed(b,static_cast<int>(random()%8));
        if (anyCurrentWin(b) || !immediateWins(b,1).empty() || !immediateWins(b,2).empty() ||
            !forkMoves(b,side,true).empty() || forkMoves(b,enemy,true).empty()) continue;
        auto defenses = compareDefenses(e,b,side,"random "+std::to_string(accepted),true);
        if (defenses.empty()) ++noDefense; else ++withDefense;
        ++accepted;
    }
    require(accepted == 48 && noDefense > 0 && withDefense > 0,
            "random fixtures did not cover all defense categories");
    std::cout << "PASS 48 random exhaustive defense comparisons (" << withDefense
              << " defendable, " << noDefense << " without defense)\n";
}
}  // namespace

int main() {
    try {
        const auto start = gomoku::Clock::now();
        Engine engine;
        deterministicCases(engine);
        std::cout << "PASS independent-open-three qsearch, both ends, edge, counter-fours\n";
        randomCases(engine);
        const double seconds = std::chrono::duration<double>(gomoku::Clock::now()-start).count();
        std::cout << "PASS defense suite; elapsed " << seconds << " s\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL defense: " << error.what() << '\n';
        return 1;
    }
}
