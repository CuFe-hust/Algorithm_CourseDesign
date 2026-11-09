# 全站 UI 优化与回归记录

**日期**　2026-11-09 · **基线**　`837fa38` · **技术栈**　Vue 3 / TypeScript / Vite / pnpm
**范围**　中文排版、共享布局与典型页面、表单状态、同名题归属、互评预览易读性。
**原则**　只改前端展示与可访问性，不改角色、路由、评测、互评、评分与 B0/D1 业务契约；所有运行数据均为合成 fixture。

## 1. 证据与限制

| 项目 | 结果 |
|---|---|
| 代码与构建 | 本克隆实际修改、`corepack pnpm@11.25.0 test`、`corepack pnpm@11.25.0 build` 通过 |
| 页面验收 | 用无头 Edge + 合成 mock API 渲染 4 个代表页，1440 / 768 / 720 / 390 宽度截图并测量 |
| 改前对照 | 用 `837fa38` 的干净 `git worktree` 启动同一套 mock API，保存改前截图 |
| 设计工具 | `superdesign` / SDP MCP 在本会话不可用（`plugin:sdpm:sdpm` 连接关闭，无画布授权）；按计划改用现有 Vue 组件与源码 CSS 完成，不引入新设计依赖 |
| 真实服务 | 服务器首轮使用模拟接口。本机交付复核使用真实后端和合成课程数据库，见下方复核记录 |
| 200% 缩放 | 以 720 CSS px 宽度近似 1440 物理像素的 200% 缩放；未操作真实浏览器缩放菜单 |
| 屏幕阅读器 | 未用 NVDA/JAWS 实测；完成了语义标记与键盘焦点检查，不声称完整 AT 验收 |

## 2. 页面盘点与优先级

路由来自 `frontend/src/app/router.ts`。按角色归类：

| 角色 | 页面 | 本轮处理 | 验收 |
|---|---|---|---|
| 公共 | 登录、选课、改密、无权限、404 | 中文眉题、字体与焦点基线 | 源码审阅 |
| 学生 | 课程作业、作业详情、作答、提交历史、提交详情、我的互评、互评任务、学习报告、个人章节表现 | 排版、共享布局、表单状态、同名题归属、互评预览 | 截图：提交详情、互评任务、个人章节表现 |
| 教师 | 概览、题库、题目编辑、作业、作业编辑、学生名单、导入、学生进度、互评轮次、互评详情、逐题结果、分析中心、相似检测、复杂度 | 中文眉题、共享布局、互评预览摘要、表单状态基线 | 截图：互评预览；其余源码审阅 |

**改前主要问题（按优先级）：**

1. **高：正文/表格偏小。** 眉题 11px、徽标 11px、表格 13px、侧栏 13px；密集教学页面阅读成本高。
2. **高：互评预览只有一行“分配：已完成”与原始 JSON。** 教师无法快速看到作品数、任务数、每人负载和可行性。
3. **高：提交详情只显示“第 2 版”。** 同名题跨作业时，学生无法确认这条提交属于哪次作业、哪道题。
4. **中：表单错误只有页首一句。** 互评评分缺失时，学生要自己找哪个分项没填。
5. **中：装饰性英文眉题与重复标题。** `VERSION`、`ASSIGNMENT`、`COURSE OVERVIEW` 等与中文标题重复。
6. **中：低对比辅助文字。** `#718096` 的提示文字在白色上约 4.02:1，低于 4.5:1。
7. **低：键盘跳转与当前页语义。** 无 skip link；侧栏没有显式 `aria-current`。

## 3. 视觉规范与共享基础

### 3.1 字体与字号

- 中文界面字体优先：`Noto Sans SC` → `Source Han Sans SC` → `PingFang SC` → `Microsoft YaHei` → `Segoe UI` → `system-ui`。
- 代码/数据：`Cascadia Mono` → `JetBrains Mono` → `SFMono-Regular` → `Consolas` → `Microsoft YaHei`。
- 字号下限：正文 15px；表格与表单主要内容 14px；辅助说明/眉题 13px/12px；代码 13px。
- 行高：正文 1.65；表格 1.7；提示 1.7。
- 标题层级保持 `h1` clamp(25–31px)、`h2` 16–18px、`h3` 15px，避免在高密度页面里用过大的标题挤压内容。

### 3.2 颜色与对比

保留原有蓝色主色与浅灰背景，只加深辅助文字和状态徽标：

| 用途 | 颜色 | 背景 | 对比度 |
|---|---|---|---:|
| 正文 | `#243044` | `#f5f6f8` | 12.28:1 |
| 眉题/辅助 | `#5b6b82` | `#ffffff` | 5.43:1 |
| 眉题/辅助 | `#5b6b82` | `#f5f6f8` | 5.02:1 |
| 灰色徽标 | `#596a86` | `#f0f2f6` | 4.89:1 |
| 琥珀色徽标 | `#7a5510` | `#fff6e6` | 6.25:1 |
| 绿色徽标 | `#1f6b51` | `#eaf7f0` | 5.81:1 |
| 红色徽标 | `#9f2a2a` | `#fff0f0` | 6.68:1 |
| 字段错误 | `#a51c14` | `#fffafa` | 7.31:1 |

对比度按 WCAG 相对亮度公式计算；状态同时保留文本（“通过/未通过/待评审/无有效证据”），不依赖颜色单独传达。

### 3.3 布局与交互

- 学生/教师 Layout 增加“跳到主要内容”skip link；`main` 设 `tabindex="-1"`，键盘可直达。
- 侧栏当前页显式 `aria-current="page"`；移动端菜单增加 `aria-controls` 与 `aria-expanded`。
- 焦点样式保持 3px 可见轮廓；确认弹窗已有焦点陷阱与 Escape 关闭。
- 宽表继续放在 `.table-scroll` / `.table-wrap` / `.ability-table-scroll` 内横向滚动，页面级不横向溢出。
- 空态、加载、失败、成功、禁用均沿用既有文案与组件；新增 `.field-error`、`.form-status`、`[aria-invalid="true"]` 样式。

### 3.4 文案

- 20 处英文眉题与 2 处 `STUDENT`/`TEACHER` 装饰标签改为中文；重复标题改为有信息量的上下文：
  - `COURSE OVERVIEW` → 教学准备
  - `ASSIGNMENTS` → 教学组织
  - `QUESTION LIBRARY` → 题目资源
  - `STUDENT ROSTER` → 课程成员
  - `COMPLEXITY` → 运行证据
  - `CODE SIMILARITY` → 查重证据
  - `COURSE HOME` → 学习任务
  - `IMPORT STUDENTS` → 名单维护
  - `VERSION` → 提交版本
  - `MY SUBMISSIONS` → 提交记录
  - `PEER REVIEW` → 学生互评
  - `SELECT COURSE` → 课程工作区
  - `ACCOUNT` → 账户设置
  - `WELCOME BACK` → 账户登录
- 学生提交历史的筛选明确写为“全部提交状态”，并提示“筛选的是提交状态；评测结论在列表状态列和版本详情中查看”。
- 学习报告中的“模型尚未全部接入”改为“知识掌握待接入”，避免与已接入的 B0/D1 冲突。

## 4. 典型页面改动

### 4.1 学生提交详情：同名题归属

- 读取提交所属作业的详情（只读），在标题区显示：
  - 题目名称作为主标题；
  - “所属作业：第一次作业 · 贪心与分治”；
  - “第 2 版 · 提交时间 · 语言 · 只读”。
- 改前只显示“第 2 版”，同名题跨作业时无法确认归属。
- 归属读取失败不阻塞提交正文与评测结果，页面仍可读。

### 4.2 学生互评任务：表单状态

- 评分输入与评语增加逐字段错误：
  - 空分：“请输入 0～30 范围内、最多两位小数的得分。”
  - 空评语：“请写出具体的评审意见。”
- 字段设 `aria-invalid` / `aria-describedby`；错误文本为 13px 红色，对比度 7.31:1。
- 表单加 `novalidate`，由页面统一给出可读错误，不再依赖浏览器原生气泡。
- 顶部仍保留一条错误摘要，说明第一个需要修改的分项。
- 实测空提交：改前 0 个字段错误、0 个 `aria-invalid`；改后 4 个字段错误、4 个 `aria-invalid`（3 个评分 + 1 个评语）。

### 4.3 教师互评预览：可扫描摘要

- “分配状态”下方新增摘要卡：
  - 待评作品数、可用评审人数、计划任务数、每人任务范围、平均任务；
  - 可行性文案：“分配可行，确认后将按此负载开放互评。”或“分配不可行，不会创建部分任务。”；
  - 未满足约束转成可读文本（如“没有可分配的作品”“总容量或禁止关系导致分配不可行”）。
- 原始 JSON 与每人任务明细收进 `<details>`，教师需要时再展开。
- 原始任务表头改为“任务编号 / 评价编号”“作品匿名代号”“评审学生编号”，不再直接写“任务 / 评价ID”。
- 合成 fixture 实测：6 份待评作品、4 位评审人、10 个计划任务、每人 2–3 个、平均 2.5；与 `load_metrics` 求和一致。

### 4.4 个人章节表现

- 雷达轴标签 12px、刻度 11px、证据表 14px、表内辅助 13px、章节代码 12px。
- 保持 B0/D1 双轨、缺失留空、未布置隐藏、低证据提示；不改模型或输出语义。
- 390px 宽度下雷达与证据表仍在页面内，无页面级横向溢出；证据表在独立容器横向滚动。

### 4.5 共享 Layout 与其它页面

- 学生/教师侧栏、顶栏、页脚、卡片、表格、按钮、徽标、提示、Markdown/代码块统一到同一字号与颜色基线。
- 课时/作业/题库/学生/互评/逐题/分析/相似/复杂度页面完成中文眉题替换与字号继承；未逐页截图者列入第 6 节覆盖边界。

## 5. 验收记录

### 5.1 自动化

| 命令 | 结果 |
|---|---|
| `cd frontend && corepack pnpm@11.25.0 test` | 26 个测试文件、130 个测试全部通过 |
| `cd frontend && corepack pnpm@11.25.0 build` | `vue-tsc --noEmit` 与 Vite 构建通过 |
| `git diff --check` | 无空白错误（仅提示 `Ability.vue` 的 CRLF 将在下次 Git 触碰时转 LF） |

新增/更新的测试断言：

- `Results.test.ts`：状态徽标改为“知识掌握待接入”。
- `StudentTask.test.ts`：空提交后存在 `aria-invalid`、字段错误文本，且不发请求；随后仍能正常提交。

### 5.2 无头 Edge 实测

环境：Microsoft Edge（本机安装版），Playwright Core 1.55.0，合成 mock API，Vite dev server。
代表页：学生提交详情、学生互评任务、学生个人章节表现（D1）、教师互评预览。

| 页面 | 1440 | 768 | 720（200% 近似） | 390 | pageerror |
|---|---:|---:|---:|---:|---|
| 学生提交详情 | 无页面级横向溢出 | 无 | 无 | 无 | 0 |
| 学生互评任务 | 无 | 无 | 无 | 无 | 0 |
| 学生个人章节表现 | 无 | 无 | 无 | 无 | 0 |
| 教师互评预览 | 无 | 无 | 无 | 无 | 0 |

测量口径：`document.documentElement.scrollWidth <= window.innerWidth + 1`；同时扫描 `overflow-x: visible` 且 `scrollWidth > clientWidth + 1` 的元素，结果为空。宽表本身的横向滚动发生在 `.table-wrap` 内，不计为页面溢出。

### 5.3 改前/改后字号

| 指标 | 改前 | 改后 |
|---|---:|---:|
| 正文 | 15px | 15px |
| 眉题 | 11px（教师页 14px） | 12px |
| 侧栏导航 | 13px | 14px |
| 表格内容 | 13px | 14px |
| 徽标 | 11px | 12px |
| 提示 | 13px | 13px（颜色加深到 5.02:1） |
| skip link | 无 | 有 |
| 学生页 `aria-current` | 0 | 1 |
| 空互评提交字段错误 | 0 | 4 |

### 5.4 截图

改前 13 张、改后 17 张，共 30 张（改后含 720px 宽度与表单错误视口截图）。目录：

- `docs/reports/ui-review/screenshots/before/`
- `docs/reports/ui-review/screenshots/after/`

代表图：

- 学生提交详情：`after/student-submission-1440.png` 对比 `before/student-submission-1440.png`
- 教师互评预览：`after/teacher-review-preview-1440.png` 对比 `before/teacher-review-preview-1440.png`
- 学生互评错误态：`after/student-review-form-errors-1440.png`
- 学生个人章节表现窄屏：`after/student-ability-390.png`

## 6. 覆盖边界与剩余问题

1. **联调覆盖边界。** 首轮截图使用模拟接口。本机复核已验证真实接口上的教师和学生关键页面。该轮浏览器检查读取已有结果，未通过 UI 重做提交、判题、全部互评及封存。
2. **未做完整页面截图。** 登录/选课/改密、课程作业、作业详情、作答编辑器、提交历史、教师概览/题库/题目编辑/作业编辑/学生名单/导入/学生进度/互评轮次/逐题结果/分析中心/相似/复杂度只做了源码审阅与共享样式继承；这些页面的个别局部布局仍需在真实数据下复核。
3. **200% 缩放为近似。** 720 CSS px 覆盖了等效宽度，但没有操作浏览器缩放菜单；真实缩放下的字体度量可能略有差异。
4. **未做屏幕阅读器实测。** 已加 skip link、`aria-current`、`aria-expanded`、`aria-invalid`、`aria-describedby` 与 `role="status"`；未用 NVDA/JAWS 走完整流程。
5. **色彩视觉未模拟。** 状态均有文本，但未做色盲模拟；对比度按 WCAG 公式计算。
6. **教师页 `aria-current` 计数为 2。** 侧栏“互评与复核”和页内“第 1 轮”都标为当前页；语义上可接受，若要求唯一当前页，可把页内轮次改为 `aria-current="true"`。
7. **移动端宽表需要横向滚动。** 这是有意保留的独立容器行为；未额外加“左右滑动”提示，避免增加装饰性文案。
8. **设计工具限制。** 本会话 SDP MCP 连接关闭，未使用 superdesign 画布；全部改动在现有 Vue 组件与 CSS 中完成，未引入新依赖到产品包（Playwright 仅用于 `docs/reports/ui-review/` 的离线验收）。

## 7. 复现方式

```powershell
# 1) 安装前端依赖
cd frontend
corepack pnpm@11.25.0 install --frozen-lockfile

# 2) 测试与构建（本机未直接安装 pnpm，使用 corepack）
corepack pnpm@11.25.0 test
corepack pnpm@11.25.0 build

# 3) 合成 API（仅 UI 验收）
cd ../docs/reports/ui-review
npm install
node mock-api.mjs 8000

# 4) 另开终端启动当前前端
cd ../../../frontend
corepack pnpm@11.25.0 dev

# 5) 另开终端截图（需要本机 Edge）
cd ../docs/reports/ui-review
node capture.mjs after http://127.0.0.1:5173
```

改前对照需要 `837fa38` 的干净 worktree，在 `frontend` 安装依赖后 `corepack pnpm@11.25.0 dev --port 5174`，再执行
`node capture.mjs before http://127.0.0.1:5174`。截图与 `metrics.json` 会写入 `screenshots/<label>/`。

## 8. 文件索引

| 文件 | 作用 |
|---|---|
| `frontend/src/workspace.css` | 中文排版、字号下限、对比度、skip link、表单状态、表格与共享组件 |
| `frontend/src/features/student/StudentLayout.vue` | 学生 skip link、`aria-current`、移动菜单语义 |
| `frontend/src/features/teacher/TeacherLayout.vue` | 教师 skip link、`aria-current`、移动菜单语义 |
| `frontend/src/features/student/SubmissionDetail.vue` | 同名题归属：题目 + 所属作业 |
| `frontend/src/features/student/SubmissionHistory.vue` | 提交状态筛选文案 |
| `frontend/src/features/analytics/peer-review/StudentTask.vue` | 互评逐字段错误与 `aria-invalid` |
| `frontend/src/features/analytics/peer-review/StudentTasks.vue` | 互评任务摘要与状态徽标 |
| `frontend/src/features/analytics/peer-review/TeacherRound.vue` | 分配预览摘要、负载明细、原始 JSON 折叠 |
| `frontend/src/features/analytics/peer-review/review.css` | 互评摘要卡、任务卡、移动端两列 |
| `frontend/src/features/student/Ability.vue` | 章节表现字号与证据表可读性 |
| `docs/reports/ui-review/mock-api.mjs` | 合成 API fixture |
| `docs/reports/ui-review/capture.mjs` | Edge 截图与布局/字号测量 |
| `docs/reports/ui-review/screenshots/` | 改前/改后截图与 `metrics.json` |

**结论：** 本轮把“读得清、找得到操作、看得懂结果”落到共享排版、共享布局、表单状态、同名题归属和互评预览五处；业务契约未改。真实后端与更多页面的视觉复核仍是后续工作。

## 本机交付复核

通过真实登录进入本机 WSL 后端和合成课程数据库，使用 Edge 检查 10 个页面。记录覆盖教师逐题结果、390px 教师作业列表、学生提交历史和版本归属、B0、390px D1、学习报告、互评任务及已提交评价，以及无评分证据的学生。10 个场景均无页面级横向溢出和浏览器脚本异常。此前的模拟接口截图仍保留用于改前改后对照。

- [验收记录](ui-review/screenshots/real-backend/results.json)
- [教师逐题结果](ui-review/screenshots/real-backend/teacher-results.png)
- [390px 学生 D1](ui-review/screenshots/real-backend/student-d1-mobile.png)
- [已提交互评](ui-review/screenshots/real-backend/student-review-readonly.png)

在本机重新执行前端测试与生产构建。26 个测试文件共 130 个测试通过，Prettier 格式检查、Vue 类型检查及 Vite 构建通过。
后端相关回归覆盖 B0、D1、逐题结果及课程接入，共 64 项通过。后端全量首跑为 489 通过、3 跳过、7 失败。其中 6 项在判题模式切回测试所用的 MOCK 后重跑通过。剩余的 C 线性求和轨迹用例在未修改的 main 基线 837fa38 上同样以 RUNTIME_ERROR 失败。本轮 UI 与报告验收保留这项基线问题的记录。