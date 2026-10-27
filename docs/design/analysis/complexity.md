# 已通过代码的复杂度分析（已实现）

日期：2026-10-28。实现位于 `backend/app/analysis/algorithms/complexity.py`（纯函数）、`probe.py`（输入生成与测量）、`complexity_service.py`（状态机与投影）、`scripts/run_complexity.py`（worker）与前端 `ComplexityPanel.vue`、`GrowthChart.vue`。

## 1. 它回答什么

一段**真实通过**的代码，运行时间随输入规模怎么长、空间怎么长。给学生的是一张增长曲线、一个复杂度类别、置信度和逐条结构证据；它不参与评分。

资格条件全部满足才分析：`ACCEPTED`、`is_mock=false`、通过点数等于总数、当前执行环境内、语言受支持。任何一条不满足就返回 409 并说明原因，不编造报告。

## 2. 两个独立估计器

### 2.1 静态结构分析

Python 用标准库 `ast`，C/C++/Java 只用词法与括号结构。

Python 收集的事实：

| 事实 | 用途 |
|---|---|
| 循环嵌套，按（多项式层数, 对数层数）记录 | `while lo<hi: mid=(lo+hi)//2` 记对数层；`for` 记多项式层 |
| 折半收缩（`//2`、`>>1`、`a[mid:]`） | 分治、二分、快速幂 |
| 递归形态（折半 / 递减 / 常数参数）与递归调用数 | 单路折半 → log n；双路折半 → 分治；双路常数 → 2^n；单路递减含循环 → n² |
| 排序调用 | 引入 log n 因子 |
| 容器分配（推导式、`list(...)`、`[[0]*n]`） | 空间下界；二维表 → O(n²) |
| 递归深度 | 调用栈空间 |

结论是类别 + 证据列表（行号 + 原因）。C/C++/Java 固定 `confidence=LOW`，证据里带 `LEXICAL_ONLY`，报告写明没有语法树。

### 2.2 经验增长测量

平台无法为任意题目自动造数据，因此每题有一份**伸缩档**（`problem_complexity_profiles`）：声明输入形态族与规模上限。11 个族覆盖单整数、两个整数、整数数组、成对行、图边、两串、单串、网格、矩阵、固定输入、不可测量。

测量流程：

1. 编译一次，然后按倍增序列（256、512 … 至多 13 档）逐档运行。
2. 每档跑 3 次取中位数；单档墙钟上限 10 秒，总预算 150 秒。
3. 同一档额外跑一个**纯输入读取程序**（只读、切分、转换、打印），作为该档输入解析成本。
4. 停止条件：最大档超过 250 ms、或倍数已达 8 倍且至少 4 档有效、或超时、或触顶。停止原因写进报告。
5. 每档用 `os.wait4` 取得该子进程自己的 `ru_maxrss`（不是全进程累计最大值），换算为 KiB。

执行复用 `app/judge/local.py` 的启动门、进程组终止与输出上限，不另写执行器；测量在 `scripts/run_complexity.py` 独立进程中做，不占评测队列。

### 2.3 拟合

对每个候选类别 `f(n) ∈ {1, log n, n, n log n, n², n² log n, n³, 2ⁿ}` 拟合 `t = a·f(n) + b`，`a>0`、`b≥0`：

- `b` 必须允许为正：进程启动、解释器预热是每档都有的常数，忽略它会系统性低估增长。
- R² 选类别；相差 0.005 以内取更低阶。
- 另算双对数斜率作为物理校验，与类别预期指数相差超过 0.7 的候选被排除。

### 2.4 合并规则

1. 实测类别 **高于**纯读取类别（说明程序确实比读输入慢了），且置信度不是 LOW → 时间结论取实测。
2. 否则以结构分析为准。原因写清楚：实测总时间与纯读取同阶，只能给出上界，分不出更便宜的算法（二分查找就是这种情况）。
3. 两者不一致时两条都保留，并写“以实测为准，但两者不一致说明结论只能作为参考”。
4. 空间以结构分析为主；实测内存确实随规模增长且更高时才上调，并注明。

## 3. 复杂度

生成 O(n) 输入、执行 O(T(n))、拟合 O(档位数 × 候选数) = O(13×8)，可忽略。测量本身受单档 10 秒、总 150 秒硬上限约束。

## 4. 数据

迁移 pg0007 新增两张表：

- `problem_complexity_profiles`：`problem_version_id` 唯一、`family`、`spec`（JSONB）、`source`、`version_no`。用 `python -m scripts.seed_complexity_profiles` 按题目编号写入，幂等，不覆盖已有行。
- `complexity_reports`：一次提交一份，`status`、`time_class`/`space_class`、置信度、来源、`static_analysis`、`growth`、`summary`、`limitations`，加 `requested_by`、`attempt_no`、`lease_expires_at`、`finished_at`、`error_message`。

worker 用 `FOR UPDATE SKIP LOCKED` 领取，置 RUNNING 并给 180 秒租约，测量在事务外进行，写回前重验租约。租约过期由 `recover_expired` 置 FAILED 并说明，不自动重跑。

## 5. 接口

| 方法 / 路径 | 说明 |
|---|---|
| `POST /analysis/submissions/{id}/complexity` | 学生本人或本课程教师；202；已有报告时直接返回，不重跑 |
| `GET /analysis/submissions/{id}/complexity` | 学生本人或本课程教师；返回报告或 `status=NONE` |
| `GET /analysis/courses/{course_id}/complexity` | 仅教师；班级概览，每生每题最新一份 |
| `GET /analysis/courses/{course_id}/complexity/items` | 仅教师；哪些题配置了伸缩档 |

## 6. 已声明的限制

报告里必须出现、前端必须显示：

- 输入由平台按伸缩档合成，覆盖常见规模，不代表最坏情况或全部合法输入。
- 静态分析依据代码结构，等价改写可能改变结论。
- 结构化语言没有语法树，结论是词法上界。
- 总时间与纯读取同阶时，实测只能给出上界（会明确写）。
- 超时或失败的档位被剔除，并写剔除了几档。
- 有效档位少于 4 时，拟合容易受常数开销影响。
- 复杂度分析不参与评分，不改变评测结果。

## 7. 边界

- 只分析已真实通过的提交；未通过、模拟结果、跨执行环境的结果一律拒绝并给出 409 原因。
- 没有伸缩档的题只出结构结论（`STATIC_ONLY`），不假装测量过。
- 输出规模本身就很大的题（汉诺塔、全排列、数独、格雷码等）标记为不可测量，避免测到输出格式化而不是算法。
- 同报告不随刷新重新随机：一切来自已保存的 JSONB。

## 8. 验证

- `backend/tests/test_similarity_algorithm.py`：6 种参考形态静态分类正确（归并 n log n、冒泡 n²、二分 log n、汉诺塔 2ⁿ、线性 n、常数 1）；空间识别容器与二维表；结构化语言标 LOW 且带 LEXICAL_ONLY；不支持语言返回 UNKNOWN；5 组合成数据拟合出正确类别；点数不足返回 UNKNOWN+LOW；失败档位被剔除；合并规则三条分支各有用例。
- `backend/tests/test_similarity_and_complexity_api.py`：资格 5 类拒绝、教师可请求而他人 404、无档案 STATIC_ONLY、真实测量出 rungs/纯读取/曲线、幂等、班级概览、教师专用、种子幂等。
- 真实 HTTP 冒烟：`scripts/smoke_similarity_complexity_http.py`，真实提交、真实评测、真实测量，得到 `SUCCEEDED` 报告与曲线。
