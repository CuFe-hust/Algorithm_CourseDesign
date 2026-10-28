# 相似检测与复杂度分析：实现与验证记录

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

后端 `python -m pytest -q`：**228 passed**（基线 156，新增 72）。其中：

- `tests/test_similarity_algorithm.py`：57 项，含倒排索引与朴素集合求交的 12 组随机对拍、6 个类别的无噪声还原、降阶规则的残差级验证、log 因子三对的双向合并用例。
- `tests/test_similarity_and_complexity_api.py`：15 项，真实 PostgreSQL + FastAPI TestClient。
- `tests/test_migrations.py` 更新为 pg0007、30 张业务表。

有两处已知的偶发失败：`tests/test_judge_scheduler.py::test_service_pause_keeps_jobs_queued_and_resumes_after_switch` 在完整套件里偶发失败一次（单独运行与随后两次完整运行均通过）。`tests/test_judge_local.py::test_cpp_local_execution` 在完整套件里也偶发失败一次（单独运行与随后两次完整运行均通过）。这两个测试都属评测调度与本地执行，与本轮改动无关，也未修改；记录在此避免把它们误当成稳定现象。

前端：`vitest run` **79 passed**（20 个文件，基线 50，新增 29）；`vue-tsc --noEmit` 通过；`prettier --check` 全库通过；`vite build` 通过。

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

验证库 `algorithm_review_test` 覆盖 upgrade → downgrade pg0006 → upgrade，`compare_metadata` 差异为空。业务表从 28 张增到 30 张。

## 5. 独立审核发现并修好的问题

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

## 6. 实验暴露并修好的缺陷

`backend/scripts/experiment_similarity_complexity.py` 用本实现自带的函数跑了 6 组复杂度对照，发现两个真实缺陷：

| 缺陷 | 暴露它的实验 | 数字 | 修复 |
|---|---|---|---|
| 无噪声的 `O(n log n)` 曲线被判成 `O(n)` | fit 标定：把理想曲线喂给同一个 `fit_growth` | 5 次重复全部错 | 按残差平方和选类，降阶需通过 `exp(2/m)` 的 AIC 门槛 |
| 实测无法分辨只差一个 log 因子的两类 | 同一组数据的带噪声重复（σ=2%/5%/10%） | 40 次里 13 次分错 | 这一类改由结构分析裁定，实测分歧写进限制 |

另外两条规则从同一批数字推出：有效档位少于 5 不给 MEDIUM 以上置信度（4 档时 `O(n²)` 被判成 `O(n log n)`）；字面量边界的循环不再贡献多项式因子（`for _ in range(60000)` 是常数，旧实现把整个程序算成 `O(n log n)`）。

修复后同一套实验 6/6 组一致。这不是"现在全对了"：噪声下 log 因子仍然不稳定，报告里的结论仍需配合置信度与限制说明读。完整数字见 [experiments-2026-10-28.json](experiments-2026-10-28.json)，分析见[算法实验](../../../design/analysis/algorithm-experiments.md)。

## 7. 一处需要说明的测量结论

最初的设计假设“实测增长总能给出复杂度”，实测发现不成立：程序读输入本身是 O(n)，二分查找的实测总时间和纯读取同阶，无法区分 O(log n) 与 O(n)。因此增加了纯输入读取基线，并把规则改为“实测必须明显超过读取成本才作为依据”，否则回落到结构分析并在报告里写明只能给出上界。这条规则在 `test_combine_does_not_claim_a_class_the_measurement_cannot_separate` 和真实冒烟中都被固定下来。

## 8. 未做与边界

- 没有 Linux 沙箱：测量与评测一样在服务主机执行，只适合受控开发环境。
- C/C++/Java 只做词法结构分析，置信度固定 LOW。
- 题库里 70 道编程题的伸缩档按输入格式人工归类；写错的族会生成不合法输入，此时程序多半运行错误，报告会显示失败档位而不是伪造曲线。
- 相似检测不判断抄袭，不生成处置动作；教师决定怎么处理。
- 前端没有引入图表库，曲线是自绘 SVG。
