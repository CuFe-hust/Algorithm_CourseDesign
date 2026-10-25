# 学生作答与评测运行手册

本手册只写**已实现并实际执行过**的命令。当前交付为单节点、本机 LOCAL 真实执行（`is_mock=false`、不测量 CPU／内存），不含 Linux 沙箱隔离。

## 1. 前置条件

- macOS／Linux，Python 3.13+（本机使用仓库 `.venv`，CPython 3.14.5），PostgreSQL 18 已在 `.env` 配置（本机 5432）。
- Node 22.12+，`frontend/node_modules` 可使用 `pnpm install --frozen-lockfile` 或 `npm install` 安装。
- 四语言工具链按需可用：`python3`、`g++`、`gcc`、`javac`/`java`。缺失的语言在 LOCAL 模式下提交会返回 `409 JUDGE_CONFIGURATION_UNSUPPORTED`，不会进入永久排队。

## 2. 数据库与迁移

```bash
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/python -m alembic upgrade head
DB_NAME=algorithm_review_test ../.venv/bin/python -m alembic downgrade base   # 可选：验证可回滚
DB_NAME=algorithm_review_test ../.venv/bin/python -m alembic upgrade head
```

本轮新增两个顺序迁移：`pg0002_student_auth`（`users.must_change_password`、`auth_sessions.last_active_at/absolute_expires_at`、`request_rate_limits`）、`pg0003_judge_lifecycle`（任务租约／阶段／尝试、`judge_attempts`、`judge_retry_requests`、`judge_results` 汇总字段）。旧会话按 `created_at + 24h` 回填绝对期限，不会被续长；旧结果一律按 `MOCK` 解释，不回填真实通过数。

## 3. 启动 API 与评测执行器

```bash
cd backend
DB_NAME=algorithm_review_test JUDGE_EXECUTION_MODE=LOCAL \
  ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端启动执行器（同一 `DB_NAME`，`JUDGE_EXECUTION_MODE` 必须与提交时一致）：

```bash
cd backend
DB_NAME=algorithm_review_test JUDGE_EXECUTION_MODE=LOCAL \
  ../.venv/bin/python -m scripts.run_judge --mode LOCAL --concurrency 2 --loop
```

- `--once`：领取一批并执行后退出，用于验证配置。
- `--recover`：清理租约过期的任务（先撤销 token、终止旧执行，再重排或置 `FAILED`）。
- `--purge-aux`：清理过期会话、限流桶与超过保留期的编译诊断（不动提交、判定和幂等记录）。
- 第二个 `--loop` 进程拿不到节点派发锁，会以退出码 2 结束并提示 `dispatch lock busy`，不会重复调度。

运维暂停（不丢弃已接收任务）：在启动执行器的环境里设置 `JUDGE_SERVICE_PAUSED=1`，调度器停止领取新任务，学生侧看到 `queue_reason=SERVICE_PAUSED`；去掉该变量后继续执行。

开发库（`DB_NAME=algorithm_review`）同样需要先升级到 `pg0003`，否则 `/ready` 会因迁移版本不一致返回 503。本机已于 2026-10-25 升级并备份到 `~/algoclass-backups/`。

健康检查：`GET /api/v1/health`、`GET /api/v1/ready`（`ready` 同时校验迁移版本）。

## 4. 前端

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev            # http://127.0.0.1:5173 ，/api 代理到 127.0.0.1:8000
```

学生入口：登录 →（首次登录先改密）→ 选择课程 → 课程首页 → 作业 → 题目作答。

## 5. 检查与验证命令

```bash
# 后端（仅指向 *\_test 验证库；该库会被清空重建）
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/python -m pytest -q

# 前端
cd frontend
npx vitest run
npx vue-tsc --noEmit
npx prettier --check "src/**/*.{ts,vue}"
npx vite build

# 端到端 HTTP 冒烟（启动真实 uvicorn + 独立 CLI 执行器）
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/python -m scripts.smoke_student_flow --reseed
```

`--reseed` 只允许数据库名以 `_test` 结尾，会先清空验证库再建立演示数据；不要指向项目业务库。

## 6. 常见问题

| 现象 | 排查 |
|---|---|
| 提交返回 `409 JUDGE_CONFIGURATION_UNSUPPORTED` | 该语言在本机缺少工具链，或测试集未冻结；补齐环境后重新提交，不要反复重试 |
| 任务长期 `PENDING` 且 `queue_reason=PERSONAL_LIMIT` | 本人已有 3 份在执行；等前面任务结束 |
| `429 SUBMISSION_BACKLOG_LIMIT` | 本人待处理任务达到 20 份；这是“未接收”，草稿仍保留 |
| 任务 `FAILED` 且 `can_retry=false` | 冷却中、累计预算耗尽或配置未修复；按 `retry_block_reason` 处理 |
| 编辑诊断显示“已过期” | 诊断超过 30 天保留期被清理，判定与通过数仍然有效 |
| 浏览器提示草稿未跨刷新保留 | IndexedDB 不可用，页面已降级为内存存储；提交前请手动复制内容 |
| `--loop` 退出码 3 | 派发连接丢失（数据库不可用），重启执行器；已运行任务按租约恢复 |

## 7. 未包含的能力

- Linux 沙箱隔离、CPU／内存测量与 MLE 判定（SL7）。
- 教师端账号开通／重置、作业发布／名单／DDL 管理入口（由教师端交付，见 TD01–TD08）。
- 互评、成绩聚合与正式成绩发布。
