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

后端 `python -m pytest -q`：**199 passed**（基线 156，新增 43）。其中：

- `tests/test_similarity_algorithm.py`：31 项，含倒排索引与朴素集合求交的 12 组随机对拍。
- `tests/test_similarity_and_complexity_api.py`：12 项，真实 PostgreSQL + FastAPI TestClient。
- `tests/test_migrations.py` 更新为 pg0007、30 张业务表。

前端：`vitest run` **57 passed**（基线 50，新增 7）；`vue-tsc --noEmit` 通过；`prettier --check` 全库通过；`vite build` 通过。

真实 HTTP：`python scripts/smoke_similarity_complexity_http.py`，**59 项检查通过**。输出摘要：

```
  demo.student01: v3 ACCEPTED (5/5)
  demo.student02: v3 ACCEPTED (5/5)
  demo.student03: v3 ACCEPTED (5/5)
  demo.student04: v3 ACCEPTED (5/5)
  demo.student05: v3 WRONG_ANSWER (0/5)
  demo.student06: v3 WRONG_ANSWER (0/5)
  similarity: 3 pairs, 1 clusters, top=1.000000
  complexity: SUCCEEDED time=O(n) space=O(n) source=DYNAMIC
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

## 5. 一处需要说明的测量结论

最初的设计假设“实测增长总能给出复杂度”，实测发现不成立：程序读输入本身是 O(n)，二分查找的实测总时间和纯读取同阶，无法区分 O(log n) 与 O(n)。因此增加了纯输入读取基线，并把规则改为“实测必须明显超过读取成本才作为依据”，否则回落到结构分析并在报告里写明只能给出上界。这条规则在 `test_combine_does_not_claim_a_class_the_measurement_cannot_separate` 和真实冒烟中都被固定下来。

## 6. 未做与边界

- 没有 Linux 沙箱：测量与评测一样在服务主机执行，只适合受控开发环境。
- C/C++/Java 只做词法结构分析，置信度固定 LOW。
- 题库里 70 道编程题的伸缩档按输入格式人工归类；写错的族会生成不合法输入，此时程序多半运行错误，报告会显示失败档位而不是伪造曲线。
- 相似检测不判断抄袭，不生成处置动作；教师决定怎么处理。
- 前端没有引入图表库，曲线是自绘 SVG。
