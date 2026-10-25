# 学生作答与评测前端

本目录为已落地的学生端实现（2026-10-24）。任务拆分见 [学生作答与评测实施计划](../../../../docs/implementation/plan/student-implementation-plan.md)，设计见 [开发设计](../../../../docs/design/student/development.md)、[接口设计](../../../../docs/design/student/api.md)、[评测设计](../../../../docs/design/student/judge.md)。运行与验收命令见 [运行手册](../../../../docs/implementation/runbooks/student-setup.md)。

## 结构

```text
student/
  StudentLayout.vue            课程内布局与导航
  CourseHome.vue               作业列表、进度与待评测任务
  AssignmentDetail.vue         作业详情与逐题状态
  AnswerWorkspace.vue          四题型作答、草稿、提交、结果与版本
  SubmissionHistory.vue        本人提交筛选与分页
  SubmissionDetail.vue         只读版本、撤回、重评、载入编辑器
  components/                  ProblemStatement / ProgrammingEditor / SubjectiveEditor
                               SubmissionStatus / JudgeFeedback / DraftStatus
  composables/                 useDraft / useSubmission / useJudgePolling
  api.ts / types.ts / draft-store.ts
```

## 关键约定

- 草稿只存本机 IndexedDB，键为 `账号 + 题目 + 语言`；主观题使用 `subjective`。切换语言只读取该语言的草稿或最近提交，绝不把一种语言的正文放进另一种语言。
- 提交前先把不可变快照写入「未确认请求」；网络结果不明时用同一 `client_request_id` 与相同内容重试，只有新内容才换键。202 只表示已保存。
- 任务发现以 `GET /me/judge-jobs?filter=DISCOVERY` 的游标扫描为准（课程首页翻页到 `has_more=false`，60 秒重扫），轮询按 100 个 ID 分批、最多两批并发，页面隐藏时暂停；轮询不算用户活跃，不延长会话。批量查询 404 时重建可见集合，不逐个探测。
- 登录/改密后一律先进入课程选择；选课页只在目标属于该课程时才回到原位置（`shared/navigation.ts`）。
- 续期只由真实输入／点击触发，最多每 60 秒一次；没有新操作不发保活请求。
- 认证代次（`shared/api.ts`）保证改密或重登录后，旧请求的 401 与旧响应不会覆盖新身份。
- 学生页面只使用 `GET /assignment-items/{id}` 等学生安全视图，不调用教师题目详情再在前端删字段。

## 未完成

- 浏览器级 E2E（真实编辑器续期、刷新恢复、多标签页可视化）尚未接入工具；当前为组件／逻辑测试与 HTTP 冒烟。
- Linux 沙箱与 CPU／内存展示属后续切片，LOCAL 一律显示「未测量」。
