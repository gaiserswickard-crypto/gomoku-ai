// Standalone tactical and state-integrity regression tests.
// Compile this file alone; it includes the engine without its protocol main().
#define GOMOKU_NO_MAIN
#include "../versions/v3/main.cpp"

#include <algorithm>
#include <exception>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
using gomoku::Engine;
constexpr int side = 12;
constexpr int black = 1;
constexpr int white = 2;

int square(int row, int column) { return row * side + column; }

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void put(Engine& engine, int row, int column, int color) {
    require(engine.setStone(square(row, column), color), "fixture placement failed");
}

int choose(Engine& engine, int color, int budgetMs = 100) {
    const auto original = engine.board();
    require(engine.verifyState(), "state invalid before search");
    const int move = engine.chooseMove(color, budgetMs);
    require(engine.board() == original, "search changed the board");
    require(engine.verifyState(), "search left stale incremental state");
    if (move >= 0) {
        require(move < side * side, "out-of-range move");
        require(original[move] == 0, "search selected an occupied square");
    }
    return move;
}

void initialPosition() {
    Engine engine;
    engine.reset();
    const auto& board = engine.board();
    require(std::count(board.begin(), board.end(), 0) == 140, "initial stone count");
    require(board[square(5, 5)] == white && board[square(6, 6)] == white,
            "initial white stones");
    require(board[square(5, 6)] == black && board[square(6, 5)] == black,
            "initial black stones");
    require(engine.verifyState(), "initial incremental state");
    require(choose(engine, black, 30) >= 0, "initial position has no legal move");
}

void uniqueWin() {
    Engine engine;
    engine.reset(false);
    for (int c = 3; c <= 6; ++c) put(engine, 5, c, black);
    put(engine, 5, 2, white);
    require(choose(engine, black) == square(5, 7), "missed unique immediate win");
}

void uniqueDefense() {
    Engine engine;
    engine.reset(false);
    for (int c = 4; c <= 7; ++c) put(engine, 8, c, white);
    put(engine, 8, 3, black);
    require(choose(engine, black) == square(8, 8), "missed unique forced defense");
}

void winBeforeDefense() {
    Engine engine;
    engine.reset(false);
    for (int c = 2; c <= 5; ++c) put(engine, 3, c, black);
    put(engine, 3, 1, white);
    for (int c = 4; c <= 7; ++c) put(engine, 8, c, white);
    put(engine, 8, 3, black);
    require(choose(engine, black) == square(3, 6), "defended instead of winning");
}

void brokenFour() {
    Engine engine;
    engine.reset(false);
    for (int c : {2, 3, 5, 6}) put(engine, 4, c, black);
    put(engine, 4, 1, white);
    require(choose(engine, black) == square(4, 4), "missed broken-four gap");
}

void edgeAndDiagonal() {
    Engine engine;
    engine.reset(false);
    for (int r = 0; r < 4; ++r) put(engine, r, 0, black);
    require(choose(engine, black) == square(4, 0), "missed edge win");

    engine.reset(false);
    for (int i = 0; i < 4; ++i) put(engine, i, 11 - i, white);
    require(choose(engine, black) == square(4, 7), "missed antidiagonal defense");

    engine.reset(false);
    for (int i = 0; i < 4; ++i) put(engine, 8 + i, 8 + i, black);
    require(choose(engine, black) == square(7, 7), "missed lower-right diagonal win");
}

void overlineWins() {
    Engine engine;
    engine.reset(false);
    for (int c : {1, 2, 3, 5, 6}) put(engine, 2, c, black);
    const int move = choose(engine, black);
    require(move == square(2, 4), "missed six-in-a-row gap");
    require(engine.setStone(move, black), "cannot play overline move");
    require(engine.winsAt(move), "six-in-a-row did not count as a win");
    require(engine.verifyState(), "overline state is inconsistent");
}

void fullBoardDraw() {
    Engine engine;
    engine.reset(false);
    // Along every winning direction, this pattern has runs shorter than five.
    for (int r = 0; r < side; ++r)
        for (int c = 0; c < side; ++c)
            put(engine, r, c, (r + 2 * c) % 4 < 2 ? black : white);
    for (int p = 0; p < side * side; ++p)
        require(!engine.winsAt(p), "full-board draw fixture contains a five");
    require(choose(engine, black, 20) == -1, "full board should have no move");
    require(choose(engine, white, 20) == -1, "full board should have no white move");
}

void repeatedReset() {
    Engine engine;
    engine.reset();
    const auto initial = engine.board();
    for (int iteration = 0; iteration < 5; ++iteration) {
        put(engine, iteration, 0, black);
        put(engine, iteration, 11, white);
        (void)choose(engine, iteration % 2 + 1, 15);
        engine.reset();
        require(engine.board() == initial, "reset retained previous-game stones");
        require(engine.verifyState(), "reset retained stale incremental state");
    }
    engine.reset(false);
    require(std::count(engine.board().begin(), engine.board().end(), 0) == 144,
            "empty reset did not clear the board");
    require(engine.verifyState(), "empty reset state");
}

void randomizedMakeUnmake() {
    Engine engine;
    std::mt19937 random(20261102);
    for (int trial = 0; trial < 20; ++trial) {
        engine.reset(trial % 2 == 0);
        const auto initial = engine.board();
        std::vector<int> freeSquares;
        for (int p = 0; p < side * side; ++p)
            if (engine.board()[p] == 0) freeSquares.push_back(p);
        std::shuffle(freeSquares.begin(), freeSquares.end(), random);
        const int count = 10 + static_cast<int>(random() % 90);
        for (int i = 0; i < count; ++i) {
            require(engine.setStone(freeSquares[i], 1 + static_cast<int>(random() % 2)),
                    "random legal placement rejected");
            require(engine.verifyState(), "incremental update diverged after placement");
        }
        // Non-LIFO removals also exercise intersecting lines and neighbor counts.
        std::shuffle(freeSquares.begin(), freeSquares.begin() + count, random);
        for (int i = 0; i < count; ++i) {
            engine.undoStone(freeSquares[i]);
            require(engine.verifyState(), "incremental update diverged after removal");
        }
        require(engine.board() == initial, "make/unmake did not restore original board");
    }
}

void shortContinuousFour() {
    Engine engine;
    engine.reset(false);
    // 5,6 makes a closed four, forcing 5,7. Then 2,6 or 6,6 makes an open four.
    for (int c = 3; c <= 5; ++c) put(engine, 5, c, black);
    put(engine, 5, 2, white);
    put(engine, 3, 6, black);
    put(engine, 4, 6, black);
    const int first = choose(engine, black, 250);
    require(first == square(5, 6), "missed short continuous-four attack");
    require(engine.setStone(first, black), "cannot play first forcing move");
    require(choose(engine, white) == square(5, 7), "missed first forced reply");
    put(engine, 5, 7, white);
    const int second = choose(engine, black, 150);
    require(second == square(2, 6) || second == square(6, 6),
            "did not turn the forced line into an open four");
    require(engine.setStone(second, black), "cannot play open-four move");
    const int low = second == square(2, 6) ? 1 : 2;
    const int high = second == square(2, 6) ? 6 : 7;
    put(engine, low, 6, white);
    const int finalMove = choose(engine, black);
    require(finalMove == square(high, 6), "missed final forced win");
    require(engine.setStone(finalMove, black), "cannot play final winning move");
    require(engine.winsAt(finalMove), "forcing sequence did not end in five");
}

}  // namespace

int main() {
    const std::vector<std::pair<const char*, void (*)()>> tests = {
        {"initial position and search rollback", initialPosition},
        {"unique immediate win", uniqueWin},
        {"unique forced defense", uniqueDefense},
        {"winning move before defense", winBeforeDefense},
        {"broken-four gap", brokenFour},
        {"edges and both diagonals", edgeAndDiagonal},
        {"overline is a win", overlineWins},
        {"full-board draw", fullBoardDraw},
        {"repeated START/reset", repeatedReset},
        {"random incremental make/unmake", randomizedMakeUnmake},
        {"short continuous-four sequence", shortContinuousFour},
    };
    int failed = 0;
    for (const auto& test : tests) {
        try {
            test.second();
            std::cout << "PASS " << test.first << '\n';
        } catch (const std::exception& error) {
            ++failed;
            std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failed << '/' << tests.size() << " tests passed\n";
    return failed == 0 ? 0 : 1;
}
