# 文档索引

`docs/` 的唯一入口。三类文档按**回答什么问题**划分，不按作者、模块或写作顺序划分。

## 1. 三类判据

| 类别 | 回答的问题 | 典型特征 | 变更方式 |
|---|---|---|---|
| 功能 | 用户要什么、不做什么、什么算做完 | 范围、产品规则、验收标准；不出现表名和接口签名 | 随需求变更 |
| 设计 | 系统怎么建、边界在哪 | 表、字段、路由、事务、并发、模块路径 | 随实现修正 |
| 实施 | 已经做到哪、怎么跑起来、怎么协作 | 日期、提交、命令、勾选清单、实测截图 | 只追加 |

判断一篇新文档放哪：先问"它回答的是要做什么、怎么建、还是做到哪"。都不属于的，是**过程留痕**（任务单、评审记录）或**资产**（图、截图、原始素材），不要硬塞进三类。

## 2. 目录

```text
docs/
├── features/          功能：要做什么
│   ├── acceptance.md              阶段与整体验收（B01–B09）
│   ├── student/answer-and-judge.md 学生作答与评测的功能范围与产品规则
│   └── teacher/responsibilities.md 学生作答联调所需的教师端职责（TD01–TD08）
├── design/            设计：怎么建
│   ├── shared/        跨模块共用
│   │   ├── database.md            业务地图与写入边界
│   │   ├── database-schema.md     28 张表字段字典（由 SQLAlchemy 模型生成）
│   │   ├── data-flows.md          信息流、状态与失败处理
│   │   └── api-v1.md              当前 API 格式 v1（已实现）
│   ├── teacher/       architecture · backend · frontend · database · api
│   ├── student/       development（总纲）· api · judge
│   └── contracts/     foundation-v1 · next-phase · openapi.json · examples/
├── implementation/    实施：做到哪
│   ├── plan/          foundation-plan · progress · student-implementation-plan
│   ├── runbooks/      collaboration · data-import · teacher-setup · postgresql-migration · student-setup
│   └── evidence/      screenshots/teacher/ · teacher/ · student/
├── issues/            任务单：01-teacher · 02-student · 03-database-analysis
├── reviews/           评审闭环：student-review-resolution
├── archive/           历史：meeting-2026-10-21 · database-design-v0.1 · team-handoff
└── assets/            diagrams/ · source/
```

`issues/` 由 `scripts/sync_issue_templates.py` 读取并生成 `.github/ISSUE_TEMPLATE/`，路径不要改。
`assets/diagrams/` 由 `scripts/build_meeting_diagrams.py` 输出，路径不要改。

## 3. 编号空间

任务与场景编号全局唯一，不同文档族用不同前缀，避免"T01"同时指两件事。

| 前缀 | 含义 | 所在文档 |
|---|---|---|
| TH00–TH06 | 教师模块任务 | issues/01-teacher.md |
| S01–S05 | 学生模块任务 | issues/02-student.md |
| AN00–AN05 | 分析模块任务 | issues/03-database-analysis.md |
| AC01–AC37 | 学生验收场景 | design/student/development.md §9 |
| SL0–SL7 | 学生交付切片 | design/student/development.md §8 |
| SP00–SP24 | 学生具体实施任务 | implementation/plan/student-implementation-plan.md |
| RV01–RV09 | 学生评审技术问题 | reviews/student-review-resolution.md §1 |
| AD01–AD05 | 评审已定调整 | reviews/student-review-resolution.md §2 |
| C01–C09 | 跨模块交接项 | design/student/development.md §7 |
| TD01–TD08 | 教师端职责 | features/teacher/responsibilities.md |
| R01–R19 | 学生设计基线规则 | design/student/development.md §1 |
| B01–B09 | 整体验收场景 | features/acceptance.md |

`T`／`S`／`A` 只作为三位负责人的角色代号（教师、学生、数据库与分析），不是任务编号。

## 4. 命名约定

文档路径全小写 kebab-case，不使用下划线和全大写；只有仓库根的 `README.md`、`MAIN.md` 例外。

## 5. 相关入口

- 学生具体实施计划：[implementation/plan/student-implementation-plan.md](implementation/plan/student-implementation-plan.md)
- 学生作答与评测运行手册：[implementation/runbooks/student-setup.md](implementation/runbooks/student-setup.md)
- 学生 LOCAL 切片证据：[implementation/evidence/student/2026-10-24-local-slice.md](implementation/evidence/student/2026-10-24-local-slice.md)
- 项目启动与运行：[../README.md](../README.md)
- 分工与开发顺序：[../MAIN.md](../MAIN.md)
- 三人交接的原始摘要（历史）：[archive/team-handoff.md](archive/team-handoff.md)

## 分析模块设计与会议材料（2026-10-26）

分析框架与合成演示已实现；研究算法、正式互评/成绩业务仍待接入。

- [分析框架设计、全业务依赖与黑盒契约](superpowers/specs/2026-10-26-analysis-framework-design.md)
- [六条链路与黑盒输入输出4K图](assets/diagrams/analysis/README.md)
- [会议讲解与算法认领](design/analysis/meeting-walkthrough.md)
教师端2026-10-25联调实现与边界：[交付记录](implementation/evidence/teacher/2026-10-25-student-integration.md)。

- [分析API](design/analysis/api.md) · [黑盒研究交接](design/analysis/black-boxes.md) · [运行与演示](implementation/runbooks/analysis-setup.md)

第六条线可独立运行：只调用现有ability占位黑盒，不等待其他线路。见[独立线路说明](design/analysis/student-ability-line.md)。

## 相似代码检测与复杂度分析（2026-10-28）

两个研究插件从占位升级为真实实现；迁移 head 为 pg0007，30 张业务表。

- [同题代码相似检测](design/analysis/code-similarity.md)：词法规格化 + Winnowing 指纹，输出相似对、行号区间与相似簇。
- [已通过代码的复杂度分析](design/analysis/complexity.md)：结构分析 + 伸缩档实测，给出类别、置信度、增长曲线与适用范围。
- [实现与验证记录](implementation/evidence/similarity-complexity/2026-10-28-implementation.md) · [设计说明](superpowers/specs/2026-10-28-similarity-and-complexity-design.md)
