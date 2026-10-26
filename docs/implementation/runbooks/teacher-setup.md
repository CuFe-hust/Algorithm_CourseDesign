# 教师端运行与验收

## 1. 本地运行

后端要求 Python ≥3.12 和 PostgreSQL；沿用根 README 的数据库初始化、`.env`、迁移与演示种子。Windows 可使用既有 `scripts/setup_local_postgres.py`；macOS/Linux 使用自己安装的 PostgreSQL 配置 `.env.example` 中的连接参数。

在项目根目录安装锁定依赖，**本轮新增 python-multipart**，已有虚拟环境也需要重新安装：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
cd backend
../.venv/bin/python -m alembic upgrade head
../.venv/bin/python -m scripts.seed_demo
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows 将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。迁移和种子仍须在 backend 目录执行。演示密码只在本地 `.env` 的 `DEMO_PASSWORD`，不在前端或文档硬编码。

另开终端，使用 Node 22.12+（或 Vite 支持的 Node 20.19+）与 pnpm 11：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

访问 `http://127.0.0.1:5173`。开发代理将 `/api` 转发到 `127.0.0.1:8000`，前后端均只监听本机。默认开发 CORS 支持5173端口及 GET/POST/PUT；生产部署按实际域名配置，使用 HTTPS 和同源 `/api` 反向代理，SPA 未匹配路径回退到 index.html。不要将开发服务器直接作为公网服务。

## 2. 人工验收顺序

| 场景 | 操作与预期 |
|---|---|
| 登录与课程 | demo.teacher 登录；课程概览计数来自数据库；无教师身份进入权限提示 |
| 四类新题 | 分别创建四类题，填写知识点、参考答案与对应配置；保存后刷新仍可读取 |
| 冻结 | 缺答案/量表/测试或测试权重不为1时拒绝；完善后冻结；原版本只读 |
| 新版本 | 从冻结版本复制；新草稿修改并保存，旧作业与旧版本内容保持原样 |
| 编辑冲突 | 两个标签页读取同一草稿；先后保存，第二次过期写入409 |
| 归档 | 题目从在用列表移到归档；已有学生作业仍可读；恢复后重新出现 |
| 公式与代码 | 预览行内/独立 LaTeX、代码高亮；原始 HTML 不执行 |
| 名册上传 | 下载模板，替换示例，用合成名单预览；确认前数据库无新增 |
| 导入成功 | 新身份PENDING、无密码；重复确认/重复文件不生成重复用户或成员 |
| 错误与冲突 | 空值、重复学号、同名班歧义、跨课程资料变化阻止整批写入 |
| 资料更新 | 本课程已有且无其他有效课程的学生可经明确勾选更新；密码/状态不变 |
| 预览失效 | 换文件、超时、预览后数据库变化需重新预览；不得静默覆盖 |
| 权限 | 学生访问教师接口403；未关联课程404；学生题目响应无教师答案/隐藏用例 |
| 布局 | 检查桌面侧栏、手机折叠菜单、宽表横向滚动、错误及空状态 |

仅使用合成身份进行验收，真实名册和教师私密测试不提交到仓库。

## 3. 自动验证

后端测试会清空专用 `algorithm_review_test` 的已知表，禁止用于真实数据。先在独立验证库迁移，再执行：

```bash
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/python -m alembic upgrade head
../.venv/bin/python -m pytest -q
```

新增 `test_teacher_authoring.py` 与 `test_teacher_roster.py`，覆盖四题型、冻结保护、旧作业兼容、课程权限、错误回滚、更新确认、重复导入、过期/篡改/数据库变化、表头/编码/大小/行数等边界。原有46项测试继续保留。

```bash
cd frontend
pnpm test
pnpm build
pnpm format:check
```

前端17项测试验证安全渲染、严格 DTO、字符串 ID、请求与下载认证、课程切换取消和名册文件预览/确认状态。构建包含 TypeScript 类型检查；手动浏览器验收不能由构建成功替代。

保持后端运行后，可在工程根执行 `.venv/bin/python scripts/smoke_teacher_http.py`，以真实 HTTP 验证四题型创建/修改/冻结/复制/归档、过期写入、学生权限、名册预览无写入、确认和重复导入。脚本仅允许本机 HTTP 地址，从本地 `.env` 读取演示密码，不输出凭据；保留合成验收数据，新建验收题目会归档。Windows 替换 Python 路径即可。

2026-10-22 验证环境：Python 3.12.14、PostgreSQL 16.2、Node 24.19.0、pnpm 11.25.0。后端68项测试、前端17项测试、TypeScript/生产构建、代码格式检查，以及教师与原有学生真实 HTTP 联调均通过。

实际浏览器已完成：登录和会话过期重登、课程切换及取消保护、分析题复制/修改/冻结/历史追溯、编程题创建及多个测试点保存、冻结失败提示、归档与恢复、标准代码高亮、真实 CSV 文件选择/逐行预览/确认导入/学生名单回查。合成学号 `00188001`、`00188002` 的前导零完整保留，导入后为 PENDING。测试数据只写入本地隔离演示库。

390 px 断点检查中，页面宽度与内容宽度均为390 px，手机字号和收起侧栏样式生效；触屏真机操作留给团队最终验收，不把开发浏览器的尺寸模拟等同于真机验证。

## 4. 本轮限制与后续事项

- 支持手工录题及 CSV 名册上传；不提供 Word/PDF 自动抽题或 Excel 原生格式解析。Excel 请另存 CSV UTF-8。
- 不提供账户激活/密码发放、作业发布、互评评分、成绩发布或真实代码执行。这些必须按共享契约由后续任务接入。
- 配置快照只追加，当前不自动回收；不新增审计表。需要完整操作审计时与数据库负责人协调迁移。
- 参考答案和测试配置由教师确认质量；配置齐全不代表答案或程序已自动验证正确。
- 当前页面仅实现教师导航；学生负责人接入路由后，应将非教师登录的临时提示替换为实际主页。

## 5. 实测界面

截图来自实际 Vue 页面与本地 PostgreSQL 合成数据，包含 [课程概览](../evidence/screenshots/teacher/01-course-overview.jpg)、[名册预览](../evidence/screenshots/teacher/02-student-import-preview.jpg) 和 [标准代码预览](../evidence/screenshots/teacher/03-reference-code.jpg)。截图与数据说明见 [截图索引](../evidence/screenshots/teacher/README.md)。

## 6. 2026-10-25：学生端联调增量

前述1～5节保留首轮（2026-10-22）的运行与验收记录；其“不提供账户激活/作业发布”限制已由本节更新，当前实现与边界以 [最新架构](../../design/teacher/architecture.md) 和 [本轮证据](../evidence/teacher/2026-10-25-student-integration.md) 为准。

1. 切换最新功能分支，先备份自己的本机PostgreSQL库。学生端head为pg0003，本轮head为pg0004；旧库在backend目录执行 `../.venv/bin/python -m alembic upgrade head`，不要改写旧迁移。Windows沿用相应Scripts路径。
2. 重启API和前端。仅发题时使用教师“只读发布”；受控本机开发要验证真实执行，API与执行器均设置 `JUDGE_EXECUTION_MODE=LOCAL`，另开终端运行 `../.venv/bin/python -m scripts.run_judge --mode LOCAL --loop`。生产隔离和安全边界见 [学生运行说明](student-setup.md)。
3. 登录 → 显式选教师课程 → CSV导入合成学生 → 学生名单开通 → 本次页面分别发放初始密码或下载清单。学生首次改密后才可进入课程。再次导入不会重置密码；重置后旧密码/会话失效，需再次改密。
4. 题库冻结完整题目，配置合理总预算；作业管理创建草稿、选固定版本、分值和权重、按班或指定学生选名单，保存后发布。只读发布学生能看不能交；开放前检查节点语言和预算。发布后名单/题目不可改，只能管理截止和开关。
5. 在学生名单点提交进度，查看共享采用候选、历史和只读代码/评测；Mock与未解决任务不当成绩。互评与正式成绩尚未交付。

默认节点总预算上限300000 ms，环境变量 `JUDGE_MAX_TOTAL_BUDGET_MS` 可调整，最大3600000。最低预算随CPU限额与测试数变化；历史NULL配置明确推导，不回写旧快照。Java需实际JDK，只有系统启动器不算支持。

工程根可执行 `.venv/bin/python scripts/smoke_teacher_student_http.py` 完成真实HTTP闭环；只创建合成学生与关闭的验收作业，不打印凭据。后端pytest仍只使用algorithm_review_test，前端运行 `pnpm test`、`pnpm build`、`pnpm format:check`。本轮准确结果见上述证据文档。

API与执行器必须使用相同的评测模式、预算上限和工具链配置；安装或更换工具链后重启两者，以重新检测能力。
