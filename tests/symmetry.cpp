// Independent orbit checks for exact, color-preserving root symmetry pruning.
#define GOMOKU_NO_MAIN
#define GOMOKU_TEST_ACCESS
#include "../versions/v3/main.cpp"
#include <set>
#include <stdexcept>

static void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}

// Explicit geometric maps, independent of Engine::transformed's rotation loop.
static std::array<int,8> images(int p) {
    int r=p/12, c=p%12;
    return {{r*12+c, c*12+11-r, (11-r)*12+11-c, (11-c)*12+r,
             r*12+11-c, (11-r)*12+c, c*12+r, (11-c)*12+11-r}};
}

static std::vector<int> stabilizer(const gomoku::Engine& e) {
    std::vector<int> maps;
    for (int s=0; s<8; ++s) {
        bool same=true;
        for (int p=0; p<144; ++p)
            if (e.board()[p] != e.board()[images(p)[s]]) same=false;
        if (same) maps.push_back(s);
    }
    return maps;
}

static void check(gomoku::Engine& e, bool sparse=false) {
    const auto before=e.board();
    const auto maps=stabilizer(e);
    std::vector<gomoku::Move> moves, expected;
    std::set<int> seen;
    // Reverse order deliberately supplies noncanonical representatives first.
    for (int p=143; p>=0; --p) if (!e.board()[p] && (!sparse || p%3==1)) {
        gomoku::Move m{p,7*p,bool(p%2)};
        moves.push_back(m);
        int representative=p;
        for (int s:maps) representative=std::min(representative,images(p)[s]);
        if (seen.insert(representative).second) {
            m.pos=representative;
            expected.push_back(m);
        }
    }
    e.uniqueRootMoves(moves);
    require(moves.size()==expected.size(),"lost or duplicated a legal move orbit");
    for (std::size_t i=0; i<moves.size(); ++i) {
        require(moves[i].pos==expected[i].pos,"incorrect orbit representative/order");
        require(moves[i].order==expected[i].order && moves[i].tactical==expected[i].tactical,
                "move metadata changed during symmetry reduction");
        require(!e.board()[moves[i].pos],"representative is occupied");
    }
    require(e.board()==before && e.verifyState(),"symmetry reduction changed state");
}

int main() {
    try {
        gomoku::Engine e;
        for (int p=0; p<144; ++p) {
            std::set<int> actual,expected;
            for (int s=0; s<8; ++s) {
                actual.insert(e.transformed(p,s)); expected.insert(images(p)[s]);
            }
            require(actual==expected,"D4 transform set is incorrect");
        }
        require(stabilizer(e).size()==4,"official start has four colored symmetries");
        std::vector<gomoku::Move> differentColors{{4*12+4,0,false},{4*12+7,0,false}};
        e.uniqueRootMoves(differentColors);
        require(differentColors.size()==2,"color-swapping rotation was incorrectly pruned");
        check(e); check(e,true);
        e.reset(false);
        require(stabilizer(e).size()==8,"empty board must have all eight symmetries");
        check(e); check(e,true);
        e.setStone(0,1); e.setStone(17,2); e.setStone(83,1);
        require(stabilizer(e).size()==1,"asymmetric fixture is unexpectedly symmetric");
        check(e); check(e,true);
        // Each fixture is invariant under a selected reflection or rotation.
        // The oracle computes its full colored stabilizer, including accidental ones.
        std::uint32_t state=0x71f3a9U;
        for (int trial=0; trial<64; ++trial) {
            e.reset(false);
            int symmetry=1+trial%7;
            for (int stone=0; stone<12; ++stone) {
                state=state*1664525U+1013904223U;
                int p=static_cast<int>(state%144),q=p;
                int color=1+static_cast<int>((state>>16)&1U);
                if (e.board()[p]) continue;
                do {
                    require(e.setStone(q,color),"generated symmetry orbit overlaps");
                    q=images(q)[symmetry];
                } while (q!=p);
            }
            check(e); check(e,true);
        }
        std::cout << "PASS symmetry: D4 maps, colored start, empty/asymmetric boards, 64 invariant boards\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL symmetry: " << error.what() << '\n';
        return 1;
    }
}
