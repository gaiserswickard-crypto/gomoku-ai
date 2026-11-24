"""Inspect pinned official Rapfi weights; emit a standalone classical initializer.

Only Python's standard library is needed. LZ4 frame and block decoding below is
used for reproducible asset extraction, not for editing upstream model files.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import itertools
import json
import lzma
from pathlib import Path
import re
import struct
import tomllib
import zlib

ROOT = Path(__file__).resolve().parents[1]
NETWORKS = ROOT / "reference/rapfi-networks"
RAPFI = ROOT / "reference/rapfi"
ASSETS = ROOT / "rapfi_port/assets"
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~"


def lz4_block(block: bytes, prefix: bytes = b"") -> bytes:
    output = bytearray(prefix)
    at = 0
    while at < len(block):
        token = block[at]
        at += 1
        literal = token >> 4
        if literal == 15:
            while True:
                n = block[at]
                at += 1
                literal += n
                if n != 255:
                    break
        assert at + literal <= len(block)
        output.extend(block[at:at + literal])
        at += literal
        if at == len(block):
            break
        offset = int.from_bytes(block[at:at + 2], "little")
        at += 2
        assert 0 < offset <= len(output)
        match = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                n = block[at]
                at += 1
                match += n
                if n != 255:
                    break
        if offset >= match:
            output.extend(output[len(output) - offset:len(output) - offset + match])
        else:
            pattern = output[-offset:]
            output.extend((pattern * ((match + offset - 1) // offset))[:match])
    return bytes(output[len(prefix):])


def xxh32(data: bytes, seed: int = 0) -> int:
    """xxHash32, needed to verify LZ4 frame header/content checksums."""
    mask = (1 << 32) - 1
    p1, p2, p3, p4, p5 = 2654435761, 2246822519, 3266489917, 668265263, 374761393
    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & mask
    def rnd(acc, value):
        return (rol((acc + value * p2) & mask, 13) * p1) & mask
    at = 0
    if len(data) >= 16:
        v = [(seed + p1 + p2) & mask, (seed + p2) & mask, seed, (seed - p1) & mask]
        while at <= len(data) - 16:
            for i in range(4):
                v[i] = rnd(v[i], int.from_bytes(data[at:at + 4], "little"))
                at += 4
        h = (rol(v[0], 1) + rol(v[1], 7) + rol(v[2], 12) + rol(v[3], 18)) & mask
    else:
        h = (seed + p5) & mask
    h = (h + len(data)) & mask
    while at <= len(data) - 4:
        h = (h + int.from_bytes(data[at:at + 4], "little") * p3) & mask
        h = (rol(h, 17) * p4) & mask
        at += 4
    while at < len(data):
        h = (h + data[at] * p5) & mask
        h = (rol(h, 11) * p1) & mask
        at += 1
    h ^= h >> 15
    h = (h * p2) & mask
    h ^= h >> 13
    h = (h * p3) & mask
    return h ^ (h >> 16)


def lz4_frame(data: bytes) -> tuple[bytes, list[bytes]]:
    assert data[:4] == bytes.fromhex("04224d18")
    flags = data[4]
    assert flags >> 6 == 1
    at = 6
    content_size = None
    if flags & 8:
        content_size = int.from_bytes(data[at:at + 8], "little")
        at += 8
    if flags & 1:
        raise ValueError("External LZ4 dictionaries are not supported")
    assert ((xxh32(data[4:at]) >> 8) & 255) == data[at]
    at += 1
    output = bytearray()
    blocks = []
    while True:
        size = int.from_bytes(data[at:at + 4], "little")
        at += 4
        if size == 0:
            break
        block = data[at:at + (size & 0x7fffffff)]
        at += len(block)
        if flags & 16:
            assert xxh32(block) == int.from_bytes(data[at:at + 4], "little")
            at += 4
        if size & 0x80000000:
            output.extend(block)
        else:
            blocks.append(block)
            prefix = b"" if flags & 32 else bytes(output[-65536:])
            output.extend(lz4_block(block, prefix))
    if flags & 4:
        assert xxh32(output) == int.from_bytes(data[at:at + 4], "little")
        at += 4
    assert at == len(data)
    assert content_size is None or len(output) == content_size
    return bytes(output), blocks


def validate_builtin() -> dict:
    src = (RAPFI / "Rapfi/internalConfig.cpp").read_text(encoding="utf-8")
    config = tomllib.loads(src.split('R"internalConfig(', 1)[1].split(')internalConfig"', 1)[0])
    inc = (ASSETS / "classical_builtin.inc").read_text(encoding="utf-8")
    def parse(name):
        return [int(n) for n in re.search(rf"{name}\[\d+\] = \{{([^}}]+)\}}", inc)[1].split(",")]
    normal, renju, score = parse("normal"), parse("renju"), parse("moveScore")
    model = config["model"]
    assert normal == model["eval"]["table2"]
    assert renju == model["eval"]["renju"]["table2"]
    assert score == model["score"]["self"]["table1"] == model["score"]["oppo"]["table1"]
    pair_order = {pair: i for i, pair in enumerate(itertools.combinations_with_replacement(range(16), 2))}
    count = 0
    for patterns in itertools.combinations_with_replacement(range(16), 4):
        for weights in (normal, renju):
            expected = sum(weights[pair_order[pair]] for pair in itertools.combinations(patterns, 2))
            actual = sum(weights[a * 16 + b - a * (a + 1) // 2] for a, b in itertools.combinations(patterns, 2))
            assert expected == actual and -16384 <= actual <= 16383
        order = sum(score[p] for p in patterns)
        assert -8192 <= order * 2 <= 8191
        count += 1
    assert count == 3876
    return {"combinations": count, "arrays_match_official_toml": True,
            "pair_indices_match_independent_enumeration": True, "no_clamping_difference": True}


def fnv1a(data: bytes) -> str:
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xffffffff
    return f"{h:08x}"


def emit_classical(path: Path) -> dict:
    raw, blocks = lz4_frame(path.read_bytes())
    assert len(blocks) == 1 and lz4_block(blocks[0]) == raw
    scale = struct.unpack_from("<d", raw)[0]
    table_end = 8 + 4 * 3876 * 2 + 4 * 2048 * 2 + 4 * 3876 * 4
    magic, version, payload_size, table_count, contexts, components, patterns = struct.unpack_from("<8s6I", raw, table_end)
    assert (magic, version, table_count, contexts, components, patterns) == (b"RFCLMOD1", 8, 4, 5, 0, 13)
    assert payload_size == 4 * 5 * 13 * 13 * 2
    assert len(raw) == table_end + 32 + payload_size
    config = tomllib.loads((NETWORKS / "config-example/gomocalc-classical260809.toml").read_text(encoding="utf-8"))["model"]
    keys = ["value_readout_knots", "value_readout_knots_standard", "value_readout_knots_renju_black", "value_readout_knots_renju_white"]
    knots = [config[key] for key in keys]
    packed = blocks[0]
    encoded = base64.b85encode(packed + b"\0" * (-len(packed) % 4)).decode("ascii")
    assert base64.b85decode(encoded)[:len(packed)] == packed
    lines = [encoded[i:i + 100] for i in range(0, len(encoded), 100)]
    code = """// Genuine Rapfi classical model260809; weights are CC0-1.0.
// Engine source revision 1387d11312190ec66665d361ff07a7c70221b78a (GPL-3.0-or-later).
// Network revision 7eeb19b55219a48138756293f92211a1539bab4d.
// Generated by tools/inspect_rapfi_weights.py; no runtime file dependencies.
// Model file SHA256: @SHA@
// Decompressed model SHA256: @RAWSHA@
// Preserves all four rule tables, threat tables, policy residuals, scale and readout knots.
inline void initializeEmbeddedClassicalModel() {
    static_assert(PCODE_NB == 3876 && THREAT_NB == 2048 && RULE_NB == 3);
    static_assert(Evaluation::PolicyStoredContextCount == 5 && Evaluation::PolicyStoredPatternCount == 13);
    static const char alphabet[] = "@ALPHABET@";
    static const char* const data[] = {
@DATA@};
    unsigned char inverse[256] = {};
    for (unsigned i = 0; i < 85; ++i) inverse[static_cast<unsigned char>(alphabet[i])] = static_cast<unsigned char>(i);
    std::vector<unsigned char> packed;
    packed.reserve(@PACKED@ + 4);
    for (const char* row : data) for (size_t i = 0; row[i]; i += 5) {
        uint32_t word = 0;
        for (unsigned j = 0; j < 5; ++j) word = word*85 + inverse[static_cast<unsigned char>(row[i+j])];
        for (int shift = 24; shift >= 0; shift -= 8) packed.push_back(static_cast<unsigned char>(word >> shift));
    }
    packed.resize(@PACKED@);
    std::vector<unsigned char> raw;
    raw.reserve(@RAW@);
    size_t at = 0;
    while (at < packed.size()) {
        unsigned token = packed[at++], count = token >> 4;
        if (count == 15) { unsigned n; do { n = packed[at++]; count += n; } while (n == 255); }
        for (unsigned i = 0; i < count; ++i) raw.push_back(packed[at++]);
        if (at == packed.size()) break;
        unsigned offset = packed[at] | (unsigned(packed[at+1]) << 8); at += 2;
        count = (token & 15) + 4;
        if ((token & 15) == 15) { unsigned n; do { n = packed[at++]; count += n; } while (n == 255); }
        for (unsigned i = 0; i < count; ++i) raw.push_back(raw[raw.size()-offset]);
    }
    assert(raw.size() == @RAW@);
    uint32_t checksum = 2166136261U;
    for (unsigned char b : raw) checksum = (checksum ^ b)*16777619U;
    if (raw.size() != @RAW@ || checksum != 0x@FNV@U) std::abort();
    at = 8;
    auto nextScore = [&]() -> int16_t {
        unsigned value = raw[at] | (unsigned(raw[at+1]) << 8); at += 2;
        return static_cast<int16_t>(value < 32768 ? int(value) : int(value)-65536);
    };
    for (int t = 0; t < 4; ++t) for (unsigned p = 0; p < PCODE_NB; ++p) Evaluation::EVALS[t][p] = nextScore();
    for (int t = 0; t < 4; ++t) for (unsigned p = 0; p < THREAT_NB; ++p) Evaluation::EVALS_THREAT[t][p] = nextScore();
    for (int t = 0; t < 4; ++t) for (unsigned p = 0; p < PCODE_NB; ++p)
        for (int side = 0; side < 2; ++side) Evaluation::P4SCORES[t][p][side] = nextScore();
    at += 32; // Checked v8 extension header during asset generation.
    Evaluation::resetPolicyCross();
    for (int t = 0; t < 4; ++t) {
        Evaluation::StoredPolicyCrossTable policy {};
        for (auto &v : policy) v = nextScore();
        Evaluation::installPolicyCross(t, policy);
    }
    assert(at == raw.size());
    static const double knots[4][6] = {@KNOTS@};
    Evaluation::ClassicalValueReadouts readouts {};
    for (int t = 0; t < 4; ++t) {
        readouts[t].knotsActive = true;
        for (int k = 0; k < 6; ++k) readouts[t].knots[k] = knots[t][k];
    }
    Evaluation::installClassicalValueReadouts(readouts);
    Evaluation::setScalingFactor(@SCALE@f);
}
"""
    substitutions = {"SHA": hashlib.sha256(path.read_bytes()).hexdigest(), "RAWSHA": hashlib.sha256(raw).hexdigest(),
                     "ALPHABET": ALPHABET, "DATA": "\n".join('        "' + line + '",' for line in lines),
                     "PACKED": str(len(packed)), "RAW": str(len(raw)), "FNV": fnv1a(raw),
                     "KNOTS": ",".join("{" + ",".join(repr(k) for k in row) + "}" for row in knots),
                     "SCALE": repr(scale)}
    for key, value in substitutions.items():
        code = code.replace("@" + key + "@", value)
    dest = ASSETS / "classical_trained.inc"
    dest.write_text(code, encoding="utf-8", newline="\n")
    return {"file": str(path.relative_to(ROOT)), "sha256": substitutions["SHA"],
            "raw_sha256": substitutions["RAWSHA"], "raw_fnv1a32": fnv1a(raw),
            "raw_bytes": len(raw), "scale": scale, "readout_knots": knots,
            "initializer": str(dest.relative_to(ROOT)), "initializer_bytes": dest.stat().st_size,
            "initializer_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "table_dimensions": {"eval": [4, 3876], "threat": [4, 2048], "score": [4, 3876, 2], "policy": [4, 5, 13, 13]}}


def measure(path: Path, expensive: bool) -> dict:
    data = path.read_bytes()
    raw, _ = lz4_frame(data)
    result = {"file": str(path.relative_to(ROOT)), "file_bytes": len(data), "raw_bytes": len(raw),
              "sha256": hashlib.sha256(data).hexdigest(), "raw_sha256": hashlib.sha256(raw).hexdigest(),
              "base85_file_chars": (len(data) * 5 + 3) // 4,
              "zlib9_file_bytes": len(zlib.compress(data, 9)), "zlib9_raw_bytes": len(zlib.compress(raw, 9)),
              "lz4_checksums_verified": True}
    if expensive:
        result["lzma9_raw_bytes"] = len(lzma.compress(raw, preset=9))
        result["lzma9_file_bytes"] = len(lzma.compress(data, preset=9))
    if path.suffix == ".lz4":
        magic, arch, rules, boards, length = struct.unpack_from("<5I", raw)
        assert magic == 0xacd8cc6a
        result["nnue_header"] = {"arch_hash": f"{arch:08x}", "rule_mask": rules,
            "board_sizes": [i + 1 for i in range(32) if (boards >> i) & 1],
            "description": raw[20:20 + length].decode("utf-8"), "weight_payload_bytes": len(raw) - 20 - length}
    return result


def architecture_sizes() -> dict:
    # From mixcommon.h and mix9svqnnue.cpp at the pinned source revision.
    arrays = {"value_sum": 145 * 2560, "change_counts": 145 * 4,
              "inner_version_indices": 145 * 144 * 2,
              "outer_version_indices": 146 * 196 * 2,
              "shape_indices": 4541 * 16, "map_sum": 4541 * 128,
              "map_convolution": 13193 * 64}
    return {"mix9svq": {"shape_count": 442503, "feature_dimension": 64,
        "codebook_int16_values": 2 * 65536 * 64, "codebook_ram_bytes": 2 * 65536 * 64 * 2,
        "packed_10bit_codebook_bytes": 2 * 65536 * 64 * 10 // 8,
        "mapping_uint16_indices": 2 * 442503, "mapping_index_bytes": 2 * 442503 * 2,
        "depthwise_conv_bytes": 640, "head_bucket_bytes": 152768,
        "weight_struct_bytes": 18700672, "accumulator_12x12_allocations_bytes": arrays,
        "one_accumulator_12x12_array_bytes": sum(arrays.values()),
        "two_accumulators_12x12_array_bytes": sum(arrays.values()) * 2,
        "ram_note": "Derived array/struct sizes, excluding allocator overhead, board, search stack, TT, transient decode, and caches. The official model header rejects board size 12."},
        "mix10": {"mapping_int16_values": 2 * 442503 * 64,
                  "mapping_ram_bytes": 2 * 442503 * 64 * 2,
                  "note": "Architecture only; no mix10 weights are present in the pinned network repository."}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", action="store_true", help="Also measure all models; may take about one minute")
    args = parser.parse_args()
    report = {"engine_revision": "1387d11312190ec66665d361ff07a7c70221b78a",
              "networks_revision": "7eeb19b55219a48138756293f92211a1539bab4d",
              "builtin_validation": validate_builtin(),
              "trained_initializer": emit_classical(NETWORKS / "classical/model260809.bin"),
              "architecture_sizes": architecture_sizes()}
    roundtrip = ASSETS / "trained_roundtrip.bin"
    if roundtrip.exists():
        expected, _ = lz4_frame((NETWORKS / "classical/model260809.bin").read_bytes())
        assert roundtrip.read_bytes() == expected
        report["trained_initializer"]["cpp_roundtrip_verified_bytes"] = len(expected)
        report["trained_initializer"]["cpp_roundtrip_sha256"] = hashlib.sha256(expected).hexdigest()
    if args.measure:
        report["files"] = [measure(path, "freestyle" in path.name or path.suffix == ".bin")
                           for path in sorted(NETWORKS.rglob("*.bin*"))]
    dest = ROOT / "results/rapfi/weights.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
