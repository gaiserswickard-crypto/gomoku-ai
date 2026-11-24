# Rapfi 课程单文件移植说明

本目录保留可复现候选程序。2026-11-08 验证后，训练模型版已复制为项目根目录的 `main.cpp`；旧版保留在 `versions/v3/`。`rapfi_trained.cpp` 使用 Rapfi 的 alpha-beta/PVS 搜索和官方训练后的经典棋型评估；不包含官方 NNUE 网络。`rapfi_classical.cpp` 使用相同搜索以及内置基础评估，供对照。

当前训练模型版为 UTF-8 单文件 **425,533 字节、9,900 行**，低于 1,048,576 字节源码限制。可执行文件大小不等同于提交源码大小。训练模型版 SHA-256 为 `c33e687927f17d18f521a2497e09927c9fec749f67487aca67f5100bd8220953`。

## 来源和许可

- 引擎：[Rapfi](https://github.com/dotb1ue/rapfi)，版本 `1387d11312190ec66665d361ff07a7c70221b78a`，GPL-3.0-or-later。版权声明保留在生成源码开头；完整许可证与贡献者见 `COPYING`、`AUTHORS`。
- 模型：官方 `model260809.bin`，网络仓库版本 `7eeb19b55219a48138756293f92211a1539bab4d`，CC0-1.0。许可见 `assets/WEIGHTS-CC0-LICENSE.txt`。原模型 SHA-256 为 `8d4f518c58f9c7abe017de383a87d2d7506c62936ea5188004b7eb1780b99393`。
- 模型嵌入包含四组规则评估、威胁、走法排序、策略残差、尺度和读出曲线。解码后的 116,208 字节模型经独立序列化回写验证，与原模型逐字节一致。
- 每份 `.manifest.json` 列出完整上游输入、适配器与模型初始化器的 SHA-256。`reference/rapfi` 保持只读，移植变更由 `tools/build_rapfi.py` 明示。

## 保留和调整

保留增量棋盘、棋型更新、候选生成、置换表、迭代加深、alpha-beta/PVS、走法排序、历史启发与 VCF 战术搜索。课程入口处理 12×12 自由规则（五个及以上取胜），使用指定初始四子和 `START/PLACE/TURN/END` 协议。

关闭 NNUE、MCTS、数据库后端、配置读取、模型文件读取和哈希表导入导出；消息输出不进入协议 stdout。内存分配改成可移植的对齐分配，时间来源为 `steady_clock`，置换表为 64 MiB。

源码在预处理阶段取消 `MULTI_THREADING`，保留一个同步执行的搜索对象，不创建 OS 工作线程。剩余 `<filesystem>` 类型与函数声明没有调用或实现，不产生文件访问。运行依赖只有标准输入、标准输出、系统时钟及正常 C++ 运行库，不需要模型文件、网络或棋库文件。

另外修复了开局候选扩展对 `Pos::PASS` 的处理：跳过没有物理坐标的 PASS，避免导入测试局面或异常协议恢复时越过棋盘边界。正常课程初始中央四子的路径不受影响。

## 可复现构建

在 `gomoku` 目录运行：

```text
python tools/build_rapfi.py --model trained
g++ -std=c++17 -O2 -DNDEBUG rapfi_port/rapfi_trained.cpp -o rapfi_trained
```

`--model builtin` 生成对照版；`--output PATH` 可以指定生成路径；`--keep-comments` 保留上游注释。生成器会校验单文件字节数并同时写入 `.manifest.json`。

本机 Windows MinGW-w64 GCC C++17 编译成功，Windows 链接时另加 `-Wl,--stack,8388608`。MSVC 使用 `/std:c++17 /O2 /EHsc /DNDEBUG /utf-8` 及链接参数 `/STACK:8388608` 编译成功；本机路径专用脚本为 `compile_msvc.cmd`。以上不代表已在实际 Linux 评测机运行。

## 验证范围

最终训练模型源码的断言开启版（`-DRAPFI_COURSE_DEBUG`）通过 **1,588 项断言、106 次不改变输入局面的搜索**，覆盖双方颜色、八种对称、立即成五、强制防守、长连、VCF 链、活三防御、重置和满盘。GCC release 协议 **9/9** 组通过；MSVC 的 START/TURN/END 冒烟测试通过。对局胜率与时间、内存数据由外部对战脚本另行记录，不由这些功能测试推断。

`STACK_AUDIT.txt` 与 `.su` 来自 GCC `-fstack-usage`：最大一次性初始化栈帧 354,512 字节；自由规则递归搜索栈帧约 5,024–5,072 字节。按引擎最大 256 层估算，搜索帧约需 1.24 MiB，尚不含其它调用开销，因此本地 Windows 构建显式预留 8 MiB 栈。该静态报告不是运行时最坏路径证明。
