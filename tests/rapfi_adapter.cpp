// Compile this single translation unit with C++17 after generating the port.
// The independently checked outcomes exercise the course wrapper and native
// Rapfi search together; no upstream headers or assets are used at runtime.
#define RAPFI_COURSE_NO_MAIN
#ifndef RAPFI_COURSE_SOURCE
#define RAPFI_COURSE_SOURCE "../main.cpp"
#endif
#include RAPFI_COURSE_SOURCE

#include <iomanip>
#include <initializer_list>
#include <stdexcept>

namespace {
using Cells = std::array<int,144>;
using Clock = std::chrono::steady_clock;
int assertions = 0;
int searches = 0;
double maxSearchMs = 0;

void require(bool value,const std::string& message) {
    ++assertions;
    if (!value) throw std::runtime_error(message);
}

int point(int row,int col) { return row*12+col; }

int transform(int p,int symmetry) {
    int row=p/12,col=p%12;
    if (symmetry>=4) col=11-col;
    for (int i=0;i<(symmetry&3);++i) {
        int nextRow=col;
        col=11-row;
        row=nextRow;
    }
    return point(row,col);
}

Cells transform(const Cells& board,int symmetry) {
    Cells result{};
    for (int p=0;p<144;++p) result[transform(p,symmetry)]=board[p];
    return result;
}

void put(Cells& board,int side,std::initializer_list<int> points) {
    for (int p:points) {
        require(p>=0 && p<144 && !board[p],"invalid fixture stone");
        board[p]=side;
    }
}

// Independent five-or-more oracle, using course coordinates and colors only.
bool wins(const Cells& board,int side,int move) {
    constexpr int directions[4][2]={{0,1},{1,0},{1,1},{1,-1}};
    int row=move/12,col=move%12;
    if (move<0 || move>=144 || board[move]!=side) return false;
    for (const auto& direction:directions) {
        int length=1;
        for (int sign:{-1,1}) {
            for (int n=1;;++n) {
                int r=row+sign*n*direction[0],c=col+sign*n*direction[1];
                if (r<0 || r>=12 || c<0 || c>=12 || board[point(r,c)]!=side) break;
                ++length;
            }
        }
        if (length>=5) return true;
    }
    return false;
}

std::vector<int> completions(Cells board,int side) {
    std::vector<int> result;
    for (int p=0;p<144;++p) if (!board[p]) {
        board[p]=side;
        if (wins(board,side,p)) result.push_back(p);
        board[p]=0;
    }
    return result;
}

int search(CoursePort::Brain& brain,int budget,const std::string& label) {
    const auto cells=brain.cells();
    const auto hash=brain.board().zobristKey();
    const auto side=brain.board().sideToMove();
    const int ply=brain.board().ply();
    const auto start=Clock::now();
    const int move=brain.chooseMove(budget);
    const double elapsed=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
    ++searches;
    maxSearchMs=std::max(maxSearchMs,elapsed);
    require(elapsed<1900,label+": exceeded TURN safety ceiling");
    require(move>=0 && move<144 && !cells[move],label+": illegal selected move");
    require(brain.cells()==cells,label+": search changed input cells");
    require(brain.board().zobristKey()==hash,label+": search changed input hash");
    require(brain.board().sideToMove()==side,label+": search changed input side");
    require(brain.board().ply()==ply,label+": search changed move history");
    return move;
}

void testStateAndColors() {
    CoursePort::Brain brain;
    require(!brain.started(),"brain unexpectedly initialized");
    require(!brain.place(0,0),"PLACE before START accepted");
    require(brain.chooseMove(1)==-1,"TURN before START accepted");
    for (int side:{1,2}) {
        const auto start=Clock::now();
        brain.reset(side);
        require(std::chrono::duration<double>(Clock::now()-start).count()<1,
                "START initialization exceeded one second");
        Cells initial{};
        initial[point(5,6)]=initial[point(6,5)]=1;
        initial[point(5,5)]=initial[point(6,6)]=2;
        require(brain.cells()==initial,"START opening/color/coordinate mismatch");
        require(brain.ownColor()==side,"START own color mismatch");
        require(brain.board().sideToMove()==BLACK,"opening must leave black to move");
        const auto initialHash=brain.board().zobristKey();
        for (const auto& bad:std::array<std::array<int,2>,6>{{
                {{-1,0}},{{0,-1}},{{12,0}},{{0,12}},{{5,5}},{{5,6}}}})
            require(!brain.place(bad[0],bad[1]),"invalid PLACE accepted");
        require(brain.cells()==initial && brain.board().zobristKey()==initialHash,
                "invalid PLACE changed position");

        // START 2 normally receives PLACE before TURN. Search it directly here
        // to cover the adapter's temporary flip and exact restoration path.
        search(brain,40,"opening side restoration");
        require(brain.place(1,9),"valid PLACE rejected");
        require(brain.cells()[point(1,9)]==3-side,"PLACE color/coordinates wrong");
        require(brain.cells()[point(9,1)]==0,"PLACE transposed row and column");
        const auto before=brain.cells();
        const auto used=brain.usedMilliseconds();
        const int move=brain.turn();
        auto after=brain.cells();
        require(move>=0 && move<144 && before[move]==0,"TURN returned illegal move");
        require(after[move]==side,"TURN did not commit own color");
        after[move]=0;
        require(after==before,"TURN altered another square");
        require(brain.usedMilliseconds()>used,"TURN time not charged");
        brain.reset(3-side);
        require(brain.cells()==initial,"repeated START retained old stones");
        require(brain.ownColor()==3-side,"repeated START did not change own color");
    }
    std::cout<<"PASS state, color, coordinate, reset and search-restoration checks\n";
}

void testTactics() {
    CoursePort::Brain brain;
    for (int side:{1,2}) for (int symmetry=0;symmetry<8;++symmetry) {
        const int opponent=3-side;
        for (int kind=0;kind<4;++kind) {
            Cells cells{};
            int target=point(2,4);
            if (kind==0 || kind==2) { // A broken four with exactly one win.
                put(cells,side,{point(2,2),point(2,3),point(2,5),point(2,6)});
                if (kind==2) // Own immediate win takes precedence over defense.
                    put(cells,opponent,{point(9,2),point(9,3),point(9,4),point(9,5)});
                else put(cells,opponent,{point(9,2),point(10,8)});
            } else if (kind==1) { // One legal move avoids losing on the next ply.
                put(cells,opponent,{point(2,2),point(2,3),point(2,5),point(2,6)});
                put(cells,side,{point(9,2),point(10,8)});
            } else { // Gap completes six: freestyle must allow both colors.
                target=point(2,3);
                put(cells,side,{point(2,1),point(2,2),point(2,4),point(2,5),point(2,6)});
                put(cells,opponent,{point(9,2),point(10,8)});
            }
            cells=transform(cells,symmetry);
            target=transform(target,symmetry);
            const auto expected=completions(cells,kind==1 ? opponent : side);
            require(expected==std::vector<int>{target},"tactical fixture is not unique");
            const std::string label="tactic "+std::to_string(kind)+", color "+
                std::to_string(side)+", symmetry "+std::to_string(symmetry);
            brain.setPosition(cells,side);
            require(brain.cells()==cells,label+": board reconstruction changed colors");
            int move=search(brain,100,label);
            require(move==target,label+": expected "+std::to_string(target/12)+","+
                    std::to_string(target%12)+", got "+std::to_string(move/12)+","+
                    std::to_string(move%12));
        }

        Cells fork{};
        put(fork,side,{point(5,3),point(5,4),point(5,6),
                       point(3,5),point(4,5),point(6,5)});
        put(fork,opponent,{point(1,1),point(1,9),point(9,1),point(9,9)});
        fork=transform(fork,symmetry);
        require(completions(fork,side).empty(),"fork fixture already has a winning move");
        brain.setPosition(fork,side);
        const int move=search(brain,150,"double-four attack");
        fork[move]=side;
        require(completions(fork,side).size()>=2,
                "failed to create a forced win with two distinct five completions");
    }
    std::cout<<"PASS 80 tactical positions: both colors, 8 symmetries, freestyle six, "
                "compulsory defense and double-four attack\n";
}

void testTerminalBoard() {
    CoursePort::Brain brain;
    Cells full{};
    // Full boards are outside normal TURN traffic but must never index NONE.
    for (int p=0;p<144;++p) full[p]=1+((p/12+p%12)%2);
    brain.setPosition(full,1);
    require(brain.cells()==full,"full-board reconstruction failed");
    require(brain.chooseMove(10)==-1,"full board produced a move");
    require(brain.turn()==-1,"full-board TURN produced a move");
    full.fill(2);
    brain.setPosition(full,2);
    require(brain.cells()==full,"single-color full-board reconstruction failed");
    require(brain.chooseMove(10)==-1,"single-color full board produced a move");
    std::cout<<"PASS terminal board handling\n";
}

void testContinuousFour() {
    CoursePort::Brain brain;
    for (int side:{1,2}) for (int symmetry:{0,5}) {
        Cells cells{};
        put(cells,side,{point(5,3),point(5,4),point(5,5),point(3,6),point(4,6)});
        put(cells,3-side,{point(5,2)});
        cells=transform(cells,symmetry);
        require(completions(cells,side).empty(),"VCF fixture has immediate win");
        brain.setPosition(cells,side);
        const int first=search(brain,250,"short continuous-four first attack");
        require(first==transform(point(5,6),symmetry),"missed continuous-four first move");
        cells[first]=side;
        const auto forced=completions(cells,side);
        require(forced.size()==1,"first continuous-four attack is not forcing");
        brain.setPosition(cells,3-side);
        const int reply=search(brain,100,"short continuous-four forced reply");
        require(reply==forced[0],"missed forced continuous-four reply");
        cells[reply]=3-side;
        brain.setPosition(cells,side);
        const int second=search(brain,150,"short continuous-four second attack");
        cells[second]=side;
        const auto finalWins=completions(cells,side);
        require(finalWins.size()>=2,"continuous-four continuation is not a forced win");
        cells[finalWins[0]]=3-side;
        brain.setPosition(cells,side);
        const int final=search(brain,100,"short continuous-four final win");
        cells[final]=side;
        require(wins(cells,side,final),"continuous-four sequence failed to finish five");
    }
    std::cout<<"PASS continuous-four sequences, both colors and rotated reflection\n";
}

bool hasFork(Cells cells,int side) {
    for (int p=0;p<144;++p) if (!cells[p]) {
        cells[p]=side;
        if (completions(cells,side).size()>=2) return true;
        cells[p]=0;
    }
    return false;
}

void testThreeDefense() {
    CoursePort::Brain brain;
    for (int side:{1,2}) for (int symmetry:{0,5}) for (int firstCol:{1,4}) {
        Cells cells{};
        put(cells,3-side,{point(5,firstCol),point(5,firstCol+1),point(5,firstCol+2)});
        cells=transform(cells,symmetry);
        require(completions(cells,3-side).empty() && hasFork(cells,3-side),
                "open-three fixture is not a pending fork threat");
        brain.setPosition(cells,side);
        const int move=search(brain,100,"single/edge open-three defense");
        cells[move]=side;
        require(!hasFork(cells,3-side),"left an opponent open-four fork unblocked");
    }
    std::cout<<"PASS single and edge open-three defense, exhaustive reply oracle\n";
}
} // namespace

int main() {
    try {
        const auto start=Clock::now();
        testStateAndColors();
        testTactics();
        testContinuousFour();
        testThreeDefense();
        testTerminalBoard();
        std::cout<<std::fixed<<std::setprecision(2)<<"PASS "<<assertions
                 <<" assertions; "<<searches<<" non-mutating searches; max search "
                 <<maxSearchMs<<" ms; elapsed "
                 <<std::chrono::duration<double>(Clock::now()-start).count()<<" s\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL: "<<error.what()<<'\n';
        return 1;
    }
}
