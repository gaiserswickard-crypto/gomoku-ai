// Asset extraction audit: serialize initialized arrays in the official v8 order.
// The output is compared byte-for-byte with the decompressed upstream model.
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <vector>
constexpr unsigned PCODE_NB = 3876, THREAT_NB = 2048, RULE_NB = 3;
using Eval = int16_t;
using Score = int16_t;
namespace Evaluation {
constexpr unsigned PolicyStoredContextCount = 5, PolicyStoredPatternCount = 13;
Eval EVALS[4][PCODE_NB], EVALS_THREAT[4][THREAT_NB];
Score P4SCORES[4][PCODE_NB][2];
using StoredPolicyCrossTable = std::array<Score, 5 * 13 * 13>;
StoredPolicyCrossTable policy[4];
struct ClassicalValueReadout {
    bool knotsActive = false;
    std::array<double, 6> knots {};
};
using ClassicalValueReadouts = std::array<ClassicalValueReadout, 4>;
ClassicalValueReadouts readouts;
float scale;
void resetPolicyCross() { std::memset(policy, 0, sizeof(policy)); }
void installPolicyCross(size_t table, const StoredPolicyCrossTable& p) { policy[table] = p; }
void installClassicalValueReadouts(const ClassicalValueReadouts& r) { readouts = r; }
void setScalingFactor(float value) { scale = value; }
}
#include "classical_trained.inc"
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    initializeEmbeddedClassicalModel();
    std::ofstream output(argv[1], std::ios::binary);
    auto bytes = [&](const void* p, size_t n) { output.write(static_cast<const char*>(p), n); };
    const double scale = Evaluation::scale;
    bytes(&scale, sizeof(scale));
    bytes(Evaluation::EVALS, sizeof(Evaluation::EVALS));
    bytes(Evaluation::EVALS_THREAT, sizeof(Evaluation::EVALS_THREAT));
    bytes(Evaluation::P4SCORES, sizeof(Evaluation::P4SCORES));
    bytes("RFCLMOD1", 8);
    const uint32_t header[] = {8, 6760, 4, 5, 0, 13};
    bytes(header, sizeof(header));
    bytes(Evaluation::policy, sizeof(Evaluation::policy));
    for (const auto& readout : Evaluation::readouts) assert(readout.knotsActive);
    return output ? 0 : 3;
}
