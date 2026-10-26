# 统一前端工程

已建立 Vue 3 / TypeScript / Vite 应用，提供统一登录与选课、教师题库/CSV/账号管理/作业发布及学生作答/历史/LOCAL评测界面。三个模块使用唯一 frontend 工程。

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Node 22.12+（或兼容的20.19+）、pnpm 11。开发服务为 `http://127.0.0.1:5173`，`/api` 代理到本机8000后端。先按根README配置数据库、迁移和演示账户。密码仅在本地 `.env`。

- [教师前端结构](../docs/design/teacher/frontend.md)
- [教师完整架构与边界](../docs/design/teacher/architecture.md)
- [启动与验收](../docs/implementation/runbooks/teacher-setup.md)
- [教师API](../docs/design/teacher/api.md)

学生与互评模块分别接入 `src/features/student`、`analytics`，路由注册在 `src/app/router.ts`；共享请求位于 `src/shared/api.ts`，会话和课程位于 `session.ts`。教师和学生均在统一选课后进入对应工作区，互评/分析页面仍待接入。不要创建第二套前端或登录协议。

ID全程字符串，分值/权重保留十进制字符串，时间按UTC接收后本地化。token仅通过Authorization传递，保存在当前标签页sessionStorage；401清理身份并重登。禁止把教师参考库放进public或学生静态资源。

```bash
pnpm test
pnpm build
pnpm format:check
```
