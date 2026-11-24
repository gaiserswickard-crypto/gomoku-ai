// Course protocol adapter for the reduced Rapfi engine.
// Coordinates exposed here are (row,column), while Rapfi Pos takes (x,y).
// This adapter performs no file I/O and starts no OS worker threads.
#include <algorithm>
#include <array>
#include <chrono>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef MULTI_THREADING
#error The course submission must be compiled without MULTI_THREADING.
#endif

namespace CoursePort {

// Defined by the standalone core: initialize embedded evaluation tables and
// create exactly one synchronous SearchThread, without opening config files.
void initializeCore();

class Brain {
    using Clock = std::chrono::steady_clock;
    std::unique_ptr<Board> board_;
    Color own_ = BLACK;
    double usedMs_ = 0.0;

    static double milliseconds(Clock::time_point start) {
        return std::chrono::duration<double,std::milli>(Clock::now()-start).count();
    }
    static bool inside(int row,int col) {
        return row>=0 && row<12 && col>=0 && col<12;
    }
    static Color color(int courseColor) {
        return courseColor == 1 ? BLACK : WHITE;
    }
    void commit(Pos pos,Color side) {
        // Normal referee traffic always alternates. A pass also lets malformed
        // repeated TURN/PLACE traffic record the requested color consistently.
        if (board_->sideToMove() != side)
            board_->move<FREESTYLE>(Pos::PASS);
        board_->move<FREESTYLE>(pos);
    }

public:
    bool started() const { return bool(board_); }
    int ownColor() const { return own_ == BLACK ? 1 : 2; }
    double usedMilliseconds() const { return usedMs_; }
    const Board& board() const { return *board_; }

    std::array<int,144> cells() const {
        std::array<int,144> result{};
        if (!board_) return result;
        for (int row=0;row<12;++row) for (int col=0;col<12;++col) {
            Color value=board_->get(Pos(col,row));
            result[row*12+col]=value==BLACK ? 1 : value==WHITE ? 2 : 0;
        }
        return result;
    }

    void reset(int courseColor) {
        if (courseColor != 1 && courseColor != 2)
            throw std::invalid_argument("invalid course color");
        auto start=Clock::now();
        initializeCore();
        Config::GeneralCfg.messageMode=MsgMode::NONE;
        Search::Engine.clear(true);
        own_=color(courseColor);
        board_=std::make_unique<Board>(12);
        board_->newGame<FREESTYLE>();
        board_->move<FREESTYLE>(Pos(6,5)); // Black (5,6)
        board_->move<FREESTYLE>(Pos(5,5)); // White (5,5)
        board_->move<FREESTYLE>(Pos(5,6)); // Black (6,5)
        board_->move<FREESTYLE>(Pos(6,6)); // White (6,6), next is Black
        usedMs_=milliseconds(start);
    }

    bool place(int row,int col) {
        if (!board_ || !inside(row,col)) return false;
        Pos pos(col,row);
        if (board_->get(pos) != EMPTY) return false;
        commit(pos,~own_);
        return true;
    }

    // Search leaves the supplied board unchanged, including its side to move.
    // A separate turn() call commits the result for actual protocol traffic.
    int chooseMove(int budgetMs) {
        if (!board_ || board_->movesLeft() == 0) return -1;
        budgetMs=std::max(1,std::min(1400,budgetMs));
        Search::SearchOptions options;
        options.rule={FREESTYLE,GameRule::FREEOPEN};
        options.swapable=false;
        options.pondering=false;
        options.disableOpeningQuery=true;
        options.infoMode=Search::SearchOptions::INFO_NONE;
        options.multiPV=1;
        options.strengthLevel=100;
        options.maxMoves=144;
        options.drawResult=Search::SearchOptions::RES_DRAW;
        // Outer accounting already divides the remaining whole-game budget.
        // Fixed turn-only control avoids allocating that budget a second time.
        options.setTimeControl(budgetMs,0);
        bool flipped=board_->sideToMove()!=own_;
        if (flipped) board_->flipSide();
        try {
            Search::Engine.startThinking(*board_,options,false);
        } catch (...) {
            if (flipped) board_->flipSide();
            throw;
        }
        if (flipped) board_->flipSide();
        Pos best=Search::Engine.ctx.bestMove;
        if (board_->isInBoard(best) && board_->get(best)==EMPTY)
            return best.y()*12+best.x();
        // No protocol-invalid output even if search returns NONE on a terminal
        // position. The official referee does not ask TURN after game end.
        for (int row=0;row<12;++row) for (int col=0;col<12;++col)
            if (board_->get(Pos(col,row))==EMPTY) return row*12+col;
        return -1;
    }

    int turn() {
        if (!board_) return -1;
        auto start=Clock::now();
        int remainingTurns=std::max(1,(board_->movesLeft()+1)/2);
        int budget=static_cast<int>(std::max(1.0,(80000.0-usedMs_)/remainingTurns));
        int move=chooseMove(std::min(1400,budget));
        if (move>=0) commit(Pos(move%12,move/12),own_);
        usedMs_+=milliseconds(start);
        return move;
    }

    // Offline tests may construct arbitrary colored boards without depending
    // on a historical move order. PASS is only an internal reconstruction aid.
    void setPosition(const std::array<int,144>& position,int sideToMove) {
        reset(sideToMove);
        board_->newGame<FREESTYLE>();
        std::vector<Pos> stones[2];
        for (int p=0;p<144;++p) {
            if (position[p]<0 || position[p]>2)
                throw std::invalid_argument("invalid test position color");
            if (position[p]) stones[position[p]-1].emplace_back(p%12,p/12);
        }
        std::size_t consumed[2]{};
        while (consumed[0]<stones[0].size() || consumed[1]<stones[1].size()) {
            Color side=board_->sideToMove();
            Pos pos=consumed[side]<stones[side].size()
                ? stones[side][consumed[side]++] : Pos::PASS;
            board_->move<FREESTYLE>(pos);
        }
        // A terminal full board needs no side alignment. In the most skewed
        // synthetic fixture it has already consumed Rapfi's full pass budget.
        if (board_->movesLeft()>0 && board_->sideToMove()!=own_)
            board_->move<FREESTYLE>(Pos::PASS);
    }
};

inline int runProtocol(std::istream& input,std::ostream& output) {
    Brain brain;
    std::string line;
    while (std::getline(input,line)) {
        std::istringstream fields(line);
        std::string command;
        fields>>command;
        if (command=="START") {
            int side;
            if (!(fields>>side) || (side!=1 && side!=2)) continue;
            brain.reset(side);
            output<<"OK\n"<<std::flush;
        } else if (command=="PLACE") {
            int row,col;
            if (fields>>row>>col) brain.place(row,col);
        } else if (command=="TURN" && brain.started()) {
            int move=brain.turn();
            if (move<0) break;
            output<<move/12<<' '<<move%12<<'\n'<<std::flush;
        } else if (command=="END") break;
    }
    return 0;
}

} // namespace CoursePort

#ifndef RAPFI_COURSE_NO_MAIN
int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    return CoursePort::runProtocol(std::cin,std::cout);
}
#endif
