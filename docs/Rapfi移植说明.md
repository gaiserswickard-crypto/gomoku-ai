# Rapfi 移植与本次验证

日期：2026-11-08。当前 v4 `main.cpp` 由 `rapfi_port/rapfi_trained.cpp` 推广为主版本；旧 v3 的源码、可执行文件和 README 保存在 `versions/v3/`。

## 使用了什么

本版采用 Rapfi 的 Alpha-Beta/PVS 搜索，配合官方 **训练版经典棋形评估模型 `model260809`**。保留的模块包括增量棋盘与棋形更新、候选生成、置换表、迭代加深、走法排序、历史启发和 VCF 战术搜索。经典模型既参与局面评价，也提供走法排序等参数。

“训练版经典评估”与完整 NNUE 不是同一个模型。本版没有嵌入 NNUE：锁定版本的 freestyle NNUE 经实测常规无损压缩仍远超 1 MiB 源码限制，而且其文件头声明支持 13～22 路棋盘，不含课程的 12 路。这里没有以裁掉参数或改写棋盘声明的方式声称完整移植了 NNUE。模型尺寸、文件头、压缩结果和字节一致性核验见 `rapfi_weights.md`。

因此可以说“移植了 Rapfi 搜索和官方训练版经典评估”，不能说“拥有完整 Rapfi NNUE 的棋力”。本地对战也只支持该具体构建的有限结果。

## 为课程做的改动

课程入口 `CoursePort::Brain` 把行列坐标转换为 Rapfi 的 `(x,y)`，初始化指定中央四子，按 12×12 自由规则搜索。收到 `START` 回复 `OK`；收到 `PLACE` 记录对手棋子；收到 `TURN` 同步搜索、提交己方走法、输出坐标；收到 `END` 或 EOF 退出。

搜索关闭 pondering、交换开局与上游开局查询，避免产生课程不支持的动作。关闭 NNUE、MCTS、数据库后端、配置/模型文件读取及哈希表导入导出；日志不进入协议标准输出。`MULTI_THREADING` 在预处理阶段禁用，只保留一个同步搜索对象，不创建操作系统工作线程。

使用 `steady_clock` 计时，采用可移植的对齐分配，置换表设为 64 MiB。每步最多分配 1.4 秒，另外按照剩余空位估计还可能轮到自己多少次，用“80 秒目标减去已用时间”分配余量。这样兼顾平台的 2 秒单步和 90 秒整局限制。

开局候选扩展还跳过无实际坐标的 `Pos::PASS`，修复导入人工测试局面或异常协议恢复时的边界访问问题。正常课程四子开局不需要对外输出 PASS。

## 单文件与模型核验

| 项目 | 当前值 |
| --- | --- |
| 生成源码 | `rapfi_port/rapfi_trained.cpp`，主版本复制为 `main.cpp` |
| 源码大小 | 425,533 字节，9,900 行 |
| 课程上限 | 1,048,576 字节 |
| 源码 SHA-256 | `c33e687927f17d18f521a2497e09927c9fec749f67487aca67f5100bd8220953` |
| 经典模型 | 官方 `model260809.bin`，全部参数嵌入 |
| 模型解码大小 | 116,208 字节，回写结果与原模型逐字节一致 |
| 运行时外部数据 | 无 |

生成器会写出 `.manifest.json`，记录上游输入、适配器和模型初始化器的 SHA-256。对外提交限制针对源码字节数，不能用 `.exe` 大小代替。重新生成命令：

```text
python tools/build_rapfi.py --model trained --output rapfi_port/rapfi_trained.cpp
```

`--model builtin` 可生成基础经典评估对照版；它与本次训练模型版不同。`--keep-comments` 保留更多上游注释。修改应落在生成器或适配文件，再重新生成候选、编译和验证，最后更新主版本。

## 测试与实际对局

适配器断言开启版通过 **1,588 项断言、106 次不改变输入局面的搜索**，包含双方颜色、八种对称、立即胜点、强制防守、长连、VCF 链、活三防御、重置和满盘。GCC 协议测试通过 **9/9**；MSVC 的启动、走子和结束冒烟测试通过。测试输出和源码校验记录位于 `results/rapfi/`。

2026-11-08 的对战使用 Windows x64、GCC 16.2.0、`-O2`，所有对局绑定同一个逻辑 CPU；双方分别受每步 2 秒、每局 90 秒限制。A 为本版，交换黑白各下一局。

| 报告 | 本版执黑 | 本版执白 | 本版最长单步 | 本版最长己方累计 |
| --- | --- | --- | ---: | ---: |
| `results/rapfi/trained_vs_v3.json` | 19 手成五获胜 | 43 手对手成五，负 | 1.112 秒 | 2.640 秒 |
| `results/rapfi/trained_vs_reference.json` | 21 手成五获胜 | 42 手成五获胜 | 1.184 秒 | 10.293 秒 |

手数不含预置四子，计双方落子总数。四局均无超时、非法落子或进程异常判负；本版采样峰值工作集约 70.45 MiB。对 v3 的白方败局保留在报告中，没有隐去。不能把这四局合成一个可推广到全班的胜率，也没有证明黑方始终获胜。

当前实际编译运行验证在 Windows 完成。Linux 目标命令为 `g++ -std=c++17 -O2 main.cpp -o gomoku`，但尚未在 Linux 或学校 Docker 沙盒中执行，也未向学校平台提交。Windows 构建预留 8 MiB 栈；静态栈审计的来源、搜索帧估算及其局限见 `rapfi_port/STACK_AUDIT.txt` 和 `rapfi_port/PORT_NOTES.md`。

## 复现入口与阅读顺序

Windows 正式构建使用 `build.bat`，产物为 `build/gomoku.exe`。脚本支持 PATH 中的 G++、本地 w64devkit G++ 回退和 MSVC 回退。Windows 测试入口为 `tools\test_windows.bat`，加 `legacy` 参数可运行 v3 历史回归。Makefile 中 `make test` 检查当前 Rapfi 版，`make test-legacy` 保留 v3 回归；Linux 上这些命令是复现入口，不能作为已经执行过的 Linux 验证记录。

建议先阅读 `rapfi_port/course_protocol.inc` 理解协议、坐标和用时，再阅读 `tools/build_rapfi.py` 确认保留/裁剪的模块，然后对照锁定版本的 `reference/rapfi` 理解搜索与评估。`main.cpp` 是便于单文件提交的生成结果，不适合作为唯一的编辑源。旧 `docs/答辩要点.md` 解释的是 v1～v3 自写引擎，应结合版本区别使用。

## 来源与许可

- 引擎：[dotb1ue/rapfi](https://github.com/dotb1ue/rapfi)，提交 `1387d11312190ec66665d361ff07a7c70221b78a`，**GPL-3.0-or-later**。源码保留版权及许可声明，全文与贡献者见 `rapfi_port/COPYING`、`rapfi_port/AUTHORS`。
- 权重：[dotb1ue/rapfi-networks](https://github.com/dotb1ue/rapfi-networks)，提交 `7eeb19b55219a48138756293f92211a1539bab4d`，仓库声明全部权重按 **CC0** 发布。文本保存在 `rapfi_port/assets/WEIGHTS-CC0-LICENSE.txt`。
- 经典模型源文件 SHA-256：`8d4f518c58f9c7abe017de383a87d2d7506c62936ea5188004b7eb1780b99393`。

本版是 Rapfi 的派生移植；上游引擎、官方权重、课程适配和验证工作的来源分别记录在上述文件中。
