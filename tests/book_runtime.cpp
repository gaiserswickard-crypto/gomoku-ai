#include "../tools/book_runtime.inc"
#include <iostream>
#include <stdexcept>
#include <string>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
static std::string encode(std::vector<unsigned char> bytes) {
    const char* alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~";
    while (bytes.size() % 4) bytes.push_back(0);
    std::string result;
    for (std::size_t i = 0; i < bytes.size(); i += 4) {
        std::uint32_t value = 0;
        for (int j = 0; j < 4; ++j) value = (value << 8) | bytes[i + j];
        char group[5];
        for (int j = 4; j >= 0; --j) { group[j] = alphabet[value % 85]; value /= 85; }
        result.append(group,5);
    }
    return result;
}
static bool load(gomoku_book::Book& book, const std::vector<unsigned char>& bytes) {
    const std::string encoded = encode(bytes);
    const char* chunks[] = {encoded.c_str()};
    return book.load(chunks,1,bytes.size());
}
static std::array<int,144> start() {
    std::array<int,144> board{};
    board[65] = board[78] = 2; board[66] = board[77] = 1;
    return board;
}
static bool contains(const std::vector<int>& values, int value) {
    for (int item : values) if (item == value) return true;
    return false;
}
int main() {
    try {
        gomoku_book::Book book;
        // B(4,4); either W(4,5)->B(4,6), or W(4,7)->B(3,4).
        const std::vector<unsigned char> data{255,1,52,2,53,1,54,0,55,1,40,0};
        require(load(book,data),"valid tree rejected");
        require(book.valid() && book.nodeCount() == 6,"wrong decoded node count");
        auto board = start();
        auto root = book.candidates(board);
        require(root.size() == 2 && contains(root,52) && contains(root,91),"colored root symmetry failed");
        require(book.candidates(board,2).empty(),"White must not use Black policy");
        require(book.candidates(board,1,8,0).empty(),"zero-budget lookup did not fall back");
        require(book.candidates(board,1,1).size() == 1,"candidate limit ignored");
        board[52] = 1; board[53] = 2;
        const auto before = board;
        auto moves = book.candidates(board);
        require(moves.size() == 1 && moves[0] == 54,"first white branch mismatch");
        require(board == before,"lookup changed board");
        board[53] = 0; board[55] = 2;
        moves = book.candidates(board);
        require(moves.size() == 1 && moves[0] == 40,"second white branch mismatch");
        board[55] = 0; board[0] = 2;
        require(book.candidates(board).empty(),"unlisted reply must fall back");
        board = start(); board[52] = 2; board[53] = 1;
        require(book.candidates(board).empty(),"wrong stone colors produced a hit");
        board = start(); board[65] = 1;
        require(book.candidates(board).empty(),"wrong initial board produced a hit");
        board = start(); board[0] = 1;
        require(book.candidates(board).empty(),"wrong turn parity produced a hit");
        board = start(); board[52] = 1; board[53] = 2; board[0] = 1; board[1] = 2;
        require(book.candidates(board).empty(),"extra balanced stones produced a partial-path hit");
        // Rotate a known complete position by 180 degrees, including its reply.
        board = start(); board[143 - 52] = 1; board[143 - 53] = 2;
        moves = book.candidates(board);
        require(moves.size() == 1 && moves[0] == 143 - 54,"inverse coordinate map failed");

        // Chunked encoding produces the same tree without long C++ literals.
        const std::string text = encode(data);
        const std::string left = text.substr(0,5), right = text.substr(5);
        const char* chunks[]{left.c_str(),right.c_str()};
        require(book.load(chunks,2,data.size()),"chunked Base85 rejected");
        // Two historical paths can reach the same exact position. Both next
        // moves are advisory candidates, independent of actual insertion order.
        const std::vector<unsigned char> transposition{
            255,2,52,1,53,1,54,1,55,1,56,0,
                  54,1,55,1,52,1,53,1,40,0};
        require(load(book,transposition),"transposition tree rejected");
        board = start(); board[54] = 1; board[55] = 2; board[52] = 1; board[53] = 2;
        moves = book.candidates(board);
        require(moves.size() == 2 && contains(moves,56) && contains(moves,40),
                "equivalent complete positions failed to merge candidates");
        require(!load(book,{255,1,52}),"truncated record accepted");
        require(!book.valid() && book.candidates(start()).empty(),"failed load retained a live book");
        require(!load(book,{255,1}),"missing child accepted");
        require(!load(book,{255,0,52,0}),"unreachable trailing node accepted");
        require(!load(book,{255,1,65,0}),"occupied initial square accepted");
        require(!load(book,{255,1,52,1,52,0}),"repeated path square accepted");
        require(!load(book,{255,1,144,0}),"out-of-board coordinate accepted");
        require(!load(book,{0,0}),"non-root marker accepted");
        require(!load(book,{255,141,1}),"impossible root degree accepted");
        const char* badAlphabet[]{"0000\""};
        require(!book.load(badAlphabet,1,2),"illegal Base85 character accepted");
        const char* overflow[]{"~~~~~"};
        require(!book.load(overflow,1,2),"overflowing Base85 group accepted");
        require(load(book,{255,0}) && book.candidates(start()).empty(),"empty book must load and fall back");
        std::cout << "PASS exact book lookup, both branches, colored symmetry, unknown replies, malformed data\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL book runtime: " << error.what() << '\n';
        return 1;
    }
}
