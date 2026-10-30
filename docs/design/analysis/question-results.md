# 题目结果直接进入学习分析（2026-10-27）

团队决定：不设计、不计算每次作业的总分。作业只是布置题目、名单和截止的容器。

- 保留单题满分、编程表现、同一道主观题的互评分聚合、异常复核和知识点/测试/评价内部权重。
- 删除assignment_items.score_weight、教师等分权重按钮、学生题目权重展示，以及跨题总分/成绩发布节点。
- 新流程：item_scores → result_snapshot → mastery / ability / statistics / empirical_difficulty；behavior独立。快照仅复制逐题结果并固定版本，不求和、不求学生作业均分、不等待发布事件。
- analysis-v2使用results_snapshot_version，23步骤；人工事件仅OPEN_REVIEW/SUBMIT_REVIEWS/RESOLVE及需要时SUBMIT_SUPPLEMENT。
- pg0006从pg0005升级。旧分析批次保留历史但取消后续执行/租约，新代码要求新建v2批次；不能读取旧批次作为当前结果。旧迁移文件不改写。
- 不同单题满分仍分别保留。基础统计的样本均值不是给某个学生结算作业分数，不能以别名恢复作业总分。

第六线后续直接对接学生同学的编程题表现与教师同学的主观题有效结果，不依赖任何作业级分数。当前真实评分适配与模型研究仍按后续任务开展。

2026-10-30：真实逐题快照与个人权限投影已接入，保留本页不计算总分的约定；模型研究仍未完成。见[整合边界](platform-integration.md)。
