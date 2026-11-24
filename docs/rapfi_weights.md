# Rapfi 权重移植与体积核验

资产核验日期：2026-11-07；最终集成复核日期：2026-11-08。所有尺寸为实际字节数；课程单文件限制为 1,048,576 字节。

## 结论

可以在提交源码中嵌入真正的 Rapfi **训练版经典评估模型**，无需任何外部文件。
已生成 `rapfi_port/assets/classical_trained.inc`，84,785 字节，使用官方 `model260809.bin` 的全部权重。
它与 `classical_builtin.inc` 提供相同的 `initializeEmbeddedClassicalModel()` 接口。

本次锁定的官方仓库版本中的完整 freestyle **NNUE** 权重无法通过实测的无损压缩方案塞入 1 MiB 源码。
更关键的是，该 NNUE 文件的真实头部只声明支持 **13–22 路棋盘**，不包含课程的 12×12；官方加载器会拒绝 12 路。
经典版和完整 NNUE 版不能当作同一个棋力等级。移植是否增强了本作业，仍需由同一规则、同一时限下的对战验证；本报告不声称必胜或已达到官方 NNUE 棋力。

## 来源与许可

- 引擎：<https://github.com/dotb1ue/rapfi>，提交 `1387d11312190ec66665d361ff07a7c70221b78a`，**GPL-3.0-or-later**。
- 权重：<https://github.com/dotb1ue/rapfi-networks>，提交 `7eeb19b55219a48138756293f92211a1539bab4d`，与引擎子模块指定版本相同。
- 权重仓库 README 明确将所有权重以 **CC0** 发布；完整文本保存在 `reference/rapfi-networks/LICENSE`，并复制为 `rapfi_port/assets/WEIGHTS-CC0-LICENSE.txt`。
- 训练版源文件：`reference/rapfi-networks/classical/model260809.bin`。
- 源文件 SHA256：`8d4f518c58f9c7abe017de383a87d2d7506c62936ea5188004b7eb1780b99393`。
- 解压后 SHA256：`88f92bc96eca6eac9702b697b62c5768c9f921ad4c24278e118462c7c6fdde42`。
- 生成的 initializer SHA256：`dc1958fc0c86711db7f244d05ba4c16ab681a314e403280e24c317c7d6d1dc61`。

## 实测压缩尺寸

| 权重 | 仓库文件（LZ4） | 解压后 | 解压后重新 zlib-9 | 解压后重新 LZMA-9 |
|---|---:|---:|---:|---:|
| classical model210901 | 25,896 | 116,208 | 21,261 | 17,484 |
| classical model220723 | 68,821 | 116,208 | 54,489 | 44,292 |
| classical model260809 | 57,624 | 116,208 | 39,005 | 30,564 |
| mix9svq freestyle | 10,030,398 | 12,409,332 | 9,604,228 | 7,733,184 |
| mix9svq renju black | 9,984,172 | 12,409,332 | 9,566,282 | 未测 |
| mix9svq renju white | 9,844,944 | 12,409,332 | 9,426,855 | 未测 |
| mix9svq standard | 10,345,775 | 12,409,332 | 9,862,952 | 未测 |

freestyle NNUE 的 LZMA-9 结果再用 Base85 表示，需要约 **9,666,480 个字符**，尚未计算引擎源码、解码器和 C++ 字符串语法；直接编码官方 LZ4 文件则约 12,537,998 个字符。
这不是证明所有可能编码都不行，而是说明常规的无损压缩不足以解决该模型的体积限制。剪枝、重新量化或蒸馏训练会改变模型，必须重新训练或评估，不能直接宣称等价。

freestyle NNUE 的 SHA256 为 `6bc0d1b0ff8e1d857f7f412923cd458f38f1a435087c91ae71fec3676c23ef62`，架构校验值 `84e275f6`，规则掩码为 1（freestyle），棋盘大小掩码解码为 13–22。描述字段记录导出时间为 2025-05-24、训练器提交为 `4ff0971`。

## NNUE 参数和内存

`mix9svqnnue.cpp` 使用 FeatureDim=64、PolicyDim=32、ValueDim=64、FeatDWConvDim=32、PolicyPWConvDim=16。

- 码本：`int16_t[2][65536][64]`，8,388,608 个数，RAM 16,777,216 字节；磁盘使用 10-bit 打包，压缩前为 10,485,760 字节。
- 棋形到码本索引：`uint16_t[2][442503]`，885,006 个索引，1,770,012 字节。
- 深度卷积权重和偏置：640 字节；策略/价值 head：152,768 字节。
- 包含对齐填充的一个 Weight 结构体：18,700,672 字节。
- 按 12×12 计算，一个增量累加器各动态数组合计 1,969,028 字节；黑白两个合计 3,938,056 字节。这是架构推导，不表示该官方权重支持 12 路。

以上不包括内存分配器开销、棋盘状态、搜索栈、置换表、缓存和解码临时空间。当前限制的主要障碍是源码体积和官方权重的棋盘兼容性；不能仅由这些数据推断具体机器上的每步性能。

另一个 `mix10` 架构的映射层为 `int16_t[2][442503][64]`，这一层即 113,280,768 字节 RAM。锁定的官方权重仓库没有 mix10 模型，本报告没有对不存在的下载文件作压缩或棋力结论。

## 经典模型如何自包含

生成器直接解析官方 v8 格式，验证 LZ4 帧头和内容的 xxHash32 校验，并检查扩展头和精确尺寸。
仅把官方 LZ4 压缩块编码为 Base85 字符串，附带一个标准 C++ 解码器；初始化时还验证原始模型的 FNV-1a32。
无需 LZ4 库、TOML 库、外部权重文件、文件系统或网络。

所有参数完整保留：

- `EVALS[4][3876]`，四套规则/颜色的棋形估值。
- `EVALS_THREAT[4][2048]`，威胁估值。
- `P4SCORES[4][3876][2]`，进攻/防守走法排序。
- `StoredPolicyCrossTable[4][5][13][13]`，训练后的策略残差；经官方 `installPolicyCross` API 安装并重建激活掩码。
- 官方尺度 `116.37149810791016`。
- 配套 `gomocalc-classical260809.toml` 中四套完整 `value_readout_knots`，经官方 API 安装。

初始化必须在 PatternConfig 初始化之后、创建或重建 Board 之前执行。
该经典模型在官方 README 中声明训练/验证于 freestyle 15/20、standard 15、renju 15；它的查表本身没有 12 路加载限制，但 12 路实战强度仍需要测试。

## 校验与复现

生成与测量脚本：`tools/inspect_rapfi_weights.py`。无第三方 Python 依赖。

```powershell
python tools\inspect_rapfi_weights.py --measure
```

详细数据、所有文件 SHA256、兼容棋盘大小和内存推导位于 `results/rapfi/weights.json`。

1. 内置简易模型的两组 136 项表和 16 项排序表已与官方 TOML 对比；对全部 **3,876** 个方向棋形组合，独立枚举的三角表索引与生成器公式一致，且没有遗漏的截断/缩放差异。
2. `rapfi_port/assets/validate_trained.cpp` 使用 MSVC C++17 `/O2 /W4` 编译并运行，调用生成的 C++ initializer，再把实际数组按官方顺序序列化为 `trained_roundtrip.bin`。
3. 输出的 **116,208 字节逐字节等于官方模型解压数据**，SHA256 完全相同。该检查涵盖全部估值、威胁、排序、策略表和模型尺度。TOML 中 readout knots 单独按原始 double 值生成。
4. 2026-11-08 另用 `validate_integration.cpp` 直接包含最终生成的 `rapfi_trained.cpp`，执行实际 `Brain::reset(1)`、`Brain::reset(2)`，未运行搜索。初始化和重复 START 后，实际全部权重和尺度仍逐字节匹配官方模型；24 个 readout double 精确匹配官方 TOML；四套策略激活掩码均为 31。
5. 实际 freestyle readout 缓存在输入 `[-1000,-200,-50,0,50,100,200,500,1000]` 时输出 `[-926,-265,-67,0,67,132,265,593,926]`，与 Python 独立按官方分段线性公式计算的结果一致。`setScalingFactor` 会在安装 readout 后重建缓存，没有沿用默认尺度 200 的旧缓存。

这验证的是资产无损嵌入和初始化，不替代搜索核心的正确性、时限测试或棋力对战。
