CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -pedantic
LDFLAGS ?=

.PHONY: all test test-legacy reference
all: build/gomoku

build:
	mkdir -p build

build/gomoku: main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

build/rapfi_adapter: tests/rapfi_adapter.cpp main.cpp | build
	$(CXX) $(CXXFLAGS) -DRAPFI_COURSE_DEBUG $< -o $@ $(LDFLAGS)

build/tactics: tests/tactics.cpp versions/v3/main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@

build/oracle: tests/oracle.cpp versions/v3/main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@

build/defense: tests/defense.cpp versions/v3/main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@

build/platform: tests/platform.cpp versions/v3/main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@

build/symmetry: tests/symmetry.cpp versions/v3/main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@

build/book_runtime: tests/book_runtime.cpp tools/book_runtime.inc | build
	$(CXX) $(CXXFLAGS) $< -o $@

build/book_engine: tests/book_engine.cpp versions/v3/main.cpp | build
	$(CXX) $(CXXFLAGS) $< -o $@

test: build/gomoku build/rapfi_adapter
	./build/rapfi_adapter
	python3 tests/protocol_test.py --engine build/gomoku

test-legacy: build/tactics build/oracle build/defense build/platform build/symmetry build/book_runtime build/book_engine
	./build/tactics
	./build/oracle
	./build/defense
	./build/platform
	./build/symmetry
	./build/book_runtime
	./build/book_engine

reference: | build
	$(CXX) $(CXXFLAGS) reference/Tongji-University-SE-Programming-Paradigm-main/gomuku.cpp -o build/reference
