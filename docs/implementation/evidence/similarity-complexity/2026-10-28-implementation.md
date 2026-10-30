# 相似检测与复杂度分析：实现与验证记录

> **历史记录。** 本文记录 2026-10-28 的第一版复杂度实现（墙钟计时 + 静态结构分析），该实现已被[执行轨迹计数与递推推断](../../../design/analysis/complexity-trace.md)取代，其代码与迁移已下线；新版实验见[2026-10-29 轨迹实验记录](2026-10-29-trace-experiments.md)。
日期：2026-10-28，Asia/Shanghai。分支 `feat/similarity-and-complexity`，基线为本地 main `938a8d2`，迁移从 pg0006 前进到 pg0007。

本机环境：macOS 15（Darwin 25.6.0、arm64、10 核）、Python 3.14.5、PostgreSQL 18.6（5432）、Node 25.9.0、pnpm 11.21.0、Chrome（headless 实跑）。

## 1. 新增能力

| 能力 | 位置 |
|---|---|
| 相似算法（词法规格化 + Winnowing） | `backend/app/analysis/algorithms/similarity.py` |
| 相似批次与教师证据投影 | `backend/app/analysis/similarity_service.py` |
| 复杂度静态分析 + 增长拟合 | `backend/app/analysis/algorithms/complexity.py` |
| 伸缩档输入生成与真实测量 | `backend/app/analysis/probe.py` |
| 复杂度请求/worker/投影 | `backend/app/analysis/complexity_service.py`、`scripts/run_complexity.py` |
| 伸缩档种子 | `backend/app/analysis/profiles.py`、`scripts/seed_complexity_profiles.py` |
| 数据库 | `problem_complexity_profiles`、`complexity_reports`，迁移 pg0007 |
| 教师端证据页 | `frontend/src/features/teacher/Similarity.vue` |
| 学生端复杂度面板 | `frontend/src/features/student/components/ComplexityPanel.vue`、`GrowthChart.vue` |

## 2. 自动验证

后端 `python -m pytest -q`：**238 passed**（基线 156，新增 82）。其中：

- `tests/test_similarity_algorithm.py`：62 项，含倒排索引与朴素集合求交的 12 组随机对拍、6 个类别的无噪声还原、降阶规则的残差级验证、log 因子三对的双向合并用例。
- `tests/test_similarity_and_complexity_api.py`：20 项，真实 PostgreSQL + FastAPI TestClient。
- `tests/test_migrations.py` 更新为 pg0007、30 张业务表。

有两处已知的偶发失败：`tests/test_judge_scheduler.py::test_service_pause_keeps_jobs_queued_and_resumes_after_switch` 在完整套件里偶发失败一次（单独运行与随后两次完整运行均通过）。`tests/test_judge_local.py::test_cpp_local_execution` 在完整套件里也偶发失败一次（单独运行与随后两次完整运行均通过）。这两个测试都属评测调度与本地执行，与本轮改动无关，也未修改；记录在此避免把它们误当成稳定现象。

前端：`vitest run` **92 passed**（21 个文件，基线 50，新增 42）；`vue-tsc --noEmit` 通过；`prettier --check` 全库通过；`vite build` 通过。

真实 HTTP：`python scripts/smoke_similarity_complexity_http.py`，**59 项检查通过**。最后一次运行（当前代码）输出摘要：

```
  demo.student01: v3 ACCEPTED (5/5)
  demo.student02: v3 ACCEPTED (5/5)
  demo.student03: v3 ACCEPTED (5/5)
  demo.student04: v3 ACCEPTED (5/5)
  demo.student05: v3 WRONG_ANSWER (0/5)
  demo.student06: v3 WRONG_ANSWER (0/5)
  similarity: 3 pairs, 1 clusters, top=1.000000
  complexity: SUCCEEDED time=O(n) space=O(n) source=STATIC
  unaccepted: refused with SUBMISSION_NOT_ACCEPTED
```

脚本同时断言：学生读取相似证据返回 403；未通过提交请求复杂度返回 409 `SUBMISSION_NOT_ACCEPTED`；重复请求返回同一份报告（`finished_at` 不变，证明没有重跑）。

## 3. 实际浏览器

headless Chrome 1440×1000 实跑：

- 教师登录 → 选课 → 相似检测页 → 开始比对 → 打开一对证据。页面出现“相似簇”“相似对”，列表显示真实姓名与学号，3 个“查看代码”按钮，展开后显示“匹配证据”与两侧代码。
- 学生登录 → 本人提交 → 打开版本详情。复杂度面板显示 `时间 O(n) 置信度 高 依据：实测增长`、`空间 O(n) 依据：代码结构`，SVG 增长曲线 1 个，逐档表格与局限说明齐全。

截图：[相似证据](../screenshots/similarity/01-similarity-evidence.png)、[匹配证据与并排代码](../screenshots/similarity/02-pair-detail.png)、[学生复杂度面板](../screenshots/complexity/01-student-complexity.png)。

浏览器控制台唯一的错误是登录页一个既有静态资源 404，与本轮改动无关。

## 4. 数据库

开发库 `algorithm_review` 升级前先做 `pg_dump -Fc` 备份（工程内 `.backups/`，已加入本机 `git/info/exclude`，不入库）。从 pg0006 升到 pg0007，升级前后计数一致：users 224、problems 124。

验证库 `algorithm_review_test` 覆盖 upgrade → downgrade → upgrade 往返：pg0007（30 张业务表）与 pg0008（三条 CHECK + `history` 列），`compare_metadata` 差异为空。开发库已升到 pg0008，存量报告全部满足新约束。

## 5. 方案审核：质疑设计本身

第二轮由 Lead 组织两轮方案审核（不是找实现 bug，而是质疑方案与参数选择），四个只读智能体并行：相似检测方案、复杂度分析方案、多轮校验、学生端前端优化。方案审核的结论是：**两个功能的算法骨架站得住，但各有必须改的设计缺陷。**

### 5.1 相似检测：证据强度依赖程序长度（Lead 独立发现，P1）

实测独立完成基线（同一贪心、三人各自独立写作）：
- I/O 习惯各异（82–126 记号）：0.354839 / 0.193548 / 0.031250，全部低于阈值；
- **全班统一 I/O 惯用法（109 记号）：1.000000 / 0.583333 / 0.583333，三对全部达到或超过 0.5**；
- 长题目同一算法独立实现（202–219 记号）：0.311688。

结论：短题目里题目本身决定了大部分记号序列，独立完成也能到 1.0。教师看到"相似度 1.000000"可能是两个诚实学生的必然重合。据此：

| 改动 | 位置 |
|---|---|
| 配对返回双方记号数 | `similarity.py`（`left_tokens`/`right_tokens`）+ 契约 + 投影 |
| 任一侧 < 120 记号标注"程序较短，独立完成也可能达到此相似度" | 教师页配对表 |
| [0.5, 0.7) 标注"该区间内同题的不同正确算法也可能出现" | 教师页配对表 |
| 独立完成基线做成可复现实验 | `experiment_honest_baseline`，报告 §4.3 |

### 5.2 相似检测：簇是连通分量，不是团（方案审核 P1）

实测 8 人簇的 28 条两两组合里只有 8 条真正过阈值，页面却只显示"8 份 · 最高 0.671"。构造验证（A 含块 1、B 含块 1+2、C 含块 2）得到 3 人簇、达标 2/3 对。改动：簇返回 `qualifying_pairs`/`total_pairs`/`min_similarity`，教师页展示"达标 X/Y · 最低相似度"，非完全图打"链式"标记。

### 5.3 相似检测：其他方案结论

- k=12/w=4 经六组参数网格对照，k=8 更抗插入但底噪升高（跨题 ≥0.5 从 18 对升到 28 对），k=16 底噪最低但抗插入更差，k=12 是折中点，不改。
- `max(双向包含度)` 正确：整段抄进大作业实测 1.000000，用 Jaccard 会压到 0.46 造成漏报。
- 阈值 0.5 数据上不存在干净分隔（同题不同算法最高 0.689、轻改写中位 0.742），不改默认值，改为在界面上标注区间含义。
- 跨语言不可比：批次返回 `language_counts`，混语言时页面提示。

### 5.4 复杂度分析："实测只能给上界"的判据从未生效（方案审核 P1）

判据原写成"先给基线自己拟曲线、再比类别"。基线是常数开销程序，它的拟合几乎必然 LOW，于是 `io_class` 永远 `UNKNOWN`、`informative` 永远 `True`——判据空转，实测只要置信度够就直接定案。核对实验 JSON 六组加自测四组：`io_class` 100% `UNKNOWN`、`reference_fit` 100% `None`。

改为逐档比值：完成档里至少 3 档 `wall_ms / reference_ms ≥ 1.5` 才算有信息；没有基线时（C/C++/Java）不判否，报告写明"实测未经输入开销校验"。改完后判据第一次真正生效，线性组与常数组立刻被正确判为信息不足、回落结构分析。

### 5.5 复杂度分析：三分之一题目的伸缩档与真实输入不匹配（方案审核 P1）

63 道可测题逐一生成 `n=256` 输入喂题库参考解：21 道直接崩溃。原因是 11 个族覆盖不了题库真实格式（背包首行 `n W`、无权图二元边、三整数、数字串）。

修复两层：族参数化（`edge_arity`、`header_extra`）修好 6 道；**种子自动验收**——生成输入喂参考解，崩溃则降级为 `EXISTING_CASES` 并记录原因，已入库的用 `--revalidate` 重验。当前 70 道题：40 道可测（全部通过验收）、31 道仅结构分析。代价是三成题目拿不到实测结论，这是已接受的取舍。

### 5.6 复杂度分析：其他方案结论与改动

| 结论 | 改动 |
|---|---|
| 实测这条腿值得保留（开发库 4/6 报告由 DYNAMIC 定案；c-like 只有词法分析，砍掉实测后无结论） | 保留，但预算从 150s 降到 60s（所有成功组 <12s） |
| log 因子由结构裁定对 c-like 有漏洞（词法 LOW 也参与裁定） | 结构置信度为 LOW 时不裁定，按实测报并写明 |
| 教师逐个 POST 300 次不可用（主用例是 60 人 × 5 题） | 新增 `POST /complexity/batch` + 教师页排队按钮 |
| 冗余列缺枚举约束、status 与类别无一致性约束、版本重置丢历史 | pg0008：三条 CHECK + `history` JSONB 归档旧结论 |

### 5.7 学生端前端优化（额外任务）

由独立智能体走完整学生旅程（390/1440 两宽度，含一次真实提交）后修 7 个真实问题：

| 问题 | 修法 |
|---|---|
| 提交详情把内部枚举「任务 PENDING」直接上界面 | 中文状态映射 |
| 全站日期是美式 `toLocaleString`（中文界面易读反月/日） | 新增 `format.ts`，统一 `2026-10-28 15:04` |
| 评测空态徽标显示「未标注」 | 改「等待评测」 |
| 题面「版本 v1」与提交版本混淆 | 改「题面版本」 |
| 剩余不足 1 小时显示「剩余约 0 小时」 | `remainingLabel` 覆盖 <1 小时边界，与作业详情句式一致 |
| 草稿「尚未开始作答」与「已恢复第 N 版」同屏矛盾 | 改「没有未保存的修改」 |
| 「恢复周期」空值渲染成 0 | 显示「—」 |

## 5.8 方案修正的自验记录

原计划由两个复核智能体分别验证各自领域的修复，但两者都在长任务中中断（本会话长期智能体的已知问题）。改由 Lead 逐项实测，结果如下。

| 验证项 | 方法 | 结果 |
|---|---|---|
| informative 四条边界 | 构造测量数据 | 无基线→True、三档≥1.5→True、仅两档→False、全贴基线→False |
| 六组自洽性 | 用 rungs 的 io_ratio 重算 | 6/6 与 `informative` 一致（O1 0 档、On 0 档、Onlog 3 档、On2 4 档、On3 2 档） |
| **新误判方向**（最担心的） | 真实 probe 跑一个常数极小的 O(n²) 程序 | 逐档 ratio 1.0/1.21/1.17/1.85/3.81 → 仅 2 档达标 → informative=False → 回落静态 O(n²)，**结论正确** |
| pg0008 CHECK 真的生效 | 直接 INSERT 非法类别 / 已发布空类别 / 排队带类别 | 三种全部被拒绝，合法行通过 |
| **约束抓到我自己的 bug** | 跑 history 归档测试 | 版本重置把 status 改回 PENDING 却没清空旧类别 → 违反 `ck_cr_status_class`。已修（同时清空类别/置信度/来源） |
| 批量并发 | 连续两次 POST | 第二次跳过已有报告，`submission_id` 唯一约束下无重复行、无 500 |
| history 归档 | 模拟实现版本升级 | 旧结论进 `history[-1].time_class`，行回到 PENDING |
| 旧批次兼容 | 真实浏览器开 batch 7（无新字段） | 正常渲染，缺值显示 "—"，无 NaN/undefined |
| 新标注 | 真实浏览器开 batch 22 | 弱证据标注出现、记号数可见 |
| 学生端 7 项修复 | 真实浏览器 390/1440 | 中文日期、无美式日期、无裸枚举、无 undefined、复杂度面板仍在、无 pageerror |

约束抓到实现 bug 这件事本身说明"把规则写成数据库约束"比"写在文档里"有效：这类不一致靠人眼审是看不出来的。

**关于独立复核的如实说明。** 本轮共派出四次独立复核（两个按领域拆分的完整复核、两个单一问题的微复核），全部在运行中中断——本会话的长期智能体在长任务上不稳定，前几轮也出现过同样问题。因此上述验证由 Lead 手工完成并记录数字。为降低"用自己的构造自证"的偏差，两个最关键的结论都用了**两套互不相同的代码**复现：

- informative 新规则：第一套是我手写的步长 64 双重循环，第二套是实验脚本里另外两组的真实测量，方向一致；
- 独立完成基线：第一套是我手写的三份贪心，第二套是实验脚本 `experiment_honest_baseline` 里的三份不同代码，三对全部 ≥0.5 的结果在第二套上复现。

这是本报告在流程上的真实缺口：复核结论来自实现者本人而非独立第三方。它不改变数字，但读者应当知道这一点。

## 6. 独立审核发现并修好的问题

两个只读审核（一个审后端与算法，一个审前端）在交付前各给出一份不通过结论。修完复核项如下。审核的原始结论不在仓库里，这里只记录被采纳的问题与修复。

**算法与后端**

| 问题 | 后果 | 修复 |
|---|---|---|
| `_CostStack.pop` 没跟上 `push` 新增的 `const` 权重 | `for i in range(n)` 里先出现 `for b in range(8)` 再出现内层 n 循环时，外层代价被抹掉，`O(n^2)` 报成 `O(n)`；题库 CODE-P37 受影响 | `pop` 与 `push` 用同一套判断，`const` 直接返回；三种排列顺序加单测 |
| 档位停止条件（4）与拟合发布门槛（5）各写各的 | 平方及更高阶程序永远拿不到 5 档，实测永久失效 | 抽出 `MINIMUM_PUBLISHABLE_RUNGS`，`probe` 直接引用 |
| `exp(2/m)` 被写成 AIC 推导 | 八类候选参数个数相同，推导不成立 | 改注为经验性保守折减系数，文档同步 |
| 降阶可一次跨多个等级 | 可能从 `O(n^2)` 直接跳到 `O(1)` | 只允许在“实际并列的候选”里逐级下降，加两个单测 |
| `classify_growth` 只把 OK 档传给拟合 | “剔除 N 档”永远不出现 | 传全部测量，`fit_growth` 自己筛并记录 |
| 内存判定用总 RSS 除以 n | 解释器底噪占大头，`O(n)` 空间永远测不出 | 改为对“超出最小档的增量”做双对数斜率 |
| C 类词法先删块注释再删字符串 | 字符串里的 `"/*"` 会吞掉后续代码，加两句 print 即可规避检测 | 改成单遍扫描，同时保留换行修正行号 |
| `_merge_spans` 无下界 | 移动代码块时行号区间可向后跳跃，报出的范围与实际匹配不符 | 两侧都加 `-k` 下界 |
| `pairs_truncated` 挂属性不传字段 | 教师无法知道证据列表被截断 | 成为正式字段，贯穿契约、baseline、接口与页面 |

**前端**

| 问题 | 后果 | 修复 |
|---|---|---|
| 相似检测在 90 秒轮询窗口后无条件写“完成” | 批次仍在跑时教师读到“完成：没有达到阈值的相似对” | 按最后一次批次状态判断，未完成时只说仍在进行且不拉证据 |
| 相似检测轮询不检查组件卸载 | 切走后仍持续请求，实测 30 秒 25 次 | 加 `unmounted` 标记，每次 await 后返回 |
| 学生端复杂度面板无轮询上限且卸载后继续请求 | 10 分钟 401 次请求 | 上限 45 次并提示已停止自动刷新；序号令牌丢弃迟到响应 |
| 提交历史把 INELIGIBLE 渲染成“时间 undefined” | 页面上出现 undefined | 按响应 status 分支，缺类别时显示“无法分析/仅结构分析” |
| 面板头部徽章对 FAILED/INELIGIBLE 显示“已完成” | 同一屏同时出现“已完成”和“分析失败” | 五种终态各有文案，与教师端一致 |
| 教师概览轮询出错后文案仍说“页面会自动刷新” | 文案与行为相反 | 错误也计入“已停止自动刷新” |
| 教师概览每轮为每个失败行重新拉原因 | 1 行 PENDING + 9 行 FAILED 时每 5 秒 10 个请求 | 按 submission_id 缓存原因 |
| 教师概览卸载后仍继续轮询 | 中途切页 120 秒内又发 24 次请求 | 加卸载标记与令牌失效 |
| `business_status` 声明了但没人读 | 运行成功、业务无数据时照常画出证据表格 | 增加 `businessWarning`，无可用数据时只显示提示 |
| 截断提示写进 `else-if` | 提示出现时整张表格被隐藏，教师看不到任何一对 | 提示放到表格上方，表格照常渲染 |
| 正在计算的批次被说成“没有可用结果” | `RUNNING`/`READY` 的任务显示成失败 | 按状态分两句：“仍在计算”与“没有可用结果” |
| `.code-compare` 子项缺 `min-width: 0` | 390 宽点开代码对比横向溢出 205px | 改用 `minmax(0, 1fr)` 并给子项 `min-width: 0` |
| `GrowthChart` 未过滤非有限值 | NaN/Infinity 会写出非法 SVG 坐标 | 只画有限正数；刻度按像素距离去重叠 |
| 三个 select 无 `aria-label`、操作列表头为空 | 屏幕阅读器读不出控件名 | 补 `aria-label`；表头改用 `th aria-label`（`visually-hidden` 是绝对定位元素，会把 390 宽页面撑到 505） |
| 两处测试断言过宽（`toBeTruthy`、`toContain("过短")`） | 文案退化仍通过 | 改为精确字符串并断言键值一一对应 |

## 7. 实验暴露并修好的缺陷

`backend/scripts/experiment_similarity_complexity.py` 用本实现自带的函数跑了 6 组复杂度对照，发现两个真实缺陷：

| 缺陷 | 暴露它的实验 | 数字 | 修复 |
|---|---|---|---|
| 无噪声的 `O(n log n)` 曲线被判成 `O(n)` | fit 标定：把理想曲线喂给同一个 `fit_growth` | 5 次重复全部错 | 按残差平方和选类，降阶需通过 `exp(2/m)` 的 AIC 门槛 |
| 实测无法分辨只差一个 log 因子的两类 | 同一组数据的带噪声重复（σ=2%/5%/10%） | 40 次里 13 次分错 | 这一类改由结构分析裁定，实测分歧写进限制 |

另外两条规则从同一批数字推出：有效档位少于 5 不给 MEDIUM 以上置信度（4 档时 `O(n²)` 被判成 `O(n log n)`）；字面量边界的循环不再贡献多项式因子（`for _ in range(60000)` 是常数，旧实现把整个程序算成 `O(n log n)`）。

修复后同一套实验 6/6 组一致。这不是"现在全对了"：噪声下 log 因子仍然不稳定，报告里的结论仍需配合置信度与限制说明读。完整数字见 [experiments-2026-10-28.json](experiments-2026-10-28.json)，分析见[算法实验](../../../design/analysis/algorithm-experiments.md)。

## 8. 一处需要说明的测量结论

最初的设计假设“实测增长总能给出复杂度”，实测发现不成立：程序读输入本身是 O(n)，二分查找的实测总时间和纯读取同阶，无法区分 O(log n) 与 O(n)。因此增加了纯输入读取基线，并把规则改为“实测必须明显超过读取成本才作为依据”，否则回落到结构分析并在报告里写明只能给出上界。这条规则在 `test_combine_does_not_claim_a_class_the_measurement_cannot_separate` 和真实冒烟中都被固定下来。

## 9. 未做与边界

- 没有 Linux 沙箱：测量与评测一样在服务主机执行，只适合受控开发环境。
- C/C++/Java 只做词法结构分析，置信度固定 LOW。
- 题库里 70 道编程题的伸缩档按输入格式人工归类；写错的族会生成不合法输入，此时程序多半运行错误，报告会显示失败档位而不是伪造曲线。
- 相似检测不判断抄袭，不生成处置动作；教师决定怎么处理。
- 前端没有引入图表库，曲线是自绘 SVG。
