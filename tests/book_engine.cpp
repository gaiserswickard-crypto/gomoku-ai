// Integration regressions include actual unsafe recommendations found by the
// independent audit. Tactical rules must take priority over advisory data.
#define GOMOKU_NO_MAIN
#include "../versions/v3/main.cpp"
#include <stdexcept>

static void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
static bool contains(const std::vector<int>& values, int value) {
    return std::find(values.begin(), values.end(), value) != values.end();
}
static bool wins(const std::array<int,144>& board, int pos, int side) {
    if (board[pos]) return false;
    for (const auto& d : std::array<std::array<int,2>,4>{{{{0,1}},{{1,0}},{{1,1}},{{1,-1}}}}) {
        int count = 1;
        for (int sign : {-1,1}) {
            int r = pos/12 + sign*d[0], c = pos%12 + sign*d[1];
            while (r >= 0 && r < 12 && c >= 0 && c < 12 && board[r*12+c] == side) {
                ++count; r += sign*d[0]; c += sign*d[1];
            }
        }
        if (count >= 5) return true;
    }
    return false;
}
template<std::size_t SIZE>
static void position(gomoku::Engine& engine, const int (&moves)[SIZE][2]) {
    engine.reset();
    for (std::size_t i = 0; i < SIZE; ++i)
        require(engine.setStone(moves[i][0]*12+moves[i][1],i%2 ? 2 : 1),"invalid fixture");
}

int main() {
    try {
        gomoku::Engine engine;
        const auto& book = gomoku_book::openingBook();
        require(book.valid() && book.nodeCount() > 300000,"embedded book did not load");
        auto before = engine.board();
        int move = engine.chooseMove(1,500);
        require(move == 4*12+7 && engine.usedBook(),"initial black book move was not used");
        require(engine.board() == before && engine.verifyState(),"book search changed state");

        engine.setStone(move,1);
        before = engine.board();
        move = engine.chooseMove(2,20);
        require(!engine.usedBook() && move >= 0 && !before[move],"white did not use legal search fallback");
        require(engine.board() == before && engine.verifyState(),"white search changed state");

        engine.reset(); engine.setStone(0,1); engine.setStone(1,2);
        before = engine.board();
        require(book.candidates(before).empty(),"unlisted opening matched book");
        move = engine.chooseMove(1,20);
        require(!engine.usedBook() && move >= 0 && !before[move],"unlisted opening did not fall back");
        require(engine.board() == before && engine.verifyState(),"fallback changed state");

        const int winPath[][2] = {{4,7},{7,4},{4,6},{4,4},{7,7},{2,2},{3,3},
            {5,8},{5,7},{4,8},{6,8},{7,9},{3,7},{2,7}};
        position(engine,winPath); before = engine.board();
        require(contains(book.candidates(before),3*12+5),"known non-winning book recommendation fixture changed");
        move = engine.chooseMove(1,20);
        require(wins(before,move,1) && !engine.usedBook(),"immediate win did not override book");
        require(engine.board() == before && engine.verifyState(),"win override changed state");

        const int blockPath[][2] = {{4,7},{7,4},{4,6},{5,9},{5,7},{6,7},{3,8},
            {2,9},{3,5},{6,8},{3,7},{6,9},{6,10},{4,9}};
        position(engine,blockPath); before = engine.board();
        require(contains(book.candidates(before),2*12+8),"known unsafe book recommendation fixture changed");
        int block = -1, count = 0;
        for (int p = 0; p < 144; ++p) if (wins(before,p,2)) { block = p; ++count; }
        require(count == 1,"fixture does not have a unique white win");
        move = engine.chooseMove(1,20);
        require(move == block && !engine.usedBook(),"compulsory block did not override unsafe book");
        require(engine.board() == before && engine.verifyState(),"block override changed state");

        engine.reset();
        require(engine.chooseMove(1,500) == 4*12+7 && engine.usedBook(),"reset lost opening lookup");
        std::cout << "PASS embedded book, initial black move, white/off-book fallback, actual bad-book overrides, rollback/reset\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL book engine: " << error.what() << '\n';
        return 1;
    }
}
