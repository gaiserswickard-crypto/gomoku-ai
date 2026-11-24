// Audit the actual generated submission's initialization; no search is run.
#define RAPFI_COURSE_NO_MAIN
#include "../rapfi_trained.cpp"
#include <fstream>
#include <iomanip>

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    CoursePort::Brain brain;
    brain.reset(1);
    brain.reset(2); // Repeated START must retain all learned evaluation state.
    std::ofstream output(argv[1], std::ios::binary);
    auto bytes = [&](const void* p, size_t n) { output.write(static_cast<const char*>(p), n); };
    const double scale = Evaluation::ScalingFactor;
    bytes(&scale, sizeof(scale));
    bytes(Evaluation::EVALS, sizeof(Evaluation::EVALS));
    bytes(Evaluation::EVALS_THREAT, sizeof(Evaluation::EVALS_THREAT));
    for (int table = 0; table < 4; ++table) for (unsigned p = 0; p < PCODE_NB; ++p)
        for (int side = 0; side < 2; ++side) {
            Score value = Evaluation::P4SCORES[table][p][side];
            bytes(&value, sizeof(value));
        }
    bytes("RFCLMOD1", 8);
    const uint32_t header[] = {8, 6760, 4, 5, 0, 13};
    bytes(header, sizeof(header));
    for (int table = 0; table < 4; ++table) {
        const auto policy = Evaluation::storedPolicyCross(table);
        bytes(policy.data(), sizeof(policy));
    }
    std::ofstream readout(argv[2], std::ios::binary);
    for (const auto& row : Evaluation::classicalValueReadouts()) {
        if (!row.knotsActive) return 4;
        readout.write(reinterpret_cast<const char*>(row.knots.data()), sizeof(row.knots));
    }
    std::cout << std::setprecision(17) << "{\"scale\":" << scale << ",\"policy_active_masks\":[";
    for (int table = 0; table < 4; ++table)
        std::cout << (table ? "," : "") << int(Evaluation::POLICY_CROSS_ACTIVE_MASK[table]);
    std::cout << "],\"freestyle_readout_samples\":[";
    int samples[] = {-1000, -200, -50, 0, 50, 100, 200, 500, 1000};
    for (int i = 0; i < 9; ++i)
        std::cout << (i ? "," : "") << int(Evaluation::applyClassicalValueReadout(FREESTYLE, BLACK, Value(samples[i])));
    std::cout << "],\"threads\":" << Config::GeneralCfg.defaultThreadNum << "}\n";
    return output && readout ? 0 : 3;
}
