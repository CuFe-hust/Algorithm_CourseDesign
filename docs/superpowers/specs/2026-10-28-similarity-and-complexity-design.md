# 同题代码相似检测与已通过代码复杂度分析

日期：2026-10-28。状态：本轮实现设计，尚未完成代码。分支 `feat/similarity-and-complexity`，迁移接在 pg0006 之后（pg0007）。

本文回答两件事：

1. 同一个作业里，如何找出学生提交之间的相似代码，并把证据交给教师。
2. 学生已经真实通过的代码，如何分析其时间、空间复杂度，并画给学生看。

两件事都遵守仓库既有边界：分析算法是不依赖 Web 与数据库的纯函数；浏览器不提供身份、分数或算法结论；LOCAL 执行没有沙箱，只用于受控开发环境；模拟结果必须显式标记，不能冒充真实测量。

## 1. 范围与不做

做：

- 教师按作业（可下钻到某道编程题）创建相似检测批次，查看两两相似度、匹配代码段和相似簇。
- 仅比较同一道题内部的学生提交。跨题比较没有意义，直接禁止。
- 每个学生的比较对象是：截止前、未撤回、最后一次有效提交。
- 已通过（`ACCEPTED`、`is_mock=false`、通过点数等于总点数、当前执行上下文内）的提交可以生成一份复杂度报告。
- 复杂度报告含：静态结构分析、经验增长测量、拟合出的时间/空间复杂度类别、置信度、局限。
- 学生端把报告的测量点、拟合曲线、复杂度结论画出来。

不做：

- 不做跨作业、跨课程、跨题目的相似比较。
- 不把相似度当成抄袭结论。相似度只是证据，判断与处置由教师完成。
- 不把复杂度估计当成形式化证明。报告必须写清是静态推断还是实测拟合。
- 不为 C/C++/Java 编写完整 AST 分析；这两种结构语言只用词法与括号结构做低置信度静态估计，并在报告中写明。
- 不在本轮引入 Linux 沙箱；测量复用 LOCAL 执行门。

## 2. 相似代码检测

### 2.1 产品规则

| 规则 | 说明 |
|---|---|
| 比较范围 | 同一 `assignment_item_id` 内的提交 |
| 选取版本 | 每位学生该题截止前、未撤回的最后一次提交 |
| 最少规模 | 代码词法记号少于 40 个的提交不参与配对，标记 `INSUFFICIENT_TOKENS` |
| 结果形态 | 两两配对（含相似度与匹配片段）+ 相似簇（连通分量） |
| 默认阈值 | 相似度 ≥ 0.50 才进入证据列表；簇要求成员数 ≥ 3 |
| 命名 | 接口只用 `student_key`（`student-<id>`）；教师投影时才补学号与姓名 |
| 学生可见性 | 学生不能读取任何相似检测批次或结果 |

### 2.2 算法：词法规格化 + Winnowing 指纹

思想来自 Schleimer、Wilkerson、Aiken 的 Winnowing（MOSS 使用的方法，2003）。核心是：把代码化成一条规范化记号流，对长度 k 的连续记号串（k-gram）取哈希，再用滑动窗口保留每窗最小值作为指纹；两份代码共享的指纹比例就是相似度。

处理步骤：

1. 词法切分。
   - Python 用标准库 `tokenize`：丢弃注释、空行、缩进与编码声明；标识符统一成 `ID`，数字统一成 `NUM`，字符串统一成 `STR`；关键字与运算符保留原样。
   - C/C++/Java 用正则词法器：先去掉注释与字符串内容，再切出关键字、标识符、数字和运算符。
   - 结果是 `[(kind, text, line), ...]`。改名不改结构，所以“换个变量名”绕不过检测。
2. k-gram 哈希。取 `k = 12` 个记号的连续串，用 Rabin-Karp 滚动哈希得到 64 位整数。滚动哈希使每前进一个记号只需 O(1) 更新。
3. Winnowing。取窗口 `w = 4`，每个窗口保留最小哈希（同值取最右，保证位置可复现）。窗口最小值的集合就是指纹集合，附带记号下标与行号。
   - 效果：文档越长，指纹不会线性膨胀，且被删改的局部内容只影响附近窗口。
4. 两两比较。用倒排索引统计：对每个指纹记录包含它的提交，按对累加共享指纹数。这样比较是 O(总指纹数 × 平均倒排长度)，而不是 O(m²) 的集合两两相交。
5. 相似度定义。
   - `containment(A,B) = |F_A ∩ F_B| / |F_A|`（A 的指纹有多少出现在 B 里）
   - `similarity = max(containment(A,B), containment(B,A))`：一份代码整段抄进另一份时，直接抄袭者会被抓出来。
   - 同时输出 `jaccard = |F_A ∩ F_B| / |F_A ∪ F_B|`，供教师判断。
6. 匹配片段。把命中的记号下标按连续区间合并成片段：`left_start_line, left_end_line, right_start_line, right_end_line, matched_tokens, longest_run`。教师看到的是行号区间，不是抽象分数。
7. 相似簇。相似度高于阈值的配对连边，用并查集求连通分量；成员数 ≥ 3 的分量作为簇输出，按成员数与最高相似度排序。

为什么选它：MOSS 在课程作业查重里被用了二十多年；它对改名、重排、增删注释稳健，实现规模可控，复杂度可分析，且能给出可核对的行号证据。用 AST 树编辑距离可以更精确，但需要为每种语言建解析器，而且对“换了控制结构的等价改写”反而更敏感；本轮不选。

复杂度：设单个提交的记号数为 L，指纹数为 F（F ≤ L）。切分 O(L)；滚动哈希与 winnowing O(L)；倒排索引与计数 O(ΣF × 平均倒排长度)；片段合并 O(命中数)。m 份提交、总指纹量 ΣF 时总时间 O(m·L + ΣF·平均倒排长度)，空间 O(ΣF)。以 200 人、每人 5000 行为量级，单次批次在秒级。

参数与版本：`k=12`、`w=4`、`minimum_tokens=40`、`threshold=0.50` 全部写入输入快照；实现名 `winnowing_token`，版本 `2`（原槽位是未实现的占位）。

## 3. 已通过代码的复杂度分析

### 3.1 产品规则

| 规则 | 说明 |
|---|---|
| 资格 | 仅 `ACCEPTED`、真实执行（非 mock）、当前执行上下文内、通过点数等于总点数 |
| 触发 | 学生对自己的通过提交点击“分析复杂度”；教师可对班级提交触发 |
| 幂等 | 同一提交同一实现版本只分析一次；重复请求返回已有报告 |
| 语言 | Python 做完整静态分析；结构化语言做低置信度词法估计 |
| 结论形态 | 时间与空间各给一个类别、置信度、来源（实测/静态）与备选 |
| 局限 | 合成输入、非最坏情况、LOCAL 无隔离、内存含解释器开销，全部写进报告 |
| 失败 | 没有伸缩档、执行崩溃、全部超时，明确写原因，不编造数值 |

### 3.2 静态结构分析

从源码得到结构事实，不依赖运行：

- Python：用 `ast` 遍历。
  - 最大循环嵌套深度 `loop_depth`（`for`/`while`/推导式，嵌套函数算新作用域）。
  - 折半循环：循环体内出现 `//2`、`>>1` 或 `lo/hi` 更新，判为对数循环。
  - 递归：函数体直接或间接调用自身；两处递归调用且规模折半 → 分治；单递归且 n-1 → 线性递归；双递归 n-1 → 指数。
  - 排序调用（`sort`、`sorted`、`heapq`）→ n log n 因子。
  - 分配：循环内出现 `list`/`dict`/`set` 字面量或 `append` 到按 n 规模增长的结构 → 空间下界。
  - 递归深度与显式栈 → 空间。
  - 结论：`time_class ∈ {O(1), O(log n), O(n), O(n log n), O(n²), O(n² log n), O(n³), O(2^n), UNKNOWN}`，附证据列表（行号 + 原因）。
- C/C++/Java：按括号与关键字切块，统计 `for`/`while` 嵌套深度、自调用、数组声明。置信度固定 `LOW`，结论标注 `lexical_only`。

静态分析永远可算，是经验测量的对照组：两者一致时提高置信度，冲突时把两者都写进报告。

### 3.3 经验增长测量

平台无法对任意题目自动造数据，因此每题需要一份**伸缩档**（scale profile）：声明这道题的输入长什么样，以及规模 n 怎么放进输入。

伸缩档是 JSON，按题型归纳成若干族：

| 族 | 形态 | 典型题目 |
|---|---|---|
| `SINGLE_INT` | 一行一个整数 n | 找零钱、汉诺塔、素数个数 |
| `TWO_INTS` | 一行两个整数 a b | 快速幂、进制转换、按位与 |
| `INT_ARRAY` | 第一行 n，第二行 n 个整数 | 排序、逆序对、滑动窗口 |
| `INT_ARRAY_ROWS` | 第一行 n，随后 n 行每行若干整数 | 活动安排、最近点对 |
| `GRAPH_EDGES` | 第一行 n m，随后 m 行边 | 最短路、最小生成树 |
| `TWO_STRINGS` | 两行字符串 | LCS、编辑距离 |
| `ONE_STRING` | 一行字符串 | 最长回文、KMP |
| `GRID` | 第一行 n m，随后 n 行字符串 | 迷宫、单词搜索 |
| `MATRIX` | 第一行 n m，随后 n 行 m 个整数 | 螺旋矩阵、矩阵旋转 |
| `FIXED` | 输入结构固定（如数独 9 行） | 数独 |
| `EXISTING_CASES` | 不可伸缩，只用已配置测试点的输入 | 其余 |

伸缩档条目形如：

```json
{"CODE-P10": {"family": "INT_ARRAY", "sizes": [64, 128, 256, 512, 1024, 2048, 4096], "max_cases": 1}}
```

生成规则按族写死在代码里，用固定种子生成合法输入：数组值、边权、区间端点都由种子决定，保证同一份档案重复生成同样的数据。题目声明的数据范围作为上限；超出范围的档位直接裁掉。

测量方式：

- 复用 LOCAL 执行门：编译一次，逐档运行，记录每档墙钟时间与子进程峰值常驻内存（`RUSAGE_CHILDREN.ru_maxrss`）。
- 每档有墙钟上限；某档超时即停止加档，记录“到此为止”。
- 每档跑一次；总预算不足时优先保留更大的档位（大规模点更有区分度）。
- 测量结果是真实执行，`is_mock=false`。没有伸缩档的题只出静态结论，状态 `STATIC_ONLY`。

复杂度：生成 O(n) 输入、执行 O(T(n))、拟合 O(档位数 × 候选类别数)。档位数不超过 8，候选类别 8 个，拟合开销可忽略。

### 3.4 增长拟合

对候选族 `f(n) ∈ {1, log₂n, n, n·log₂n, n², n²·log₂n, n³, 2^n}`，用最小二乘拟合 `t = a·f(n)`（a>0），取决定系数 R² 最高的族；R² 接近时取更低阶的族。同时算双对数斜率 `p = d(log t)/d(log n)` 作为经验指数，剔除常数开销后按 `p` 就近归类。

报告给出：`fitted_class`、`r2`、`exponent`、有效档位、被丢弃的高开销档位。R² < 0.90 或有效档位 < 3 时，动态结论标记 `LOW_CONFIDENCE`，最终以静态结论为主，并把冲突写清楚。

空间：静态给空间下界；动态内存是子进程峰值 RSS 的单调最大值，含解释器开销，只用来判断“是否随 n 明显增长”，类别粒度只到 `O(1) / O(n) / O(n²)` 三档，置信度 `LOW`。

### 3.5 合并与呈现

最终报告含两块：`static` 与 `dynamic`，以及 `summary`：

```json
{
  "time": {"class": "O(n log n)", "confidence": "HIGH", "source": "DYNAMIC",
           "static_class": "O(n log n)", "dynamic_class": "O(n log n)", "agreement": true},
  "space": {"class": "O(n)", "confidence": "LOW", "source": "STATIC"},
  "points": [{"n": 64, "time_ms": 3, "peak_rss_kib": 12456}, ...],
  "limitations": ["输入由平台按伸缩档合成，不代表最坏情况", "LOCAL 执行无隔离，仅用于受控开发环境"]
}
```

可视化：横轴 n，纵轴时间，双对数坐标；实测点画点，拟合曲线画线；旁边给出复杂度徽标、置信度、静态证据（嵌套深度、递归类型、证据行号）与局限说明。

## 4. 接口契约

全部挂在 `/api/v1`，Bearer 认证，沿用统一错误格式与字符串 ID。

### 4.1 相似检测（教师）

```
POST /analysis/courses/{course_id}/code-similarity/batches
{"request_id":"sim-001","assignment_id":"1","assignment_item_id":"1","threshold":0.5,"seed":20261028}
→ 201 批次视图（与现有分析批次同构，pipeline=CODE_SIMILARITY，每道编程题一个任务）

GET /analysis/batches/{batch_id}
→ 现有批次视图；steps[].result 即该题相似检测输出

GET /analysis/batches/{batch_id}/similarity
→ {
    "batch_id":"7", "assignment_id":"1", "threshold":0.5,
    "items":[{"item_key":"item-1","item_id":"1","title":"活动安排问题","problem_code":"CODE-P01",
              "status":"SUCCEEDED","submission_count":6,
              "implementation_name":"winnowing_token","implementation_version":"2",
              "pairs":[{"left":{"student_id":"2","student_no":"DEMO2026001","name":"演示同学",
                               "submission_id":"12","version_no":2},
                        "right":{...},
                        "similarity":0.87,"containment_left":0.9,"containment_right":0.87,
                        "jaccard":0.62,"matched_tokens":180,"longest_run_tokens":64,
                        "spans":[{"left_start_line":3,"left_end_line":9,"right_start_line":5,
                                  "right_end_line":11,"matched_tokens":48}]}],
              "clusters":[{"member_keys":["student-2","student-3","student-5"],
                           "member_ids":["2","3","5"],"size":3,"max_similarity":0.91}],
              "insufficient":[{"student_id":"4","reason":"INSUFFICIENT_TOKENS","tokens":12}]}],
    "limitations":["相似度是证据，不是抄袭判定"]
  }
```

### 4.2 复杂度

```
POST /analysis/submissions/{submission_id}/complexity
{"client_request_id":"cx-001"}
→ 202 {"submission_id":"12","status":"PENDING","replayed":false}
   409 INELIGIBLE 该提交尚未真实通过；409 IMPLEMENTATION_CHANGED 需要新报告

GET /analysis/submissions/{submission_id}/complexity
→ {"submission_id":"12","eligible":true,"status":"SUCCEEDED","report":{...},"reason":null}

GET /analysis/courses/{course_id}/complexity?assignment_item_id=1   （教师，班级概览）
→ {"items":[{"student_id":"2","student_no":"...","name":"...","submission_id":"12",
             "status":"SUCCEEDED","time_class":"O(n log n)","space_class":"O(n)"}]}
```

`report` 结构：

```json
{
  "status":"SUCCEEDED",
  "language":"python3",
  "implementation_name":"complexity_probe","implementation_version":"1",
  "time":{"class":"O(n log n)","confidence":"HIGH","source":"DYNAMIC"},
  "space":{"class":"O(n)","confidence":"LOW","source":"STATIC"},
  "static":{"time_class":"O(n log n)","evidence":[{"line":4,"reason":"两路折半递归"}],
            "loop_depth":1,"recursive":true,"allocations":["result"]},
  "dynamic":{"fitted_class":"O(n log n)","r2":0.998,"exponent":1.04,
             "points":[{"n":64,"time_ms":3,"peak_rss_kib":12456}]},
  "limitations":["..."]
}
```

## 5. 数据库

新增两张表，迁移 pg0007。

`problem_complexity_profiles`

| 字段 | 说明 |
|---|---|
| problem_version_id | 外键，唯一；固定在题目版本上 |
| family | 伸缩族名，与代码中的族一一对应 |
| spec | JSONB，档位与生成参数 |
| source | `SEEDED` / `TEACHER` |
| created_by | 外键 users |
| version | 正整数 |

`complexity_reports`

| 字段 | 说明 |
|---|---|
| submission_id | 外键，唯一；一份提交一份报告 |
| assignment_item_id | 外键，便于按题聚合 |
| student_id | 外键，便于按人查 |
| status | `PENDING/RUNNING/SUCCEEDED/STATIC_ONLY/INELIGIBLE/FAILED` |
| time_class / space_class | 复杂度类别字符串，可空 |
| time_confidence / space_confidence | `HIGH/MEDIUM/LOW` |
| time_source / space_source | `DYNAMIC/STATIC` |
| static_analysis / growth / summary | JSONB |
| limitations | JSONB 数组 |
| implementation_name / implementation_version | 固定实现版本 |
| requested_by | 外键 users |
| attempt_no / lease_expires_at / finished_at | 租约与重试 |
| error_message | 可空，截断到 400 字符 |

唯一与检查约束：`submission_id` 唯一；`status` 枚举；`attempt_no >= 0`；`lease_expires_at` 与 `finished_at` 可空；`(time_class IS NULL) = (time_source IS NULL)` 等一致性由服务层保证，不加过度约束。

## 6. 执行与安全

- 相似检测是纯计算，在现有分析 worker 中运行（新增 pipeline，任务由既有 `process_one` 领取）。
- 复杂度测量要执行学生代码，放在独立 CLI `scripts/run_complexity.py`，与 JUDGE 队列隔离；领取用 `FOR UPDATE SKIP LOCKED` 加 120 秒租约，测量在事务外进行，结果写回前重验租约。
- 测量对每档设置墙钟上限与总预算；进程组在超时后整体杀死。复用 `app/judge/local.py` 的启动门、进程组终止与输出上限，不另写一套执行器。
- 相似与复杂度接口都只允许课程成员按角色访问：相似检测仅教师；复杂度本人可读，教师可读本课程。
- 报告和批次中不出现姓名与学号，除教师投影。

## 7. 验证

后端：

- 相似算法：改名/重排/加注释后仍判定高相似；无关代码低相似；空提交与过短提交不配对；倒排索引结果与朴素集合相交一致（随机小样例对拍）；复杂度不超过 O(ΣF) 量级。
- 相似批次：跨题被拒；缺提交等待；教师投影含学号姓名；学生 403；批次幂等。
- 静态复杂度：已知参考实现（归并排序 O(n log n)、冒泡 O(n²)、二分 O(log n)、汉诺塔 O(2^n)）分类正确；结构化语言降级为 LOW。
- 拟合：合成数据 `t = 3n² + 5` 能拟合出 O(n²)；噪声与点数不足时给低置信度。
- 测量：用参考实现真实运行，Python 参考解 P01/P02/P10 跑通并得到合理类别；超时档位被裁剪；无伸缩档返回 `STATIC_ONLY`。
- 权限与幂等：重复请求返回同一报告；未通过提交 409。

前端：组件测试覆盖图表数据转换、状态渲染、空/错误态；`pnpm test`、`vue-tsc`、构建通过。

HTTP：新增 smoke 脚本，真实登录、提交、评测、创建批次、读取证据、生成复杂度报告，全部走 HTTP 并断言权限。

## 8. 与既有设计的关系

- 复用 `analysis-v2` 的批次、快照、任务、结果四张表与 runner/lease 机制，不为相似检测另建队列。
- `code_similarity` 槽位从 `not_implemented` 升级为 `winnowing_token` v2；DEMO 仍用合成数据，REAL_INPUT 走真实算法，`is_mock` 语义不变。
- FULL 23 步流程保留；`code_similarity` 步骤在 FULL 中仍要求单题范围。
- 复杂度报告不参与任何成绩计算，也不改变判题结果。
