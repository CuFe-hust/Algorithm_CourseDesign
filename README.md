# 算法课程评审平台

已实现共享后端最小链路：登录、读取作业题目、版本提交、模拟任务、结果查询与教师提交列表。包含21张业务表、迁移、合成账号和四类演示题，可供队友对接。完整前端、真实代码执行、互评和正式成绩发布尚未实现。

## 三人从这里开始

**[MAIN.md：项目主文档、分工与开发顺序](MAIN.md)**。本main是已经跑通最小链路的协作底座，你可以直接基于它推进分析流程，两位队友分别完成教师和学生模块。

| 负责人 | 任务正文 | 先做什么 |
|---|---|---|
| T：教师队友 | [教师Issue](docs/issues/01-teacher.md) | T00统一Vue骨架，然后CSV、题库和作业写入 |
| S：学生队友 | [学生Issue](docs/issues/02-student.md) | 当前真实作答页面，接着历史，再接A01互评 |
| A：你 | [分析Issue](docs/issues/03-database-analysis.md) | 在底座上补互评契约/数据/基础流程，再聚合/检测/发布 |

阅读顺序：本README启动 → MAIN和自己的Issue → [数据库与归属](docs/DATABASE.md) → [信息流](docs/DATA_FLOWS.md) → [当前API格式](docs/API.md)。规划接口另见[下一阶段提案](docs/contracts/next-phase.md)，未标记为已实现的接口不能当作可调用。

推送与分支/PR方式见[Git协作](docs/COLLABORATION.md)。仓库有3个GitHub Issue模板，推送后可直接选用，负责人待你填写；当前未在线创建Issue，也未设置远程地址。

开发资料包含70道编程题、主观题原Word和任务书，见[data/source](data/source/README.md)；仅4道演示题实际入库，真实学生名册不打包。前端位置和公共骨架分工见[frontend约定](frontend/README.md)，当前没有可启动的Vue应用。

## 完整启动顺序

在工程根目录使用PowerShell。本机实际验证Python 3.14.5、MySQL 9.4.0，建议队友使用同版本；依赖锁文件包含运行与测试依赖。需要预先安装Python和MySQL程序。

```powershell
python scripts/setup_local_mysql.py
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.seed_demo
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 [接口文档](http://127.0.0.1:8000/docs)。演示教师为 `demo.teacher`，演示学生为 `demo.student01`～`demo.student06`，共同演示密码随机生成在工程根 `.env` 的 `DEMO_PASSWORD`，在本地编辑器查看，勿发到公开Issue。登录接口返回access_token，点击Authorize填入后调用业务接口。

另开终端进入backend目录，运行模拟任务消费：

```powershell
..\.venv\Scripts\python.exe -m scripts.process_mock_jobs --watch
```

本轮只运行单个模拟worker，源码不会被执行。结果固定明确标记 `MOCK_ACCEPTED/is_mock=true`，时间和内存为空，不代表程序正确或正式成绩。主观答案保存后为AWAITING_REVIEW。

发生worker异常退出后，先停止全部旧worker，再以 `--recover-running` 恢复未结束的任务。正式执行需要后续实现沙箱与任务租约。

## 一次完成真实HTTP联调

保持API运行，停止其他watch worker，在工程根运行：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_http.py
```

脚本读取本地密码且不打印密码/token；真实登录、查题、提交并重试、处理一次任务、查询落库结果、验证另一学生不可读、教师可读，并提交主观答案。演示提交保留，不清空业务数据。改用其他端口时加 `--base-url http://127.0.0.1:端口`。

## MySQL集成验证

在backend目录运行；测试会清空并重建专用验证库的已知表及合成数据，禁止把真实数据放进algorithm_review_test。项目库不被清空。

```powershell
$env:DB_NAME='algorithm_review_test'
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:DB_NAME
```

种子重复执行不重复插入，不覆盖原答案或自动延期。首次生成的演示作业7天截止；需要延期时在backend目录显式运行 `..\.venv\Scripts\python.exe -m scripts.seed_demo --refresh-deadlines --deadline-days 7`。不支持通过重跑种子重置已有密码。

## 协作入口

- [接口与数据流契约](docs/contracts/foundation-v1.md)
- [三人交接说明](docs/team-handoff.md)
- [实际数据库字段](docs/database-schema.md)、[数据来源与导入约定](docs/data-import.md)
- [教师Issue草案](docs/issues/01-teacher.md)、[学生Issue草案](docs/issues/02-student.md)、[数据库与分析Issue草案](docs/issues/03-database-analysis.md)，尚未在线创建。
- `backend/app/teacher`、`student`、`analysis` 是各自扩展位置；`common` 和 `core` 是公共基础。
- `backend/app/db/models` 和 `backend/migrations` 由数据库负责人协调，修改字段时新增迁移，禁止改写已应用版本。
- `data/demo` 使用合成学生及少量已核对题目，题目JSON包含教师参考资料，不能直接打包进学生前端。

## Windows 项目专用 MySQL

电脑已安装 MySQL Server 时运行：

```powershell
python scripts/setup_local_mysql.py
```

脚本复用已有 MySQL 安装中的程序，在本机 127.0.0.1:3307 启动独立实例，不修改既有 Windows MySQL 服务。数据位于本机用户的 `%LOCALAPPDATA%/AlgorithmReview/mysql-local/data`，不会放进同步或 Git 目录。

创建项目库 `algorithm_review` 和独立验证库 `algorithm_review_test`。随机生成项目账号密码，写入已忽略的 `.env`；管理凭据仅保存在本机实例状态目录中。脚本不会输出密码，也不会要求现有管理员密码。

验证项目账号、数据库访问权限及中文读写：

```powershell
python scripts/check_database.py
```

此检查只在独立验证库创建临时表并在验证后删除；业务验证使用上文的pytest和HTTP脚本。

若程序安装在其他位置，先设置 `MYSQL_BIN` 为安装的 bin 目录。脚本在端口被其他实例占用或出现未知数据目录时拒绝初始化；不会清空已有数据。

重启电脑后再次运行同一命令启动实例，已有数据保留。停止本实例：

```powershell
python scripts/setup_local_mysql.py --stop
```

## 三人本地开发

每位成员使用自己的 `.env`、数据库和虚拟环境，通过统一模型、迁移及演示种子共享结构，不复制密码、管理凭据或数据库数据目录。仅提交 `.env.example` 供配置参考。

有现成可用MySQL账号的成员可复制.env.example并填写自己的连接，项目账号需有项目库及验证库的迁移/读写权限；APP_SECRET设置至少32字符随机值。该模式无需运行专用实例脚本。前端开发CORS已允许localhost及127.0.0.1的5173端口，登录使用Authorization头。

前台运行的API与worker使用Ctrl+C停止。如果本机使用隐藏后台进程，可在工程根执行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop_dev.ps1`，脚本只匹配本工程路径与对应模块命令，不停止数据库。随后再按需停止项目MySQL。
