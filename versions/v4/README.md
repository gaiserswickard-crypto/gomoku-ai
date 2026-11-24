# 五子棋课程程序：v4 Rapfi 经典评估移植版

当前 `main.cpp` 是适配课程规则的 **Rapfi 搜索引擎 + 官方训练版经典评估模型 `model260809`**，包含全部运行所需代码与权重。它不包含完整 NNUE 网络。单文件为 **425,533 字节、9,900 行**，低于课程的 1 MiB 限制；运行时无需模型、配置或棋库文件。

2026-11-08 的本地换色测试：对往年参考程序 2 胜；对旧 v3 棋库版 1 胜 1 负。它仍有白方败局，没有证明执黑必胜，也没有向学校平台提交。版本与算法说明见 [Rapfi移植说明](docs/Rapfi移植说明.md)。

## 编译与使用

在本目录打开 PowerShell：

```powershell
.\build.bat
```

生成 `build\gomoku.exe`。脚本依次尝试 PATH 中的 G++、本地 `tmp\rapfi_tools\w64devkit\bin\g++.exe`，最后尝试 MSVC。Windows 构建显式设置 8 MiB 栈。

课程平台的目标编译方式是：

```bash
g++ -std=c++17 -O2 main.cpp -o gomoku
```

平台的单文件提交入口为 `main.cpp`，选择 G++ / C++17。当前实际验证使用 **Windows x64、GCC 16.2.0、`-O2`**；MSVC 编译与启动/走子冒烟检查也通过。**尚未在 Linux 评测沙盒运行**，不要把 Windows 通过等同于平台已通过。

程序通过标准输入输出参与对战，没有图形界面。手动烟测可依次输入：

```text
START 1
TURN
END 0
```

程序分别回复 `OK` 和一对行列坐标，`END` 不回复。`PLACE r c` 仅记录对手落子，不输出；每局保持同一个进程，EOF 正常退出。

## 课程适配

| 项目 | 当前实现 |
| --- | --- |
| 棋盘与坐标 | 12×12，行列均为 0～11 |
| 预置四子 | 黑 `(5,6)`、`(6,5)`；白 `(5,5)`、`(6,6)`，之后黑先走 |
| 胜负规则 | 自由规则，连续至少五子获胜，长连有效，无禁手 |
| 指令 | `START`、`PLACE`、`TURN`、`END`；响应立即刷新 |
| 单步时间 | 平台上限 2 秒；内部预算最多 1.4 秒，并按整局余量缩短 |
| 整局时间 | 平台上限 90 秒；内部按 80 秒目标分配剩余回合预算 |
| 资源 | 单线程同步搜索，64 MiB 置换表，不进行运行时文件或网络访问 |

## 已完成的验证

测试均针对 SHA-256 为 `c33e687927f17d18f521a2497e09927c9fec749f67487aca67f5100bd8220953` 的训练模型版源码。

- 适配器和战术测试：**1,588 项断言、106 次搜索通过**，覆盖颜色、坐标、八种对称、立即成五、必防、长连、连续冲四、活三防守、重置、满盘和搜索状态恢复。
- GCC 协议测试：**9/9 通过**。
- 权重解码后回写，与官方经典模型的 116,208 字节原始参数逐字节一致。
- 换色对战绑定同一个逻辑 CPU，双方每步 2 秒、每局 90 秒；四局均以成五结束，无超时或非法落子判负。

| 对手 | 本版执黑 | 本版执白 | 合计 |
| --- | --- | --- | --- |
| 旧 v3 棋库版 | 胜，19 手 | 负，43 手 | 1 胜 1 负 |
| 往年参考程序 | 胜，21 手 | 胜，42 手 | 2 胜 |

手数为预置四子之后双方合计落子数。这四局中，本版最长单步约 **1.184 秒**，最长一局己方累计约 **10.293 秒**，峰值工作集约 **70.45 MiB**。详细棋谱和资源记录在 `results/rapfi/trained_vs_v3.json`、`results/rapfi/trained_vs_reference.json`，功能测试记录也在 `results/rapfi/`。

这些是两个对手、固定官方开局的小样本结果，不能推断全班胜率、最终排名或执黑必胜。

## 复现与修改

生成训练模型版候选：

```powershell
python tools\build_rapfi.py --model trained --output rapfi_port\rapfi_trained.cpp
```

核对生成的 manifest、编译并测试候选后，再将其复制为 `main.cpp`，运行 `build.bat`。不要只手改生成源码后又重新生成，否则修改会被覆盖。生成器、课程协议适配和权重初始化器分别是 `tools/build_rapfi.py`、`rapfi_port/course_protocol.inc`、`rapfi_port/assets/classical_trained.inc`。

Makefile 的当前测试入口为 `make test`；历史 v3 回归入口为 `make test-legacy`。Windows 可运行 `tools\test_windows.bat`，检查当前适配器和协议；`tools\test_windows.bat legacy` 检查保留的 v3 测试。协议测试也可单独运行：

```powershell
python tests\protocol_test.py --engine build\gomoku.exe
```

本地换色对战示例：

```powershell
python tools\arena.py --black build\gomoku.exe --white build\reference.exe --games 2 --output results\local_match.json
```

普通 `arena.py` 检查协议、走子与用时；本次带 CPU 亲和性和进程资源采样的报告由 `tools/rapfi_benchmark.py` 生成。

## 来源与历史版本

本版基于 [Rapfi](https://github.com/dotb1ue/rapfi) 的开源代码，属于移植和修改，不能表述为独立编写了 Rapfi 引擎。引擎按 **GPL-3.0-or-later** 发布，版权声明保留在源码中，完整许可和作者名单见 `rapfi_port/COPYING`、`rapfi_port/AUTHORS`；官方训练权重按 **CC0** 发布，文本见 `rapfi_port/assets/WEIGHTS-CC0-LICENSE.txt`。

旧 v1、v2、v3 保留在 `versions/`。旧 v3 的完整说明已保存为 `versions/v3/README.md`；`docs/答辩要点.md`、`docs/升级说明.md`、`docs/棋库版说明.md` 仍描述历史引擎，不是当前 Rapfi 实现的逐函数说明。当前详细技术记录见 [Rapfi移植说明](docs/Rapfi移植说明.md)、[移植记录](rapfi_port/PORT_NOTES.md) 和 [权重核验](docs/rapfi_weights.md)。
