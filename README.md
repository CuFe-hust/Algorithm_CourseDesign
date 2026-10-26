# 算法课程评审平台

已实现统一教师/学生前端与共享FastAPI、PostgreSQL后端，24张业务表、迁移head为pg0004。教师可管理四类题目、导入及开通学生账号、发放/重置初始密码、创建发布作业、调整截止和查看采用结果；学生可改密、作答、提交、查看历史与LOCAL真实评测。匿名互评、评分聚合、正式成绩与Linux沙箱仍待后续模块。

## 三人从这里开始

**[MAIN.md：项目主文档、分工与开发顺序](MAIN.md)**。本仓库提供已经跑通最小链路的协作底座，三位成员可基于它分别推进教师、学生与互评分析模块。

今晚开会：[讲解顺序与下一步动作](docs/archive/meeting-2026-10-21.md) · [数据库模式图（4K）](docs/assets/diagrams/01-database-schema-4k.png) · [交互流程图（4K）](docs/assets/diagrams/02-interaction-flow-4k.png) · [SVG源文件及完整外键清单](docs/assets/diagrams/README.md)。

| 负责人 | 任务正文 | 先做什么 |
|---|---|---|
| T：教师队友 | [教师Issue](docs/issues/01-teacher.md) | TH00统一Vue骨架，然后CSV、题库和作业写入 |
| S：学生队友 | [学生Issue](docs/issues/02-student.md) | 当前真实作答页面，接着历史，再接AN01互评 |
| A：数据库与分析负责人 | [分析Issue](docs/issues/03-database-analysis.md) | 在底座上补互评契约/数据/基础流程，再聚合/检测/发布 |

阅读顺序：本README启动 → MAIN和自己的Issue → [数据库与归属](docs/design/shared/database.md) → [信息流](docs/design/shared/data-flows.md) → [当前API格式](docs/design/shared/api-v1.md)。规划接口另见[下一阶段提案](docs/design/contracts/next-phase.md)，未标记为已实现的接口不能当作可调用。

推送与分支/PR方式见[Git协作](docs/implementation/runbooks/collaboration.md)。仓库有3个GitHub Issue模板，推送后可直接选用，负责人待你填写；当前未在线创建Issue；远程仓库已配置并推送。

开发资料包含70道编程题、主观题原Word和任务书，见[data/source](data/source/README.md)；全量120题及217位合成身份、8班的结构化快照见[data/formatted](data/formatted/README.md)，队友可直接导入；真实名册及映射仅留本机。前端位置和公共骨架分工见[frontend约定](frontend/README.md)，教师前端已可启动，见 [教师端架构](docs/design/teacher/architecture.md) 和 [运行验收](docs/implementation/runbooks/teacher-setup.md)。

## 完整启动顺序

在工程根目录使用PowerShell。本机实际验证Python 3.14.5、PostgreSQL 18.6，建议队友使用同版本；依赖锁文件包含运行与测试依赖。需要预先安装Python和[PostgreSQL程序](https://www.postgresql.org/download/windows/)，或将解压后的bin目录设为PG_BIN。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe scripts/setup_local_postgres.py
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.seed_demo
..\.venv\Scripts\python.exe -m scripts.import_full_data
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 [接口文档](http://127.0.0.1:8000/docs)。演示教师为 `demo.teacher`，演示学生为 `demo.student01`～`demo.student06`，共同演示密码随机生成在工程根 `.env` 的 `DEMO_PASSWORD`，在本地编辑器查看，勿发到公开Issue。登录接口返回access_token，点击Authorize填入后调用业务接口。

另开终端进入backend目录，运行模拟任务消费：

```powershell
..\.venv\Scripts\python.exe -m scripts.process_mock_jobs --watch
```

上述命令仅用于MOCK联调，不执行源码；真实LOCAL开发流程见[学生运行说明](docs/implementation/runbooks/student-setup.md)。结果固定明确标记 `MOCK_ACCEPTED/is_mock=true`，时间和内存为空，不代表程序正确或正式成绩。主观答案保存后为AWAITING_REVIEW。

发生worker异常退出后，先停止全部旧worker，再以 `--recover-running` 恢复未结束的任务。LOCAL已实现租约与恢复；Linux沙箱仍待后续实现。

## 一次完成真实HTTP联调

保持API运行，停止其他watch worker，在工程根运行：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_http.py
```

脚本读取本地密码且不打印密码/token；真实登录、查题、提交并重试、处理一次任务、查询落库结果、验证另一学生不可读、教师可读，并提交主观答案。演示提交保留，不清空业务数据。改用其他端口时加 `--base-url http://127.0.0.1:端口`。

## PostgreSQL集成验证

在backend目录运行；测试会清空并重建专用验证库的已知表及合成数据，禁止把真实数据放进algorithm_review_test。项目库不被清空。

```powershell
$env:DB_NAME='algorithm_review_test'
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:DB_NAME
```

种子重复执行不重复插入，不覆盖原答案或自动延期。首次生成的演示作业7天截止；需要延期时在backend目录显式运行 `..\.venv\Scripts\python.exe -m scripts.seed_demo --refresh-deadlines --deadline-days 7`。不支持通过重跑种子重置已有密码。

## 协作入口

- [接口与数据流契约](docs/design/contracts/foundation-v1.md)
- [三人交接说明](docs/archive/team-handoff.md)
- [实际数据库字段](docs/design/shared/database-schema.md)、[数据来源与导入约定](docs/implementation/runbooks/data-import.md)
- [教师Issue草案](docs/issues/01-teacher.md)、[学生Issue草案](docs/issues/02-student.md)、[数据库与分析Issue草案](docs/issues/03-database-analysis.md)，尚未在线创建。
- `backend/app/teacher`、`student`、`analysis` 是各自扩展位置；`common` 和 `core` 是公共基础。
- `backend/app/db/models` 和 `backend/migrations_postgresql` 由数据库负责人协调，修改字段时新增迁移，禁止改写已应用版本。
- `data/demo` 使用合成学生及少量已核对题目，题目JSON包含教师参考资料，不能直接打包进学生前端。

## Windows 项目专用 PostgreSQL

使用上面的虚拟环境安装依赖后运行 `.\.venv\Scripts\python.exe scripts/setup_local_postgres.py`。脚本查找本机已安装的PostgreSQL，或环境变量PG_BIN指定的bin目录；在127.0.0.1:5433启动独立实例，数据保存在 `%LOCALAPPDATA%/AlgorithmReview/postgres-local/data`。不会修改已有Windows数据库服务。

创建algorithm_review和algorithm_review_test，项目角色无超级用户/建库/建角色权限，随机凭据写到已忽略的.env。管理配置仅保存在本机实例目录。重启电脑后再次运行同一命令启动，数据保留。停止本实例：

```powershell
.\.venv\Scripts\python.exe scripts/setup_local_postgres.py --stop
```

验证权限及中文读写：`.\.venv\Scripts\python.exe scripts/check_database.py`。只在验证库事务内创建临时表，回滚后不留数据。

旧MySQL用户按[迁移说明](docs/implementation/runbooks/postgresql-migration.md)切换。旧实例、原数据及原.env备份保留；旧迁移链仅作历史，不对PostgreSQL执行。

## 三人本地开发

每位成员使用自己的 `.env`、数据库和虚拟环境，通过统一模型、迁移及演示种子共享结构，不复制密码、管理凭据或数据库数据目录。仅提交 `.env.example` 供配置参考。

有现成可用PostgreSQL账号的成员可复制.env.example并填写自己的连接，项目账号需有项目库及验证库的迁移/读写权限；APP_SECRET设置至少32字符随机值。该模式无需运行专用实例脚本。前端开发CORS已允许localhost及127.0.0.1的5173端口，登录使用Authorization头。

前台运行的API与worker使用Ctrl+C停止。如果本机使用隐藏后台进程，可在工程根执行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop_dev.ps1`，脚本只匹配本工程路径与对应模块命令，不停止数据库。随后再按需停止项目PostgreSQL。

## 全量数据与隐私

队友运行`python -m scripts.import_full_data`默认使用公开脱敏快照，导入ALGO_FULL_2026课程：70编程题、50主观题、350组测试、275份参考答案/代码、217名学生、8班。DEMO_ALGO仍用于四类题的登录与提交流程演示。全量课程不会自动发布作业，名册账号PENDING且无密码，教师端已提供显式开通和作业发布入口，导入不会自动替教师执行这两步。

真实名册只供本机显式导入；不要把数据库备份、身份映射或原始xlsx上传GitHub。不同身份模式不能覆盖同一数据库的已有身份，请选定一种，详见[数据导入](docs/implementation/runbooks/data-import.md)。当前API业务格式保持兼容，迁移head为pg0004；互评和成绩分析框架继续由对应模块推进。

教师与学生的完整联调见[2026-10-25验证记录](docs/implementation/evidence/teacher/2026-10-25-student-integration.md)，先备份本机库再执行增量迁移。
