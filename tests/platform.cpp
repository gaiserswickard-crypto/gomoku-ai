// Regressions reconstructed from the user's actual platform log 866b.
#define GOMOKU_NO_MAIN
#define GOMOKU_TEST_ACCESS
#include "../versions/v3/main.cpp"
#include <stdexcept>

static void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}

int main() {
    try {
        gomoku::Engine e;
        // First 17 plies after the four initial stones; White is to move.
        const int sequence[][2] = {{4,4},{7,3},{4,5},{6,4},{4,6},{4,7},
            {3,4},{6,7},{4,3},{4,2},{5,2},{2,5},{5,4},{3,2},{3,6},{8,2},{9,1}};
        int side = 1;
        for (const auto& rc : sequence) {
            require(e.setStone(rc[0]*12+rc[1],side),"invalid recorded position");
            side = 3-side;
        }
        const auto before = e.board();
        // The historical move (2,7) allows a verified continuous-four loss.
        e.setStone(2*12+7,2);
        e.proofDeadline_ = gomoku::Clock::now()+std::chrono::seconds(1);
        e.proofAborted_ = false; e.proofNodes_ = 0;
        int attack = -1;
        require(e.proveFours(1,30,attack),"known opponent VCF was missed");
        require(!e.proofAborted_,"known VCF proof timed out");
        e.undoStone(2*12+7);
        int move = e.chooseMove(2,500);
        require(move == 6*12+3,"chose a refuted defense in platform round 866b, ply 18");
        require(e.board() == before && e.verifyState(),"platform search changed board/state");
        std::cout << "PASS platform 866b ply 18: rejects (2,7), chooses (6,3)\n";

        // Enemy open threes must not suppress our own winning counter-fours.
        e.reset(false);
        const int black[][2] = {{5,3},{5,4},{5,5},{3,6},{4,6}};
        const int white[][2] = {{5,2},{8,2},{8,3},{8,4},{10,2},{10,3},{10,4}};
        for (const auto& rc : black) e.setStone(rc[0]*12+rc[1],1);
        for (const auto& rc : white) e.setStone(rc[0]*12+rc[1],2);
        auto counterBoard = e.board();
        e.deadline_ = gomoku::Clock::now()+std::chrono::seconds(1);
        e.aborted_ = false; e.nodes_ = 0;
        int score = e.quiescence(1,-gomoku::INF,gomoku::INF,0,8);
        require(score > gomoku::MATE-20 && !e.aborted_,"missed winning counter-four sequence");
        require(e.board() == counterBoard && e.verifyState(),"counter search did not restore state");
        std::cout << "PASS winning counter-four under enemy double-three threats\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL platform: " << error.what() << '\n';
        return 1;
    }
}
