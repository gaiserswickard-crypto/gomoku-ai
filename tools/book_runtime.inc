// Exact opening-tree lookup. The generated submission embeds this source and data.
// Data: preorder (move byte, unsigned LEB128 child count), including root move 255.
// Root is the official four-stone board; its children are Black's first moves.
// RFC 1924 / Python b85 alphabet, padded four bytes per five source characters.
#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace gomoku_book {
class Book {
    struct Node {
        std::uint32_t end;
        unsigned char move, depth;
    };
    std::vector<Node> nodes_;
    bool valid_ = false;
    static constexpr std::size_t MAX_NODES = 500000;
    static int transform(int pos, int symmetry) {
        int r = pos / 12, c = pos % 12;
        if (symmetry & 4) c = 11 - c;
        for (int i = 0; i < (symmetry & 3); ++i) {
            const int old = r; r = c; c = 11 - old;
        }
        return r * 12 + c;
    }
    static int initial(int pos) {
        return pos == 65 || pos == 78 ? 2 : (pos == 66 || pos == 77 ? 1 : 0);
    }

public:
    bool valid() const { return valid_; }
    std::size_t nodeCount() const { return nodes_.size(); }

    bool load(const char* const* chunks, std::size_t chunkCount, std::size_t rawBytes) {
        valid_ = false;
        nodes_.clear();
        if (!chunks || !chunkCount || chunkCount > 4096 || rawBytes < 2 || rawBytes > 4000000)
            return false;
        static const char alphabet[] =
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~";
        int digits[128];
        for (int& value : digits) value = -1;
        for (int i = 0; i < 85; ++i) digits[static_cast<unsigned char>(alphabet[i])] = i;
        const std::size_t paddedBytes = (rawBytes + 3) / 4 * 4;
        std::vector<unsigned char> bytes;
        bytes.reserve(paddedBytes);
        for (std::size_t part = 0; part < chunkCount; ++part) {
            if (!chunks[part]) return false;
            const char* text = chunks[part];
            std::size_t length = 0;
            while (length <= 4000 && text[length]) ++length;
            if (length > 4000 || length % 5) return false;
            for (std::size_t offset = 0; offset < length; offset += 5) {
                if (bytes.size() >= paddedBytes) return false;
                std::uint64_t group = 0;
                for (int j = 0; j < 5; ++j) {
                    const unsigned char ch = static_cast<unsigned char>(text[offset + j]);
                    if (ch >= 128 || digits[ch] < 0) return false;
                    group = group * 85 + static_cast<unsigned>(digits[ch]);
                }
                if (group > 0xffffffffULL) return false;
                for (int shift = 24; shift >= 0; shift -= 8)
                    bytes.push_back(static_cast<unsigned char>(group >> shift));
            }
        }
        if (bytes.size() != paddedBytes) return false;
        for (std::size_t i = rawBytes; i < bytes.size(); ++i) if (bytes[i]) return false;
        bytes.resize(rawBytes);

        struct Frame { std::uint32_t index, remaining; };
        std::vector<Frame> stack;
        stack.reserve(141);
        std::vector<Node> parsed;
        parsed.reserve(rawBytes / 2 < MAX_NODES ? rawBytes / 2 : MAX_NODES);
        bool occupied[144]{};
        for (int p = 0; p < 144; ++p) occupied[p] = initial(p) != 0;
        std::size_t cursor = 0;
        while (cursor < bytes.size()) {
            while (!stack.empty() && !stack.back().remaining) {
                const std::uint32_t index = stack.back().index;
                parsed[index].end = static_cast<std::uint32_t>(parsed.size());
                if (index) occupied[parsed[index].move] = false;
                stack.pop_back();
            }
            if (!parsed.empty() && stack.empty()) return false;
            if (parsed.size() >= MAX_NODES || stack.size() > 140) return false;
            const unsigned char move = bytes[cursor++];
            const unsigned depth = static_cast<unsigned>(stack.size());
            std::uint32_t children = 0;
            unsigned shift = 0;
            for (;;) {
                if (cursor >= bytes.size() || shift >= 28) return false;
                const unsigned char value = bytes[cursor++];
                children |= static_cast<std::uint32_t>(value & 127) << shift;
                if (!(value & 128)) break;
                shift += 7;
            }
            if (children > 140 - depth) return false;
            if (!depth) {
                if (move != 255 || !parsed.empty()) return false;
            } else {
                if (move >= 144 || occupied[move]) return false;
                --stack.back().remaining;
                occupied[move] = true;
            }
            const std::uint32_t index = static_cast<std::uint32_t>(parsed.size());
            parsed.push_back({index + 1, move, static_cast<unsigned char>(depth)});
            if (children) stack.push_back({index, children});
            else if (depth) occupied[move] = false;
        }
        while (!stack.empty() && !stack.back().remaining) {
            const std::uint32_t index = stack.back().index;
            parsed[index].end = static_cast<std::uint32_t>(parsed.size());
            if (index) occupied[parsed[index].move] = false;
            stack.pop_back();
        }
        if (!stack.empty() || parsed.empty()) return false;
        nodes_.swap(parsed);
        valid_ = true;
        return true;
    }

    // All current stones, their colors, and the total stone count must match
    // a tree path. No probabilistic hash can turn an unrelated board into a hit.
    // The tree is advisory: unlisted replies and unproved leaves stay unknown.
    std::vector<int> candidates(const std::array<int,144>& board, int side = 1,
                                int maxCandidates = 8, int budgetMs = 3) const {
        std::vector<int> result;
        if (!valid_ || side != 1 || maxCandidates <= 0 || budgetMs <= 0) return result;
        if (maxCandidates > 8) maxCandidates = 8;
        int black = 0, white = 0;
        for (int p = 0; p < 144; ++p) {
            if (board[p] < 0 || board[p] > 2) return {};
            if (initial(p) && board[p] != initial(p)) return {};
            black += board[p] == 1; white += board[p] == 2;
        }
        if (black != white || black < 2 || black + white >= 144) return result;
        const int targetDepth = black + white - 4;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(budgetMs);
        std::size_t visited = 0;
        bool selected[144]{};
        for (int symmetry = 0; symmetry < 8; ++symmetry) {
            bool preservesColors = true;
            for (int p : {65,66,77,78})
                if (initial(p) != initial(transform(p,symmetry))) preservesColors = false;
            if (!preservesColors) continue;
            std::array<int,144> transformed{}, inverse{};
            for (int p = 0; p < 144; ++p) {
                const int q = transform(p,symmetry);
                transformed[q] = board[p]; inverse[q] = p;
            }
            std::size_t index = 1;
            while (index < nodes_.size()) {
                if ((++visited & 127) == 0 && std::chrono::steady_clock::now() >= deadline) return {};
                if (visited > 2000000) return {};
                const Node& node = nodes_[index];
                if (node.depth == targetDepth + 1) {
                    const int move = inverse[node.move];
                    if (!board[move] && !selected[move]) {
                        selected[move] = true;
                        result.push_back(move);
                        if (static_cast<int>(result.size()) >= maxCandidates) return result;
                    }
                    index = node.end;
                } else if (node.depth <= targetDepth &&
                           transformed[node.move] == (node.depth % 2 ? 1 : 2)) {
                    ++index;
                } else index = node.end;
            }
            if (std::chrono::steady_clock::now() >= deadline) return {};
        }
        return result;
    }
};
} // namespace gomoku_book
