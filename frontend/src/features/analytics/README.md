# 互评与分析模块

第③、④条真实链路实现位于 `peer-review/`；教师入口“互评与复核”，学生入口“我的互评”。复用共享登录与API请求客户端，在 `src/app/router.ts` 注册。

接口和架构见仓库 `docs/design/analysis/peer-review-*.md`，运行方式见 `docs/implementation/runbooks/peer-review-setup.md`。其他分析线路按对应契约接入；本模块输出逐题候选，不实现作业总分与正式成绩发布。
