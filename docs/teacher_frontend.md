# 教师端前端架构

## 1. 技术与目录

Vue 3 Composition API、TypeScript、Vue Router、Vite；图标使用 Lucide；Markdown 使用 markdown-it，公式使用 KaTeX，代码使用 highlight.js，输出经 DOMPurify 清洗。依赖版本由 `frontend/pnpm-lock.yaml` 固定。

```text
frontend/
├── index.html / package.json / pnpm-lock.yaml
├── vite.config.ts                  # 5173，/api 代理至本机 8000
└── src/
    ├── main.ts / App.vue / styles.css
    ├── app/router.ts               # 公共路由和教师课程准入
    ├── shared/
    │   ├── api.ts                  # 请求、Bearer、统一错误、query
    │   ├── session.ts              # 登录、课程列表、课程选择、退出
    │   ├── Login.vue / Access.vue / NotFound.vue
    │   ├── Pagination.vue
    │   ├── confirm.ts / ConfirmDialog.vue
    │   └── markdown.ts / MarkdownPreview.vue / CodePreview.vue
    └── features/
        ├── teacher/
        │   ├── TeacherLayout.vue   # 侧栏、课程切换、账户与内容区
        │   ├── Overview.vue        # 真实数据库计数与快捷入口
        │   ├── Problems.vue        # 搜索、题型、归档状态、分页
        │   ├── ProblemEditor.vue   # 内容、答案、配置和版本操作
        │   ├── Students.vue        # 学生与班级筛选
        │   ├── StudentImport.vue   # 文件→预览→确认→结果
        │   └── types.ts            # 教师 DTO、类型与写入投影
        ├── student/README.md       # 学生负责人接入位置
        └── analytics/README.md     # 互评/分析负责人接入位置
```

## 2. 页面与操作

| 路由 | 页面职责 |
|---|---|
| `/login` | 调用共享登录接口，不硬编码账号密码 |
| `/teacher` | 在用题目、草稿、学生、班级计数和题型分布 |
| `/teacher/problems` | 教师题库，不在静态资源中打包参考库 |
| `/teacher/problems/new` | 选择题型、固定题号、保存首个草稿 |
| `/teacher/problems/:id` | 草稿编辑；冻结后只读；新建版本；历史切换与归档 |
| `/teacher/students` | 课程学生名单、状态、班级、查询分页 |
| `/teacher/students/import` | 下载模板、上传 CSV、逐行预览和确认入库 |
| `/access` | 当前无教师课程的账户提示，等待组员接入学生主页 |

题目编辑分为“题目内容 / 参考答案 / 测试配置或评分量表”三个标签页。右侧维护难度、知识点、来源与历史版本。编程资源单位明确为 ms / KiB；权重和分值保持字符串。

## 3. 状态、请求与安全

- 会话 token 与用户摘要放在当前标签页 `sessionStorage`，关闭标签页后清理；所有业务请求通过 `Authorization` 传递。生产部署须使用 HTTPS。
- 登录后从 `/courses` 获取角色。教师导航只展示有教师身份的课程，后端仍逐次验证权限。
- 当前课程 ID 持久化在当前会话；切换课程时先经过未保存修改提示，再切换数据。页面以课程 ID 与路径作为 key，防止复用旧课程编辑状态。
- 题库、学生列表使用请求序号，丢弃较早的异步响应。搜索、分页、加载、失败、空列表均有明确状态。
- 401 清除会话并回到登录；404 等错误正常显示，不能当作成功空列表。错误展示 `request_id` 便于定位。
- 模板下载复用请求客户端的认证和错误处理；字段校验和冻结要求转为中文提示，不把原始校验对象直接呈现给教师。
- BIGINT ID 全程使用字符串；保存前通过 `editable()` 显式提取字段，避免把服务端元数据提交给严格 DTO。
- 页面确认对话框统一由 `ConfirmDialog.vue` 提供，支持取消、Escape 和焦点约束。草稿提交携带原始 `updated_at`，409 提示重新读取；未保存修改离开页面、切换版本和关闭页面时提醒。冻结和归档前有明确确认。
- Markdown 禁用原始 HTML，KaTeX `trust=false`，限制展开次数，清洗最终 HTML/MathML。代码输入作为文本处理，不执行学生或教师代码。
- 标准代码用独立 `CodePreview` 保留原始缩进和文本，即使代码包含 Markdown 围栏也不会被当作题目内容重新解析。Python 3 使用 Python 高亮规则。
- 改选文件会清空预览、确认勾选与导入结果；确认始终上传同一 File 和签名预览令牌。数据库变化时重新预览。

## 4. 学生端和互评端如何接入

在 `app/router.ts` 注册对应模块路由；直接复用 `shared/api.ts`、`session.ts`，读取自己的课程角色。将 `Login.vue` 中非教师用户进入 `/access` 的临时逻辑替换为实际学生入口，并处理同一用户跨课程多角色的选择。

教师布局仅负责教师导航，其他模块可建立自己的布局。不得复制整套 Vite 工程或另写登录协议；学生题目必须调用原有学生安全接口，禁止复用教师版本详情 DTO。

## 5. 验证

`pnpm test` 的17项测试覆盖字符串 ID、Bearer、multipart 边界、401、下载认证、中文校验、安全 Markdown/代码、严格保存投影、取消课程切换、导入确认和更换文件后的预览失效。`pnpm build` 同时进行 TypeScript 检查与生产构建。实际浏览器操作验收见 [teacher_setup.md](teacher_setup.md)。
