// Offline deterministic search probe. Build twice against the original and
// warning-clean source, with identical compiler flags. No wall-clock cutoff.
#define RAPFI_COURSE_NO_MAIN
#ifndef RAPFI_COURSE_SOURCE
#define RAPFI_COURSE_SOURCE "../main.cpp"
#endif
#include RAPFI_COURSE_SOURCE

#include <iomanip>

namespace EquivalenceProbe {
struct Digest {
    uint64_t value = 14695981039346656037ULL;
    void bytes(const void* data, size_t count) {
        const auto* p = static_cast<const unsigned char*>(data);
        for (size_t i=0; i<count; ++i) { value ^= p[i]; value *= 1099511628211ULL; }
    }
    template<class T> void add(const T& v) { bytes(&v, sizeof(v)); }
    void integer(int64_t v) { add(v); }
    std::string str() const { std::ostringstream out; out<<std::hex<<value; return out.str(); }
};

std::string tablesHash() {
    Digest d;
    d.add(PatternConfig::PATTERN2x);
    d.add(PatternConfig::PATTERN2xStandard);
    d.add(PatternConfig::PATTERN2xRenju);
    d.add(PatternConfig::PCODE);
    d.add(PatternConfig::PCODERenjuBlack);
    d.add(PatternConfig::DEFENCE);
    d.add(PatternConfig::DEFENCEStandard);
    d.add(PatternConfig::DEFENCERenju);
    d.add(Evaluation::EVALS);
    d.add(Evaluation::EVALS_THREAT);
    d.add(Evaluation::P4SCORES);
    d.add(Evaluation::POLICY_CROSS);
    d.add(Evaluation::POLICY_CROSS_ACTIVE_MASK);
    for (const auto& readout : Evaluation::classicalValueReadouts()) {
        d.add(readout.knotsActive);
        d.add(readout.knots);
    }
    return d.str();
}

std::string boardHash(const Board& board) {
    Digest d;
    d.integer(board.size()); d.integer(board.ply());
    d.integer(board.sideToMove()); d.integer(board.movesLeft());
    d.add(board.zobristKey());
    for (int row=0; row<12; ++row) for (int col=0; col<12; ++col) {
        Pos p(col,row);
        d.integer(board.get(p)); d.integer(board.isCandidate(p));
        for (Color side : {BLACK,WHITE}) {
            d.integer(board.pattern4(p,side));
            for (int direction=0; direction<4; ++direction)
                d.integer(board.pattern(p,side,direction));
        }
    }
    const auto& st=board.stateInfo();
    d.integer(st.journalStart); d.integer(st.lastMove); d.integer(st.valueBlack);
    d.integer(st.candArea.x0); d.integer(st.candArea.x1);
    d.integer(st.candArea.y0); d.integer(st.candArea.y1);
    for (Color side : {BLACK,WHITE}) {
        d.integer(st.lastFlex4AttackMove[side]);
        for (int i=0; i<3; ++i) d.integer(st.lastPattern4Move[side][i]);
        for (int i=0; i<PATTERN4_NB; ++i) d.integer(st.p4Count[side][i]);
    }
    return d.str();
}

bool hasFive(const std::array<int,144>& cells,int move,int color) {
    constexpr int directions[4][2]={{0,1},{1,0},{1,1},{1,-1}};
    for (const auto& dir:directions) {
        int count=1;
        for (int sign:{-1,1}) {
            int r=move/12+sign*dir[0],c=move%12+sign*dir[1];
            while(r>=0&&r<12&&c>=0&&c<12&&cells[r*12+c]==color) {
                ++count;r+=sign*dir[0];c+=sign*dir[1];
            }
        }
        if(count>=5)return true;
    }
    return false;
}

int coordinate(Pos pos) { return pos.isInBoard(12,12) ? pos.y()*12+pos.x() : -1; }
}

int main(int argc,char** argv) {
    using namespace EquivalenceProbe;
    const int maxDepth=argc>1?std::stoi(argv[1]):10;
    const uint64_t maxNodes=argc>2?std::stoull(argv[2]):30000;
    CoursePort::initializeCore();
    std::cout<<"{\"kind\":\"metadata\",\"tables\":\""<<tablesHash()
        <<"\",\"layout\":["<<sizeof(Pattern2x)<<','<<sizeof(StateInfo)<<','
        <<sizeof(Board)<<','<<sizeof(Search::TTEntry)<<','<<sizeof(Search::TTBucket)
        <<"],\"max_depth\":"<<maxDepth<<",\"max_nodes\":"<<maxNodes<<"}\n"<<std::flush;
    std::string id;
    int count;
    while(std::cin>>id>>count) {
        Search::Engine.clear(true);
        Board board(12);
        board.newGame<FREESTYLE>();
        std::array<int,144> cells{};
        for(int index=0;index<count;++index) {
            int p; if(!(std::cin>>p)||p<0||p>=144||cells[p]) return 2;
            int side=index%2+1;
            cells[p]=side;
            if(hasFive(cells,p,side))return 3;
            board.move<FREESTYLE>(Pos(p%12,p/12));
        }
        const auto before=boardHash(board);
        const int staticEval=Evaluation::evaluate<FREESTYLE>(board,-VALUE_INFINITE,VALUE_INFINITE);
        Search::SearchOptions options;
        options.rule={FREESTYLE,GameRule::FREEOPEN};
        options.swapable=false;
        options.disableOpeningQuery=true;
        options.pondering=false;
        options.timeLimit=false;
        options.maxNodes=maxNodes;
        options.maxDepth=maxDepth;
        options.infoMode=Search::SearchOptions::INFO_NONE;
        options.multiPV=1;
        options.strengthLevel=100;
        options.maxMoves=144;
        options.drawResult=Search::SearchOptions::RES_DRAW;
        const auto start=std::chrono::steady_clock::now();
        Search::Engine.startThinking(board,options,false);
        const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        const auto after=boardHash(board);
        if(before!=after)return 4;
        auto* thread=Search::Engine.main();
        auto* data=thread->searchDataAs<Search::AB::ABSearchData>();
        const Pos best=Search::Engine.ctx.bestMove;
        const Search::RootMove* selected=nullptr;
        Digest roots;
        for(const auto& rm:thread->rootMoves) {
            roots.integer(rm.value); roots.integer(rm.previousValue);
            roots.integer(rm.selDepth); roots.add(rm.numNodes);
            roots.integer(rm.pv.size());
            for(Pos p:rm.pv) roots.integer(p);
            if(!rm.pv.empty()&&rm.pv[0]==best)selected=&rm;
        }
        int p=coordinate(best);
        if(p<0||cells[p])return 5;
        std::cout<<"{\"kind\":\"position\",\"id\":\""<<id<<"\",\"side\":"
            <<1+int(board.sideToMove())<<",\"stones\":"<<count<<",\"best\":"<<p
            <<",\"static_eval\":"<<staticEval<<",\"score\":";
        if(selected)std::cout<<int(selected->value);else std::cout<<"null";
        std::cout<<",\"nodes\":"<<Search::Engine.nodesSearched()<<",\"completed_depth\":"
            <<data->completedDepth.load()<<",\"selective_depth\":"<<thread->selDepth
            <<",\"board\":\""<<before<<"\",\"root_moves\":\""<<roots.str()<<"\",\"pv\":[";
        if(selected)for(size_t i=0;i<selected->pv.size();++i) {
            if(i)std::cout<<',';std::cout<<coordinate(selected->pv[i]);
        }
        std::cout<<"],\"milliseconds\":"<<std::fixed<<std::setprecision(6)<<ms<<"}\n"<<std::flush;
    }
    return 0;
}
