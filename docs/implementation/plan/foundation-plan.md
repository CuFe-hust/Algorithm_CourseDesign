# 公共数据库与后端底座实施计划 V0.1.0

> 历史记录：本文保留早期MySQL方案及当时验证结果。当前已切换PostgreSQL，启动与全量数据以README、POSTGRESQL_MIGRATION.md为准；当前4K图已更新。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 在本会话内顺序实施，不自动创建其他代理或 GitHub Issue。

**Goal:** 提供可供三人独立启动、连接各自 MySQL 的公共后端，跑通登录、读取题目、提交答案及模拟评测结果查询。

**Architecture:** 一个共享后端工程，teacher、student、analysis 按功能组织，共用数据库模型与权限基础。模拟评测结果实际落库并明确标记；复杂匹配、聚合、检测算法保留输入输出契约，后续替换。当前迭代不实现完整教师页面、学生页面、匿名互评或真实沙箱执行。

**Tech Stack:** Python、FastAPI、SQLAlchemy、Alembic、PyMySQL；MySQL；前端预定 Vue 3、TypeScript、Vite，本轮交付可调用接口及样例，供前端开发。

**Spec:** [数据库设计讨论稿](../../archive/database-design-v0.1.md)。该稿的 13 张表尚不构成完整迁移；任务 1 先补足本轮涉及的配置与结果表，并标记仍待下一迭代实现的流程。

## Global Constraints

- 日期：2026-10-21；本机最小链路已实现并验证；复选状态反映本次实施结果，队友实际机器验收仍待执行。
- 工程建议新建在大作业目录下的 `course-review-platform/`，不覆盖原始材料。初始化前检查同名目录及上级 Git 状态。
- 三人本地数据库独立，以同一套模型、迁移和合成种子保持一致；不合并调试数据库文件。
- 内部 ID 为 BIGINT UNSIGNED；接口 ID 为十进制字符串。学号按字符串处理；姓名允许重复。
- UTF-8/utf8mb4；业务时间保存 UTC，接口输出带时区。分数和权重使用精确十进制。
- 引入新的虚拟环境和项目依赖清单，不修改系统级 Python 依赖；固定实际验证通过的依赖版本。
- 本机已发现 MySQL94 服务运行中，不重装、不重置现有服务或账户；具体 MySQL 连接、版本及授权要实际验证。
- 数据库连接通过本地 `.env` 提供，仓库仅提交无凭据的 `.env.example`。缺凭据时继续完成代码与文档，不能宣称 MySQL 验证通过。
- 建库仅针对明确命名的项目数据库；禁止清空既有数据库。迁移和种子在独立验证库执行后才能用于项目库。
- 每次结果区分模拟与真实。模拟阶段资源使用留空，不能把随机数字描述为测量的运行时间或内存。
- 真实名册不作为公共 GitHub 演示数据；学生测试使用合成姓名与学号。真实题目先选少量示例，不批量导入未经核对的参考答案或公式转换结果。

## Review Focus

- 学号含字母与同名学生：按学号和内部 ID 对应，不能转整数或按姓名合并；任务 3、4 验证。
- 未授权查询：教师权限、课程归属、作业名单和学生本人数据均由服务端检查；任务 5 验证。
- 网络重试与并发提交：同一幂等请求只保存一次，同标识不同内容返回冲突；任务 5 验证。
- 源资料带答案与公式：学生响应隐藏教师参考资料和隐藏用例，演示题公式逐项核对；任务 1、4、5 验证。
- 模拟结果与正式成绩混淆：接口明确模拟标记，未运行测试不生成真实资源指标，也不冒充正式成绩发布；任务 6 验证。

## 任务 1：补齐最小闭环设计与接口契约

**Files:** 更新 `01_DATABASE_DESIGN_V0.1.0.md`；工程内新增 `docs/design/contracts/foundation-v1.md`、`docs/design/contracts/examples/`。

**Interfaces:** 输入为现有 13 表设计、题目样例和已对齐三模块职责；输出为下列数据与接口约定，供所有后续任务使用。

- [x] 补齐 test_suites、test_cases、reference_solutions、rubrics、rubric_items、analysis_jobs、judge_results 的字段及关联；落实作业引用配置版本与冻结规则。
- [x] 本轮支持账号、课程名单、题目、作业、提交与模拟评测；互评、聚合、检测、正式成绩发布明确列为后续范围，不把本轮底座标为最终系统。
- [x] 定义登录、课程列表、作业列表、题目详情、提交、提交详情及模拟任务处理的请求、响应与错误样例。学生响应使用独立结构，禁止直接序列化全部数据库字段。
- [x] 规定 `POST /api/v1/auth/login`、`GET /api/v1/courses`、`GET /api/v1/courses/{course_id}/assignments`、`GET /api/v1/assignment-items/{item_id}`、`POST /api/v1/assignment-items/{item_id}/submissions`、`GET /api/v1/submissions/{submission_id}`。
- [x] 提交接口返回 202、提交 ID 和任务状态；主观题返回已接收状态、不创建代码评测任务；编程题登记 PENDING 任务。
- [x] 固定错误格式 `code/message/details/request_id`；401 表示未登录，403 表示已知但禁止的操作，404 用于隐藏不可见资源，409 表示幂等或版本冲突，422 表示字段错误。
- [x] 定义 `JudgeInput`、`JudgeOutput`：输入包含提交 ID、源码、语言和测试集版本；输出包含判定、模拟标记、算法版本及允许为空的资源指标。模型结构在契约中完整列明后再写业务代码。

验收：读取题目、提交编程答案、提交主观答案三条链路均能沿字段追溯；数据库字段和接口样例一致，无未定义的必需引用。

## 任务 2：建立可启动的共享工程

**Files:** `backend/pyproject.toml`、依赖锁文件、`backend/app/main.py`、`core/config.py`、`core/errors.py`、`db/session.py`、`.env.example`、`.gitignore`、`tests/test_health.py`。

**Interfaces:** 提供 `create_app() -> FastAPI`、`get_db()` 数据库会话依赖及 `GET /api/v1/health` 存活接口；健康检查不暴露连接字符串。

- [x] 先写并运行应用启动和健康响应测试，确认在应用尚未创建时失败。
- [x] 创建独立虚拟环境，安装并锁定依赖。保留 teacher、student、analysis 路由入口，统一注册到应用。
- [x] 实现环境配置校验、请求标识、错误格式；本地凭据文件和虚拟环境加入忽略规则。
- [x] 实现存活检查与单独的数据库就绪检查；数据库未连接时存活可正常返回，就绪检查明确失败。
- [x] 验证应用可启动、接口文档可访问，缺连接配置时不误报数据库已就绪。

验收：`pytest tests/test_health.py -q` 通过；使用 `uvicorn app.main:app` 可启动，接口前缀统一。

## 任务 3：模型与可重复迁移

**Files:** `db/base.py`、`db/models/identity.py`、`problems.py`、`assignments.py`、`submissions.py`、`analysis.py`；`alembic.ini`、`migrations/`、`tests/integration/test_migrations.py`。

**Interfaces:** 模型字段遵循任务 1 定稿；数据库创建使用 `alembic upgrade head`，业务启动不得用隐式建表替代迁移。

- [x] 先写真实 MySQL 集成验证：从空验证库升级、查询预期表和约束、重复升级不产生变化；未实施前确认失败。
- [x] 实现本轮模型、外键、唯一索引及数据类型；账户、题号等编码规范与数据库比较规则保持一致。
- [x] 生成并人工检查首次迁移，保证作业题目对量表和测试集的引用都有实际目标表。
- [x] 验证含字母学号可保存；重复学号与重复作业题目顺序被拒绝；外键引用不存在记录被拒绝。
- [x] 仅使用明确指定的独立验证库运行上述检查，不以 SQLite 的通过替代 MySQL 证据。

验收：真实 MySQL 集成检查通过，迁移版本可查询；表、约束与设计一致。没有可用连接时该任务保留未完成。

## 任务 4：演示数据和题目来源整理

**Files:** `backend/scripts/seed_demo.py`、`data/demo/`、`docs/implementation/runbooks/data-import.md`、`tests/integration/test_seed_demo.py`。

**Interfaces:** 提供 `seed_demo(session) -> SeedSummary`；只建立带明确演示标记的数据，不删除或覆盖真实数据。

- [x] 先验证连续执行两次种子不增加重复账号、题目、作业；不同学号同名可存在。
- [x] 生成一位演示教师、至少六位合成学生、两个班、一门课程；密码通过本地演示配置设定并哈希，不写进仓库。
- [x] 选择一题编程题及三类主观题各一题，准备固定题目版本、标签、测试集、参考资料及量表；核对所有演示题数学表达式。
- [x] 创建一份纯编程和一份混合作业，含发布时名单与固定题目配置。截止时间通过明确参数设置，说明演示运行时如何更新。
- [x] 记录原题来源和导入映射；CSV 首版只固定模板与校验契约，完整教师导入页面由教师模块实现。

验收：另一位成员在自己的空库迁移后可执行种子得到等价演示环境；学生可见数据与教师参考资料分离。

## 任务 5：登录、读取和提交链路

**Files:** `common/auth.py`、`common/permissions.py`、`teacher/`、`student/` 对应 router/schema/service；`tests/integration/test_auth.py`、`test_student_flow.py`。

**Interfaces:** 实现任务 1 的路由；权限从登录会话和课程成员获取，不接受客户端传入角色冒充身份。登录机制与 CSRF/CORS 配置在契约中固定后统一实现。

- [x] 先写教师/学生登录、未登录拒绝、跨学生查询拒绝、非课程成员和非作业参与者拒绝的测试。
- [x] 实现演示账号登录及权限依赖；教师查询入口与学生响应遵循同一资源归属规则。
- [x] 实现课程与作业查询、学生题目详情；断言参考答案、标准代码、隐藏测试不出现在学生响应中。
- [x] 实现正式提交与版本递增；以事务保证编程提交和任务同时保存。主观提交只保存答案，不自动判分。
- [x] 验证同请求重试不重复入库、同请求标识不同内容返回 409；并发版本不冲突，截止与撤回规则符合设计。
- [x] 验证程序源码、中文及公式内容往返保存后保持一致；数据库故障不得返回提交成功。

验收：教师提供的演示作业可被合法学生读取和提交；越权、重试、截止及隐藏数据保护均有验证证据。

## 任务 6：模拟评测与交接包

**Files:** `analysis/contracts.py`、`analysis/judge_mock.py`、`analysis/worker.py`、`scripts/process_mock_jobs.py`、`tests/integration/test_mock_judge.py`、`README.md`、`docs/archive/team-handoff.md`。

**Interfaces:** `judge(input: JudgeInput) -> JudgeOutput`；`process_pending_jobs(session, limit: int) -> int`。后者由明确命令触发，页面请求不假装任务已被执行。

- [x] 先验证编程提交形成任务、处理后可查询持久化模拟结果，重复处理不创建重复有效结果。
- [x] 实现确定性模拟适配器；输出清楚标记 `is_mock=true`、实现名称及版本，CPU 时间和内存为空。
- [x] 实现任务 PENDING/RUNNING/SUCCEEDED/FAILED 状态及失败记录；本轮先单执行器处理，文档说明限制。评测结果与正式成绩发布保持区分。
- [x] 完整运行登录、读题、提交、处理模拟任务、查结果；主观答案仍保持等待后续互评的业务含义。
- [x] 编写 Windows 本地启动、迁移、种子、处理任务及接口调用说明；列明实际验证的 Python、MySQL、Node 版本。
- [x] 给三个 Issue 准备可复制的范围与交接清单，并明确哪些公共文件变更由谁协调；没有仓库 URL 时只保存本地草稿，不创建线上 Issue。

验收：另一位成员可以照说明完成最小链路；全部成功声明都有对应命令和输出，明确尚未接入真实评测及复杂算法。

## 首次交接的完成定义

- [x] 从空项目验证库可完成迁移与种子，不依赖作者手工修改数据库。
- [x] 三个开发范围使用同一套模型、配置方式与接口约定。
- [x] 题目读取、正式提交、模拟任务和结果查询可实际调用。
- [x] 教师/学生权限、匿名准备边界、题目参考资料隔离均有验证。
- [ ] 每个成员可以独立运行自己的环境，前端可据接口文档开始真实联调。（本机重建与HTTP验证已通过，其他成员机器待本人执行。）
- [x] MySQL 连接和验证记录齐全；缺连接、缺验证时明确保留未完成状态。

## 当前实际进度

- 已有：题目与名册来源、第一版 13 表设计、技术方向、此实施计划。
- 已检查本机：MySQL94 服务正在运行；Python 3.14.5；Node 已安装；系统 Python 能导入 FastAPI、SQLAlchemy、uvicorn、pytest；Alembic、PyMySQL 尚未安装。实施仍使用新虚拟环境。
- 已实现：course-review-platform工程、21张业务表、0001/0002迁移、种子、登录与提交/模拟结果接口；27项测试和真实HTTP联调通过。
- 连接条件已落实：本机项目专用MySQL 9.4.0，127.0.0.1:3307；账号仅具有项目库与验证库权限，密码保存在本地.env。
