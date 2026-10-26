# Analysis Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 实现已确认的全链路分析框架：任务/输入/输出落库、15类算法槽位、真实输入读取与合成场景演示，保留人工等待与可替换算法。

**Architecture:** 独立于现有JUDGE队列的分析批次与任务，数据库快照→纯算法→版本化输出。一个worker执行就绪任务；DEMO的人工步骤显式推进，REAL_INPUT不补造互评和正式成绩。

**Tech Stack:** 现有FastAPI/Pydantic、SQLAlchemy/PostgreSQL、Alembic、pytest，不新增运行依赖。

**Spec:** ../specs/2026-10-26-analysis-framework-design.md（用户已确认，授权继续写计划并开发）。

## Global Constraints

- 保留已有LOCAL/MOCK评测、学生和教师接口；整班任务不写入analysis_jobs。
- 新迁移pg0005，依赖教师集成分支pg0004；该分支仅合入本地分析功能分支，不推共享main。
- 四类记录：analysis_batches、analysis_input_snapshots、analysis_runs、analysis_artifacts。ID字符串、分数十进制字符串、UTC时间。
- DEMO/REAL_INPUT严格分开，mock沿依赖传播；正式成绩业务仍是后续，不伪造完成。
- 随机模拟值固定seed并保存；真实插件未实现返回NOT_IMPLEMENTED，缺数据WAITING_INPUT。
- 实施采用本会话顺序开发，最终独立审阅；不逐任务重复请求授权。
- 使用.worktrees/analysis-framework独立Git工作副本。应用原生worktree工具因调用上下文非Git仓库失败，采用Git worktree回退；共享现有虚拟环境，私有.env仅复制到已忽略本地副本。

## Review Focus

1. 并发run/事件/worker完成：批次行锁、任务attempt_token与租约、过期结果拒绝。
2. 跨课程/学生访问：所有批次写读查任课权限；catalog也需登录；学生不读通用artifact。
3. 相同request_id不同body：返回409，既有批次/事件/运行不可覆盖；人工事件重复不重做。
4. 缺输入/零分/不足/未实现分开，任何依赖mock的派生输出继续mock；REAL_INPUT拒绝演示人工事件。
5. 数据变动及版本：一致性快照，hash覆盖参数/配置，结果只追加；重试attempt变化、原输出历史保留。

## Task 1 — Pure contracts, catalogue and algorithms

**Files:** app/analysis/framework/{contracts,catalog,graph}.py；app/analysis/algorithms/{baseline,mock}.py；tests/test_analysis_contracts.py。

**Interfaces:** `catalogue()->list[dict]`含15插件的输入输出JSON Schema；`invoke(key,payload,*,mode,seed,input_hash)->AlgorithmOutput`；`steps()->list[Step]`给编排依赖；`digest(value)->str`稳定JSON hash。

- [ ] 写失败测试：15插件schema完整；真实AI未实现；受约束匹配不自评/不重复/负载可验；人数不足INFEASIBLE；聚合0分不是null、缺样本null、权重0排除、分数越界拒绝；seed稳定。
- [ ] 运行定向pytest确认缺模块/行为失败，再实施契约、基线、模拟与DAG。
- [ ] 用独立dict/Pydantic数据，禁止算法导入SQLAlchemy/FastAPI；输出hash必须对应输入，输出引用属于输入范围。
- [ ] 验证定向测试通过并提交。

## Task 2 — Persistence and snapshot adapters

**Files:** app/db/models/analytics.py、models/__init__.py、migrations_postgresql/versions/pg0005_analysis_framework.py；app/analysis/framework/{fixtures,snapshots}.py；tests/test_analysis_storage.py；既有test_migrations.py。

**Interfaces:** `demo_snapshot(seed)->dict`合成6人/两类题；`capture(db,course_id,assignment_id,mode,seed)->dict`只读真实名单/提交/结果并固定版本/上下文；四个模型供服务层使用。

- [ ] 写失败测试：pg0005升级/往返与28表模型一致；真实快照不含姓名学号/密码；DEMO稳定且mock；跨课作业拒绝；原数据不改。
- [ ] 在专用algorithm_review_test应用迁移，禁止清空项目库。现有conftest的/tmp假设改为仅非Windows设置，Windows使用本机pytest temp。
- [ ] 模型/静态迁移保持一致，增加状态CHECK、唯一约束和必要索引；快照采集使用可重读事务，阻止后续覆盖。
- [ ] 定向测试通过并提交。

## Task 3 — Orchestration, worker and HTTP API

**Files:** app/analysis/framework/{service,runner,payloads}.py；app/analysis/router.py；app/main.py；scripts/run_analysis.py；tests/test_analysis_flow.py。

**Interfaces:** `create_batch(db,course_id,actor,body)`、`batch_view(db,batch_id,actor)`、`advance(db,batch_id,actor,request_id)`、`demo_event(db,batch_id,actor,body)`、`process_one(db)->bool`。

- [ ] 写失败测试：DEMO逐阶段等待OPEN_REVIEW/SUBMIT_REVIEWS/RESOLVE/RELEASE；所有独立任务先就绪；缺真实互评等待；补评节点有显式入口且可无缺口SKIPPED。
- [ ] 实施一个逻辑批次含固定步骤，run只推进满足前置/业务状态的任务；人工步骤不可自动跨过，数据不足保留blocked_by/reason。
- [ ] 匹配/聚合mock或baseline结果各自记录来源；合成评审事件来自fixture；真实代码计分无证据时不编造分数。
- [ ] 每任务保存input_hash/payload快照、算法版本/seed/参数；worker领取用SKIP LOCKED，完成需持有有效token/租约；失败有界重试保留attempt历史。
- [ ] HTTP catalog/create/view/run/demo-events复用登录与任课权限、统一错误；额外retry接口仅FAILED且新attempt，不改输入。
- [ ] 越权、幂等冲突、并发/过期完成、真实模式禁止演示事件测试通过并提交。

## Task 4 — Demonstration, schemas and verified handoff

**Files:** backend/scripts/demo_analysis.py、export_analysis_contracts.py；docs/design/analysis/{api,black-boxes}.md；docs/implementation/runbooks/analysis-setup.md；data/analysis/{catalog,example-inputs,example-outputs}.json；图状态/索引更新。

- [ ] CLI以合成DEMO运行完整六条线，输出稳定计数与mock标记，不输出token/个人资料；可以按人工节点逐段暂停讲解。
- [ ] 从实际catalog生成JSON Schema和每插件成对输入输出样例；替换函数入口及验证命令写入黑盒说明。
- [ ] 更新两张4K图与状态：框架/合成演示已实现，研究插件未实现，正式互评/发布未接入；PNG/SVG hash核对。
- [ ] 定向回归＋全部后端测试；前端仅因共享整合已有代码需跑既有测试/构建，不新增UI；实际HTTP演示验证。
- [ ] 请求一次最终独立代码审阅，修复重要问题，更新验收证据和本计划勾选。
- [ ] 提交独立副本全部变更，回到分析分支fast-forward整合；本轮不擅自合并/推送共享main。

## Execution ledger

- 设计确认：用户明确“认可，按此边界继续”，同时授权写计划并开发；按已授权目标连续执行，不重复请求选择执行方式。
- Ruling: 为满足最新教师/学生接入与单迁移链，本地分析分支合入9865289；共享main保持不变。唯一docs/README冲突保留双方链接。
