// Randomized black-box checks against a separate five-cell-window rule oracle.
// Compile this file alone; do not also link main.cpp.
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
constexpr int width = 12;
constexpr int size = width * width;
using Board = std::array<int, size>;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

// Unlike Engine::winsAt, this does not count outward runs. Enumerate every
// length-five segment containing the queried stone, with explicit boundaries.
bool oracleWinsAt(const Board& board, int position) {
    if (position < 0 || position >= size || board[position] == 0) return false;
    const int directions[4][2] = {{0, 1}, {1, 0}, {1, 1}, {1, -1}};
    const int color = board[position];
    for (const auto& direction : directions) {
        for (int start = -4; start <= 0; ++start) {
            bool five = true;
            for (int step = start; step < start + 5; ++step) {
                const int row = position / width + step * direction[0];
                const int column = position % width + step * direction[1];
                if (row < 0 || row >= width || column < 0 || column >= width ||
                    board[row * width + column] != color) {
                    five = false;
                    break;
                }
            }
            if (five) return true;
        }
    }
    return false;
}

std::vector<int> oracleWinningMoves(Board board, int color) {
    std::vector<int> moves;
    for (int p = 0; p < size; ++p) {
        if (board[p]) continue;
        board[p] = color;
        if (oracleWinsAt(board, p)) moves.push_back(p);
        board[p] = 0;
    }
    return moves;
}

bool contains(const std::vector<int>& moves, int position) {
    return std::find(moves.begin(), moves.end(), position) != moves.end();
}

void compareActualWins(const gomoku::Engine& engine, const Board& board,
                       const std::string& context) {
    for (int p = 0; p < size; ++p)
        require(engine.winsAt(p) == oracleWinsAt(board, p),
                context + ": winsAt disagrees at " + std::to_string(p));
}
}  // namespace

int main() {
    try {
        constexpr int cases = 600;
        std::mt19937 random(0x20261102U);
        gomoku::Engine engine;
        int winChecks = 0, blockChecks = 0, ordinaryChecks = 0, positiveBoards = 0;

        for (int trial = 0; trial < cases; ++trial) {
            engine.reset(false);
            Board board{};
            std::vector<int> available;
            for (int p = 0; p < size; ++p) available.push_back(p);
            std::shuffle(available.begin(), available.end(), random);
            const int target = 20 + static_cast<int>(random() % 61);
            int stones = 0;
            const std::string context = "case " + std::to_string(trial);

            // Every prefix is nonterminal. If one color completes five at this
            // square, try the other; skip the square if both would complete five.
            for (int p : available) {
                if (stones == target) break;
                board[p] = 1 + static_cast<int>(random() % 2);
                if (oracleWinsAt(board, p)) board[p] = 3 - board[p];
                if (oracleWinsAt(board, p)) { board[p] = 0; continue; }
                require(engine.setStone(p, board[p]), context + ": fixture rejected");
                ++stones;
            }
            require(stones == target, context + ": could not fill random fixture");
            require(engine.board() == board, context + ": fixture board differs");
            require(engine.verifyState(), context + ": fixture incremental state differs");
            compareActualWins(engine, board, context);

            std::vector<int> wins[3];
            wins[1] = oracleWinningMoves(board, 1);
            wins[2] = oracleWinningMoves(board, 2);

            for (int color = 1; color <= 2; ++color) {
                const std::string turn = context + ", side " + std::to_string(color);
                const auto original = engine.board();
                const int move = engine.chooseMove(color, 1);
                require(engine.board() == original, turn + ": search changed board");
                require(engine.verifyState(), turn + ": search changed incremental state");
                require(move >= 0 && move < size && board[move] == 0,
                        turn + ": illegal chosen move");
                if (!wins[color].empty()) {
                    ++winChecks;
                    require(contains(wins[color], move), turn + ": failed to win immediately");
                } else if (wins[3 - color].size() == 1) {
                    ++blockChecks;
                    require(move == wins[3 - color][0], turn + ": missed unique forced block");
                } else {
                    ++ordinaryChecks;
                }

                // Also test actual terminal boards, so winsAt is checked on
                // positive cases and on every stone belonging to the new line.
                for (int winningMove : wins[color]) {
                    require(engine.setStone(winningMove, color), turn + ": cannot play oracle win");
                    board[winningMove] = color;
                    compareActualWins(engine, board, turn + ", winning continuation");
                    require(engine.verifyState(), turn + ": winning placement state differs");
                    engine.undoStone(winningMove);
                    board[winningMove] = 0;
                    require(engine.board() == original && engine.verifyState(),
                            turn + ": undo of winning move failed");
                    ++positiveBoards;
                }
            }
        }

        require(winChecks > 0 && blockChecks > 0 && ordinaryChecks > 0 && positiveBoards > 0,
                "random generator did not cover every required category");
        std::cout << "PASS " << cases << " random nonterminal boards; "
                  << 2 * cases << " searches\n"
                  << "Immediate wins: " << winChecks << "; unique blocks: " << blockChecks
                  << "; other legal moves: " << ordinaryChecks << '\n'
                  << "Terminal continuation boards checked: " << positiveBoards << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL oracle: " << error.what() << '\n';
        return 1;
    }
}
