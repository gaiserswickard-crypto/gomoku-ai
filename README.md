# 五子棋大脑程序（课程期中项目）

同济大学软件工程《程序设计范式》期中项目：按照课程通信协议（stdin/stdout 指令交互）实现的五子棋走子程序（"大脑程序"）。程序提交至课程在线评测平台，与全年级同学的程序进行两两机-机对抗，**最终总积分位列年级前 10**。

当前 `main.cpp` 是适配课程规则的 **Rapfi 搜索引擎 + 官方训练版经典评估模型 `model260809`**，包含全部运行所需代码与权重。它不包含完整 NNUE 网络。单文件为 **425,533 字节、9,900 行**，低于课程的 1 MiB 单文件限制；运行时无需模型、配置或棋库文件。

> 本项目基于开源五子棋引擎 [Rapfi](https://github.com/dotb1ue/rapfi)（GPL-3.0-or-later）移植和修改，并非独立编写的引擎，详见下文「来源与许可」。

## 比赛规则概要

- 12×12 棋盘，中央预置四子（黑 `(5,6)`、`(6,5)`；白 `(5,5)`、`(6,6)`），之后黑先走。
- 自由规则：连续至少五子获胜，长连有效，无禁手。
- 单步限时 2 秒，整局累计限时 90 秒，内存上限 350 MB，单线程。
- 平台运行于 Linux x86_64 Docker 沙盒，G++ C++17、`-O2` 编译，单文件提交。
- 程序通过 stdin 接收 `START` / `PLACE` / `TURN` / `END` 指令，通过 stdout 响应落子坐标。

## 课程适配

| 项目 | 实现 |
| --- | --- |
| 棋盘与坐标 | 12×12，行列均为 0～11 |
| 预置四子 | 黑 `(5,6)`、`(6,5)`；白 `(5,5)`、`(6,6)`，之后黑先走 |
| 胜负规则 | 自由规则，连续至少五子获胜，长连有效，无禁手 |
| 指令 | `START`、`PLACE`、`TURN`、`END`；响应立即刷新 |
| 单步时间 | 平台上限 2 秒；内部预算最多 1.4 秒，并按整局余量缩短 |
| 整局时间 | 平台上限 90 秒；内部按 80 秒目标分配剩余回合预算 |
| 资源 | 单线程同步搜索，64 MiB 置换表，不进行运行时文件或网络访问 |

## 编译与使用

Linux（与课程平台一致）：

```bash
g++ -std=c++17 -O2 main.cpp -o gomoku
```

Windows：在本目录打开 PowerShell 运行 `build.bat`，生成 `build\gomoku.exe`。

程序通过标准输入输出参与对战，没有图形界面。手动烟测可依次输入：

```text
START 1
TURN
END 0
```

程序分别回复 `OK` 和一对行列坐标，`END` 不回复。`PLACE r c` 仅记录对手落子，不输出；每局保持同一个进程，EOF 正常退出。

## 仓库结构

```text
main.cpp          最终提交参赛的单文件大脑程序
docs/             移植说明、权重核验、答辩要点等技术文档
tests/            协议、战术、对称性等测试源码
tools/            构建生成器、本地对战、协议测试等脚本
rapfi_port/       Rapfi 移植工程：协议适配、权重初始化器、移植记录
versions/         v1～v4 历史版本（含早期自研引擎与棋库版）
results/          本地与平台对战的复盘记录和资源占用数据
```

## 已完成的验证

- 适配器和战术测试：**1,588 项断言、106 次搜索通过**，覆盖颜色、坐标、八种对称、立即成五、必防、长连、连续冲四、活三防守、重置、满盘和搜索状态恢复。
- GCC 协议测试：**9/9 通过**。
- 权重解码后回写，与官方经典模型的 116,208 字节原始参数逐字节一致。
- 本地换色对战绑定同一个逻辑 CPU，双方每步 2 秒、每局 90 秒；对局均以成五结束，无超时或非法落子判负。
- 平台对局的离线复盘见 `results/platform/analysis.md`。

## 复现与修改

生成训练模型版候选：

```powershell
python tools\build_rapfi.py --model trained --output rapfi_port\rapfi_trained.cpp
```

核对生成的 manifest、编译并测试候选后，再将其复制为 `main.cpp`。生成器、课程协议适配和权重初始化器分别是 `tools/build_rapfi.py`、`rapfi_port/course_protocol.inc`、`rapfi_port/assets/classical_trained.inc`。

协议测试可单独运行：

```bash
python tests/protocol_test.py --engine build/gomoku.exe
```

本地换色对战示例：

```bash
python tools/arena.py --black build/gomoku.exe --white build/reference.exe --games 2 --output results/local_match.json
```

## 来源与许可

本项目基于 [Rapfi](https://github.com/dotb1ue/rapfi)（提交 `1387d11312190ec66665d361ff07a7c70221b78a`）的开源代码移植和修改，**不能表述为独立编写了 Rapfi 引擎**。

- 引擎与派生代码按 **GPL-3.0-or-later** 发布，版权声明保留在源码中，完整许可和作者名单见 `COPYING`、`AUTHORS`。
- 官方训练权重按 **CC0** 发布，文本见 `rapfi_port/assets/WEIGHTS-CC0-LICENSE.txt`。

旧 v1、v2、v3 保留在 `versions/`（含早期自研引擎）。详细技术记录见 [Rapfi移植说明](docs/Rapfi移植说明.md)、[移植记录](rapfi_port/PORT_NOTES.md) 和 [权重核验](docs/rapfi_weights.md)。
