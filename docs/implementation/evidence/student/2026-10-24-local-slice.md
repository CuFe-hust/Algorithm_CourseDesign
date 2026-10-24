# 学生作答与评测：2026-10-24 LOCAL 纵向切片证据

分支 `feat/student-submission`，需求快照 `3be855d`，实施日期 2026-10-24。本文只记录**实际执行过**的命令与结果；未执行的项在文末“未覆盖”中明确列出，不冒充通过。

## 1. 运行环境

| 项 | 值 |
|---|---|
| 系统 | macOS（darwin，Apple Silicon） |
| Python | 3.14.5（仓库 `.venv`，uv 管理，依赖来自 `backend/requirements.lock`） |
| 数据库 | PostgreSQL 18.6，`127.0.0.1:5432`，验证库 `algorithm_review_test` |
| Node / 包管理 | Node 22.22.2；`pnpm` CLI 本机损坏（symlink 失败），改用 `npm install` 安装依赖；锁文件仍以 `pnpm-lock.yaml` 为准 |
| 编译器 | Apple clang 21.0.0（`gcc`/`g++`）、`javac 26.0.1` |

## 2. 迁移

```bash
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/python -m alembic upgrade head
```

结果：`pg0001 → pg0002_student_auth → pg0003_judge_lifecycle` 成功；`compare_metadata` 与模型定义差异为 0（由 `tests/test_migrations.py` 断言，含 `upgrade → downgrade base → upgrade` 重复执行）。测试库以外未执行迁移，未改写 `pg0001`。

## 3. 自动化测试

| 命令 | 结果 |
|---|---|
| `DB_NAME=algorithm_review_test ../.venv/bin/python -m pytest -q`（backend） | **106 passed**（基线 68 passed，新增 38 条） |
| `npx vitest run`（frontend） | **36 passed / 9 files**（基线无法运行，`node_modules` 缺失；本次先安装依赖再跑） |
| `npx vue-tsc --noEmit` | 通过 |
| `npx prettier --check "src/**/*.{ts,vue}"` | 通过（仅格式化本轮新增／修改文件） |
| `npx vite build` | 通过（`dist/` 已在 `.gitignore`） |

新增测试文件与覆盖：

| 文件 | 覆盖 |
|---|---|
| `backend/tests/test_auth_sessions.py` | AC03–AC07、AC27、AC31 后端部分、RV02（真实并发连接下的登录／改密串行）、413 请求体上限 |
| `backend/tests/test_student_records.py` | AC02、AC08、AC12、AC15、AC16、AC23–AC24、AC32–AC33 读取与分页、重评冷却／预算 |
| `backend/tests/test_judge_local.py` | AC16–AC18、AC29、AC36：比较器归一化、四语言真实执行、CE／WA／RE／墙钟超时／输出超限、启动闸门、跨进程文件锁 |
| `backend/tests/test_judge_scheduler.py` | AC17–AC21、AC26、AC29–AC30、RV01／RV05：LOCAL 汇总、个人并发 3、模式隔离、所有权丢失丢弃结果、租约恢复清理、迟到启动被拒、派发锁与领取锁互不阻塞 |
| `backend/tests/test_judge_maintenance.py` | AC34、RV09：过期会话／限流桶／诊断的有界清理，保留判定与通过数；CLI 入口 |
| `frontend/src/shared/api.auth.test.ts` | AC31、RV06：认证代次、迟到 401 不清新 token、429 的 `Retry-After`、网络错误不等同过期 |
| `frontend/src/shared/activity.test.ts` | AC04–AC06：1 分钟节流、无操作不续期、隐藏页不续期、401 停止、断网保留意图不风暴 |
| `frontend/src/features/student/draft-store.test.ts` | AC08–AC09、AC33、RV08：按账号／题目／语言隔离、多标签页冲突、存储失败明确报错、未确认请求 |

## 4. 端到端 HTTP 冒烟

```bash
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/python -m scripts.smoke_student_flow --reseed
```

该命令启动真实 uvicorn（随机端口）+ 独立 `python -m scripts.run_judge --once --mode LOCAL` 进程，输出：

```text
PASS server started
PASS health
PASS unauthorised courses
PASS login
PASS login fields
PASS session
PASS renew
PASS student courses
PASS assignments
PASS assignment detail
PASS public cases
PASS hidden data absent
PASS submit accepted
PASS receipt queued
PASS body limit
PASS progress pending
PASS discovery
PASS judge cli
PASS verdict
PASS real execution
PASS no fake resources
PASS counts
PASS progress passed
PASS history
PASS batch status
PASS rejudge rejected for accepted result
PASS withdraw after deadline state is stable
PASS logout
PASS token revoked
29/29 checks passed
```

关键断言：提交后 `PENDING`；CLI 执行后 `result.verdict=ACCEPTED`、`passed_cases=5/5`、`is_mock=false`、`execution_mode=LOCAL`、`cpu_time_ms/memory_kib=null`、`measurement_status=UNAVAILABLE_LOCAL`；进度 `has_passed=true` 且 `best_submission_id` 指向该提交；历史列表不含正文；批量状态返回终态；正常 AC 结果拒绝重评（409）；退出后同一 token 立即 401。

## 5. 验收与审核覆盖

| 编号 | 证据 | 状态 |
|---|---|---|
| AC01–AC02 | 登录／选课页面实现；`test_assignment_detail_is_student_safe_and_scope_checked`、无课程空状态 | 后端与页面逻辑通过；浏览器级 E2E 未跑（见第 6 节） |
| AC03 | `test_first_login_requires_password_change_and_revokes_old_token` | 通过 |
| AC04–AC06 | `activity.test.ts`（假时钟 60s 节流、无活动不续期）；`test_renew_extends_idle_window_only`（2h／24h 上限） | 共享逻辑通过；真实编辑器页面续期未做浏览器验证 |
| AC07 | `test_renew_does_not_resurrect_expired_session_row`、退出后续期 401 | 通过 |
| AC08–AC09 | `draft-store.test.ts`（隔离、冲突、QuotaExceeded 报错） | 通过 |
| AC10–AC11 | 回执与快照逻辑实现；`test_idempotency_replays_once_and_conflicting_payload_returns_409`（既有） | 后端通过；前端“等待中继续编辑”仅代码审查 |
| AC12–AC14 | 截止后同键重放、字节上限、主观题无任务（既有测试 + `test_student_records`） | 通过 |
| AC15 | 他人提交／历史／批量状态均 404（`test_history_...`、`test_batch_status_...`） | 通过 |
| AC16 | 仅公开测试点返回；`test_item_exposes_only_public_test_cases_with_stable_numbers` | 通过 |
| AC17–AC18 | `test_python_...`、`test_cpp_local_execution`、`test_c_local_...`、`test_java_local_execution`、`test_wall_clock_and_output_limits` | 通过（四种语言在本机真实编译执行） |
| AC19–AC20 | `test_personal_concurrency_caps_at_three`（5 份仅 3 份被领取）、`test_node_and_claim_locks_are_independent` | 通过（单进程线程池；真实多进程压测未做） |
| AC21 | `test_recovery_kills_the_old_execution_before_requeueing` | 通过 |
| AC22 | `test_rejudge_requires_facility_failure_cooldown_and_budget`、`test_rejudge_then_local_execution_clears_failure` | 通过 |
| AC23–AC24 | 最佳候选在 LOCAL 空资源下按通过数选择，Mock 不参与（`test_progress_counts_only_real_results...`） | 通过 |
| AC25 | 教师端 68 条基线测试全部保持通过 | 通过 |
| AC26 / RV01 | `test_late_starter_cannot_run_after_recovery_won_the_lock`：暂停旧启动者→恢复撤销 token→恢复后旧启动者被拒且未创建程序（校验不存在标记文件） | 通过 |
| AC27 / RV02 | `test_login_and_change_password_are_serialized_on_the_user_row`：4 次改密仅 1 次成功、最终仅 1 个会话、旧密码失效 | 通过（真实独立连接） |
| AC28 / RV03 | 登录限流、提交限频／突发、个人与节点积压、重评冷却与预算、413 流式请求体 | 接收侧通过；配置级熔断未实现 |
| AC29 | 缺工具链／不支持语言 → 409，不排队；`test_unavailable_language_is_a_configuration_error` | 通过 |
| AC30 / RV05 | 派发锁与领取锁不同键、第二个派发者拿不到锁 | 通过 |
| AC31 / RV06 | `api.auth.test.ts`（迟到 401、代次推进、网络错误区分） | 通过 |
| AC32 / RV07 | `test_job_discovery_scans_every_page_past_one_hundred`（105 条、2 页、无遗漏）、游标伪造 422 | 扫描通过；前端 404 重建路径未做浏览器验证 |
| AC33 / RV08 | 草稿按语言隔离、历史按 language 过滤、无跨语言借正文 | 通过 |
| AC34 / RV09 | `test_auxiliary_cleanup_is_bounded_and_preserves_business_history` | 通过 |
| AC35 | 进度与最佳仅在同 `evaluation_context` 内计算（LOCAL），Mock 排除 | 通过 |
| AC36 | 内部逐点判定汇总，无 `judge_case_results` 表；`test_local_job_produces_real_summary_and_progress` | 通过 |
| AC37 | 教师总预算字段尚不存在，按受控配置推导；执行器保留墙钟上界 | **未完成**（依赖 TD06 与预算字段） |

## 6. 已识别但未修复的偏差

| 偏差 | 影响 | 归属 |
|---|---|---|
| 登录成功后若带 `next` 深链接会直接跳到目标页，未按 R02／接口设计 §3.1-6“重新登录仍先选课” | 重新登录绕过显式选课，违反已定产品规则 | SP07b 一并修 |
| 前端未调用 `GET /me/judge-jobs` 的 DISCOVERY／ACTIVE 接口；课程首页只轮询进度快照里的 `latest_submission_id` | 超过 100 份任务、旧任务被维护恢复执行时不能完整发现（AC32 前端部分缺失） | SP15 前端补 |
| `queue_reason` 实际只产出 `RESOURCE_WAIT` 与 `RETRY_BACKOFF` | `PERSONAL_LIMIT`、`SERVICE_PAUSED` 提示缺失，学生只能看到“排队” | SP18/SP21 |
| 开发库 `algorithm_review` 仍停在 `pg0001`（本轮只在验证库执行迁移） | 直接用开发库启动会 `/ready` 失败、旧表缺列 | 部署前执行 `alembic upgrade head` |
| 诊断容量预算（256 MiB）、结构化日志轮转、启动扫描遗留执行目录未实现 | 只有按天保留，磁盘水位失控时没有提前过期 | SP21 |
| `Scheduler.run_forever` 与 CLI 自带循环重复，当前 CLI 未使用该方法 | 代码冗余，两处容易漂移 | 清理项 |
| `useSubmission.dirtySinceReceipt` 未被页面使用（页面用本地 `dirty` 标记） | 语义重复 | 清理项 |

## 7. 未覆盖与外部依赖

| 项 | 原因 | 后续 |
|---|---|---|
| 浏览器级 E2E（真实编辑器续期、刷新恢复作答、多标签页可视化） | 本轮未引入 Playwright 等 E2E 工具，仅做组件／逻辑测试与 HTTP 冒烟 | SP07b、SP22 |
| 真实多进程调度竞争（≥2 个调度进程同时抢任务） | 测试在单进程线程池内验证；跨进程只有主锁与生命周期锁的断言 | SP23 压测 |
| 200 合成账号集中提交、10 份／人全链路时延 | 未执行 | SP23 |
| 配置级熔断（60 秒内 3 次设施故障暂停）与容量告警 | 未实现 | SP21 |
| Linux 沙箱隔离与 CPU／内存测量 | 按计划属 SL7 | SL7 |
| 教师账号开通／重置、作业发布／名单／DDL 真实联调 | 教师端交付 TD01–TD05 | 交接教师端 |
| `pnpm` 本机损坏 | 环境问题，已用 `npm install` 绕过；`pnpm-lock.yaml` 未改动 | 修复本机 pnpm 后回归 `pnpm test` |
| `_test` 库外的迁移 | 未执行 | 部署时单独安排 |

## 8. 本轮改动文件（概要）

后端：`app/common/auth.py`、`app/core/{errors,limits,ratelimit,bodylimit}.py`、`app/db/models/{identity,analysis}.py`、`app/judge/*`（config、checker、local、gate_launcher、supervisor、locks、results、selection、scheduler、recovery、maintenance）、`app/student/{router,service,schemas,records}.py`、`app/analysis/worker.py`、`app/main.py`、`migrations_postgresql/versions/pg0002_*.py`、`pg0003_*.py`、`scripts/{run_judge,smoke_student_flow}.py`。

前端：`shared/{api,session,activity}.ts`、`shared/{Login,ChangePassword,CourseSelect,Access}.vue`、`app/router.ts`、`features/student/**`、`styles.css`（新增学生区样式）。

文档：`docs/design/shared/api-v1.md`（新增第 7 节）、`docs/design/contracts/openapi.json`（由应用重新生成）、`docs/implementation/runbooks/student-setup.md`、本文件、实施计划追加执行记录。
