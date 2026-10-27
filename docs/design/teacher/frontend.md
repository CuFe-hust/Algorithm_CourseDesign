# 教师端前端架构

更新：2026-10-25。Vue 3 Composition API、TypeScript、Vue Router、Vite；复用学生端共享认证、显式课程选择、真实操作续期与请求代次保护。Markdown/LaTeX/代码渲染仍使用markdown-it、KaTeX、highlight.js和DOMPurify。

## 1. 结构与页面

```text
frontend/src/
├── app/router.ts                    统一路由、角色准入、刷新后接入activity
├── shared/
│   ├── api.ts / session.ts          Bearer、认证代次、401、会话和当前课程
│   ├── Login.vue / CourseSelect.vue / ChangePassword.vue
│   ├── activity.ts / navigation.ts 真实交互续期、同课程返回地址
│   └── ConfirmDialog.vue / Pagination.vue / MarkdownPreview.vue / CodePreview.vue
└── features/teacher/
    ├── TeacherLayout.vue            侧栏、教师课程切换、工作区切换与退出
    ├── Overview.vue                 课程统计
    ├── Problems.vue / ProblemEditor.vue   题库、冻结版本与配置
    ├── Students.vue                 名单、账号开通/重置、一次性凭据发放
    ├── StudentImport.vue            CSV文件、只读预览、确认写入
    ├── Assignments.vue              作业列表与分页
    ├── AssignmentEditor.vue         草稿、固定选题/名单、发布、截止与开关
    ├── StudentProgress.vue          共享采用候选、历史与只读提交快照
    └── types.ts / assignmentTypes.ts 严格写入投影、字符串ID、权重与日期
```

| 路由 | 页面职责 |
|---|---|
| `/login`、`/courses`、`/account/change-password` | 全平台统一认证与显式选课 |
| `/teacher` | 题目、草稿、学生、班级和题型计数 |
| `/teacher/problems`、`/new`、`/:id` | 搜索归档、创建编辑、内容/答案/配置、历史冻结与派生 |
| `/teacher/students` | 名单分页、班级/关键词筛选、单人或当前页批量开通/重置 |
| `/teacher/students/import` | CSV模板、文件选择、逐行预览、确认和名单回查 |
| `/teacher/assignments`、`/new`、`/:id` | 作业列表、选题、分值与权重、应交名单、发布与截止开关 |
| `/teacher/students/:studentId/progress` | 该学生的当前评测环境、采用版本、历史及只读答案 |

## 2. 状态和写入

- ID始终为字符串，不转Number。分值与权重传十进制字符串；`editable()`及`assignmentPayload()`显式提取写字段，服务端元数据不回传严格DTO。
- 题目、作业及账号操作携带 `expected_updated_at`；409保留输入并要求重新读取。页面以课程ID和路径作为key，不复用其他课程编辑状态。
- 作业从分页冻结版本候选中选题，固定版本和测试/量表ID。各题独立设置满分与主观评审人数，不设置跨题权重。
- 名单支持班级、学号/姓名筛选、当前页选择、指定学生，以及经确认加入全部筛选结果（最多2000人）；选择不随翻页丢失。发布后题目、分值、名单只读。
- 截止用datetime-local输入，发送前转为带Z的UTC；返回UTC在界面本地显示。默认只读发布，开放提交必须显式选择；未保存内容不可发布。
- 服务端字段约束和冻结需求转换为可读中文，错误显示请求编号；加载、空数据、失败和成功均有明确状态。作业查题/查人使用请求序号，迟到响应不替换新筛选。

## 3. 初始密码发放

账号开通与名单导入分开；批量凭据接口最多50人，界面批量操作仅处理当前页所选学生。确认操作后，初始密码只存在组件内存，可下载UTF-8文本清单，由教师逐人发放。没有邮件自动发送，也不保存可供重复查询的明文。

存在未清除的一批明文时不允许发起下一批；离开有确认，卸载清空。密码不进入sessionStorage、localStorage、URL、通用名单响应或日志。页面提供“已保存，清除本页明文”；遗失时重新重置，旧会话和密码随之失效。

## 4. 共享登录与课程回归

登录和改密后先选课程；选定课程才恢复相符角色的返回地址。没有选定教师课程的深链接回到选课，不自动选第一门教师课。已缓存课程时结束加载，避免切换工作区一直转圈。

路由切换后启动共享activity管理，刷新直接进入教师页面也按真实操作续期；退出或失效停止跟踪。后台轮询不续期。共享客户端只允许当前认证代次的401清除凭据，迟到响应不会登出新会话。

题目与作业编辑离开有未保存确认；切换课程先经过路由守卫，取消后下拉框恢复原课程。账号发放页先保存/发放或明确放弃明文再离开。所有确认由共享ConfirmDialog提供，支持Escape、取消与焦点约束。

## 5. 结果和内容安全

教师进度调用共享选择服务，复用学生JudgeFeedback组件。排队或设施故障标为处理中，Mock不当正式分数，LOCAL CPU/内存显示未测量。答案用CodePreview或MarkdownPreview只读呈现；学生作答页只增加预算及来源展示，不改变其提交流程。

Markdown禁用原始HTML、KaTeX trust=false，最终输出清洗。参考答案和隐藏测试仅从教师授权接口读取，不在静态资源中打包题库。公开用例与题面样例独立维护，默认隐藏新测试点。

桌面使用固定侧栏与宽表；手机使用折叠菜单、卡片和表内横向滚动。本轮桌面1280px与390px断点均有实测，触屏真机验收仍由团队完成。
