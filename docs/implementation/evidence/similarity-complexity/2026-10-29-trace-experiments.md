# 2026-10-29 执行轨迹复杂度实验：准确率、跨语言一致性与可重复性

日期：2026-10-29。被测实现是当前提交里的执行轨迹路线：`backend/app/analysis/probe.py`（输入合成）、`backend/app/analysis/trace/`（采集、闭式拟合、递推推断）、`backend/app/analysis/trace/adapters/`（Python 与 C/C++ 采集器）。复现脚本是 `backend/scripts/experiment_complexity_trace.py`，原始数据是两份 JSON：

- [2026-10-29-trace-experiments.json](2026-10-29-trace-experiments.json)：70 道题的 Python 参考解，语言 Python 3
- [2026-10-29-trace-experiments-cpp.json](2026-10-29-trace-experiments-cpp.json)：同一批题的 C++ 参考解，语言 C++17

标注表是 [data/analysis/complexity_expected_classes.json](../../../data/analysis/complexity_expected_classes.json)，逐题读过参考解后标注，每题带一句 rationale。

## 0. 怎么跑

```bash
cd backend
../.venv/bin/python -m scripts.experiment_complexity_trace --language python
../.venv/bin/python -m scripts.experiment_complexity_trace --language cpp \
  --output ../docs/implementation/evidence/similarity-complexity/2026-10-29-trace-experiments-cpp.json
../.venv/bin/python -m scripts.validate_complexity_profiles
```

脚本不连数据库、不联网；输入只有题库的参考解和 `profiles.PROFILES`。固定种子 `20261028`，每个程序跑两遍用于可重复性对比；单题预算 30 秒。本次运行：Python 3.14.5，macOS-26.6.2-arm64。Python 一轮 371 秒（70 题 × 2 遍），C++ 一轮 314 秒。

## 1. 覆盖：68/69 道题有可伸缩输入

`validate_complexity_profiles` 用题库参考解和真实采集器验收每个输入形态族：

| 项 | 数量 |
|---|---:|
| 题库编程题 | 70 |
| 固定输入、不可伸缩（CODE-P37 数独） | 1 |
| 参与验收 | 69 |
| 通过验收 | **68** |
| 失败 | 1（CODE-P02 找零钱） |

CODE-P02 的参考解对 N 只做 7 次整除，档位从 64 拉到 1,048,576 时工作量只从 41 变到 46（比值 1.12）。它在输入可伸缩但算法是 O(1)，验收判据（工作量增长 ≥1.5 倍）按设计拒绝它，seeding 会把它降级为 `EXISTING_CASES` 并记录原因。上一版的可测数量是 40/70。

## 2. Python 参考解：65 道有标注的题里判对 58 道（89.2%）

| 项 | 数值 |
|---|---:|
| 有期望类别的题（分母） | 65 |
| 判对 | **58（89.2%）** |
| 判成 UNKNOWN | 3 |
| 判错类别 | 8 |
| 执行失败 / 超时 | 0 |
| 不可测（固定输入） | 1 |

分类型：

| 期望类别 | 判对 / 总数 | 实际判成 |
|---|---:|---|
| O(1) | 1 / 1 | O(1) 1 |
| O(log n) | 3 / 4 | O(log n) 3，UNKNOWN 1 |
| O(n) | 22 / 25 | O(n) 22，UNKNOWN 1，O(n log n) 2 |
| O(n log n) | **18 / 19** | O(n log n) 18，UNKNOWN 1 |
| O(n²) | 7 / 9 | O(n²) 7，O(n) 1，O(n log n) 1 |
| O(n³) | 3 / 3 | 全对 |
| O(2ⁿ) | 2 / 2 | 全对 |
| O(n!) | 2 / 2 | 全对 |

上一版的失效模式在这里的结果：**n 与 n log n 的 19 道题里 18 道判对**（唯一例外是 Dijkstra 在生成图上提前退出，判成 UNKNOWN），n² 与 n² log n 没有互相混淆，2ⁿ 与 n! 全对。旧版实验里 40 次带噪声对照有 13 次在 n/n log n 上分错。

12 道没有判对的题，按原因归类：

**A. 输入数值决定执行路径（3 道，判 UNKNOWN，报告里写明原因）**
- CODE-P08 跳跃游戏：不同输入值让循环提前结束，工作量在档位之间上下跳。
- CODE-P26 单源最短路：Dijkstra 在生成图上找到目标就停，总工作量依赖图的结构。
- CODE-P58 扩展欧几里得：步数随具体数值波动，档位之间的计数没有稳定增长趋势。

**B. 真实增长不在类别目录里（4 道，标注就是 UNKNOWN）**
- CODE-P15 大整数乘法：乘法的 Karatsuba 增长 n^1.585 在解释器内部，被判 O(1)。
- CODE-P39 括号生成：Catalan 增长约 4ⁿ/n^1.5，被判 O(2ⁿ)。
- CODE-P57 统计素数个数：n log log n，被判 O(n)。
- CODE-P62 质因数分解：√n，被判 O(log n)。

这四道题被判的类别是"目录里最接近的一项"，报告的限制说明会写明真实的增长形态。实验把它们的期望标成 UNKNOWN，所以计入错误；这反映的是词汇表缺口，不是采集或拟合出错。

**C. 标注本身有争议（5 道）**
- CODE-P24 最长公共子串：标注 O(n)，参考解是二维 DP，实测增长接近 n²。
- CODE-P40 单词搜索：标注 O(n²)，回溯路径数在生成网格上更接近指数或 n² log n。
- CODE-P46 最长公共前缀：标注 O(n)，逐串比较的代价与串长有关。
- CODE-P64 二进制中 1 的个数：标注 O(n)，每个数按位处理时是 n log n 量级。
- CODE-P48 第 k 小：标注 O(n)，参考解是随机化 quickselect，实测与运行都带随机性。

**D. 平均情况与最坏情况的差别（1 道）**
- CODE-P27 负权环判定：Bellman-Ford 最坏 n²，但在没有负环的随机图上提前退出，实测线性。报告按实测报 O(n)。

## 3. C++ 参考解：65 道里判对 54 道（83.1%）

| 项 | 数值 |
|---|---:|
| 有期望类别的题 | 65 |
| 判对 | **54（83.1%）** |
| 判成 UNKNOWN | 1 |
| 判错类别 | 14 |
| 执行失败 / 超时 | 0 |

分类型：

| 期望类别 | 判对 / 总数 | 实际判成 |
|---|---:|---|
| O(1) | 1 / 1 | O(1) 1 |
| O(log n) | 3 / 4 | O(log n) 3，UNKNOWN 1 |
| O(n) | 19 / 25 | O(n) 19，O(n²) 3，O(n log n) 2，O(1) 1 |
| O(n log n) | **17 / 19** | O(n log n) 17，O(n²) 1，O(n² log n) 1 |
| O(n²) | 7 / 9 | O(n²) 7，O(n) 1，O(n² log n) 1 |
| O(n³) | 3 / 3 | 全对 |
| O(2ⁿ) | 2 / 2 | 全对 |
| O(n!) | 2 / 2 | 全对 |

C++ 比 Python 低 6 个百分点，原因在采集器而不在推断：

- 编译器插桩只能数到"我们这轮编译出来的代码行"。Apple libc++ 把基础类型的 `std::sort`/`stable_sort` 等实现放在预编译库里，轨迹看不到内部，适配器只能按调用次数与档位规模折算 `n log n`。折算的调用在执行路径里成立时类别正确；如果程序把所有工作交给库、可观测部分只剩读入和容器的逐元素开销，实测曲线会偏向线性或更高的容器开销（CODE-P06、CODE-P13、CODE-P56 这类把排序和扫描混在容器操作里的程序因此偏高）。
- C 语言没有 `operator new` 记账，空间类别不采集；C++ 里只用 `malloc` 的程序也不采集峰值分配。
- 输入解析基准用的是数字读法：非数字输入时基准立刻失败，等于不扣读入开销。

## 4. 跨语言一致性：69 道可测题里 60 道（87.0%）两种语言给出同一类别

同一份题面、同一套输入形态，Python 与 C++ 参考解判出的类别一致的有 60/69。9 道不一致的题集中在两类：数据依赖/提前退出（P08、P26、P48、P63）、以及 C++ 采集器对容器与库调用的可见性差异（P06、P15、P24、P40、P46）。这个数字衡量的是"轨迹路线是否真的与语言无关"：分类逻辑一致，差异来自各语言能观测到的工作不同；报告里每种语言都会写明自己的采集方式和限制。

## 5. 可重复性：69 道题里 67 道两次运行逐档计数完全相同

每道题跑两遍，比较每一档的 `work`（精确整数）。67/69 完全相等，2 道不一致：

- CODE-P47 快速排序、CODE-P48 第 k 小：参考解使用随机化枢轴/随机选择，两次运行的执行路径本来就不同。

这不是测量噪声，而是程序本身的非确定性；报告的 `deterministic` 字段会标出来，并写进限制说明。确定性程序（含全部 C++ 程序）的计数逐位相同，这是计数路线与旧版墙钟路线最直接的差别。

## 6. 代价

| 语言 | 单题采集+推断中位数 | 最慢 | 70 题整轮（每題 2 遍） |
|---|---:|---:|---:|
| Python | 3.5 s | 18.5 s | 371 s |
| C++ | 4.5 s | 6.0 s | 314 s |

预算：Python 累计约 200 万事件、内存峰值只在 n≤2048 的档位采；C/C++ 累计约 800 万插桩行、单档 10 秒；每份报告总预算 60 秒。实测最慢的 Python 报告（最近点对，9 档 × 3 次子进程）18.5 秒，仍在预算内。

## 7. 这个实验测不到什么

- **只有题库参考解，没有学生代码。** 参考解写得整齐、变量少；学生代码更长，库调用与输入解析方式更多样，误差形态可能不同。这与旧版实验的局限相同。
- **每题只用一个输入形态族。** 报告描述的是"在这类输入上的增长"，不是最坏情况；CODE-P27 这类提前退出的题因此与最坏情况标注不一致。
- **标注是作者按参考解与题面手写的。** 第 2 节 C 类列了 5 道有明显争议的题；准确率的分子对标注质量敏感。
- **CodeComplex 不可用。** 这台机器没有外网（HuggingFace 与 GitHub 均不可达），无法下载 4900+4900 份的外部基准；脚本预留了数据入口，有网络时可以补外部语料对照。
- **C++ 的库调用折算是理论代价。** 它假设排序目标的大小约等于本题输入规模；标准库实现不可见这一点无法在单机上彻底消除。

## 8. 与上一版实验的关系

上一版（[algorithm-experiments.md](../../../design/analysis/algorithm-experiments.md) 第 7、8 节）的结论是：6 组对照里只有 2 组由实测定案，n 与 n log n 在噪声下 40 次里错 13 次，程序跑不赢读输入就只能给上界。本实验在同一批题库上给出的是：89.2%（Python）与 83.1%（C++）的逐题类别准确率、0 次执行失败、67/69 的可重复性，n log n 与 n 在 Python 上不再混淆。旧版的 6 组对照仍可作为上一版方法的档案引用，两套数字不要混算。

## 9. 数据字典

两份 JSON 的顶层键一致：

| 键 | 内容 |
|---|---|
| `meta` | 时间、Python 版本、平台、语言、seed、repeat、预算、题数、标注文件 |
| `labels` | 逐题期望类别、置信度、rationale |
| `results` | 逐题：family、expected、predicted、confidence、method、recurrence、points（n/work/baseline_work/peak_bytes）、rungs、stop_reason、deterministic、elapsed_seconds、verdict |
| `summary` | 准确率、混淆表、分类型统计、重复性、代价、失败清单与原因分类 |

冒烟与前端展示读取的是同一份 `report` 结构：`time`（类别/置信度/方法/闭式/递推）、`space`、`trace`（逐档计数与证据）、`limitations`。
