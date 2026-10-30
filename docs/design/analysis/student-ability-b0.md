# 第六条线首版：章节作答表现与个人面板

2026-10-29。首版真实实现 B0，支持数据库持久化任务和个人面板。旧 `STUDENT_ABILITY` 占位线路保留为历史契约；新入口使用 `STUDENT_ABILITY_B0`，不改写历史输入/输出。

## 今天会议怎么演示

启动现有后端和前端后，在 backend 目录运行：

```powershell
..\.venv\Scripts\python.exe -m scripts.demo_student_ability_b0
```

脚本只创建标明来源的合成输入批次并执行真实B0，不修改账号密码或真实成绩。终端返回实际course_id、batch_id、实现名、hash和演示地址。

当前本机入口：`http://127.0.0.1:5173/student/courses/1/ability?demo=1`。以已有 `demo.student01` 登录；密码在本地 `.env` 的 `DEMO_PASSWORD`，不要写入会议公开材料。其他机器根据脚本返回的course_id访问，不能硬编码为1。

建议按以下顺序讲解：

1. 返回正式分析：没有正式来源时显示未生成，不显示模拟分数。
2. 切换合成演示：醒目的来源标记一直保留。
3. 对照贪心章节：两道编程题和一道主观题的归一化成绩合并；不规定两类各50%。
4. 分治章节为真实计算出的0，动态规划为1；与无有效证据的空值区分。
5. 排序与查找待评、数据结构未提交，雷达不补零，证据表给出原因。
6. 数学与数论、位运算与杂项、数组与模拟未布置，页面隐藏。
7. 展示输入hash和实现版本，说明结果来自已保存的artifact，刷新不改变结果。

演示数据中前五名学生有成绩，最后一名演示学生无布置题，展示空范围分支；数据均为测试场景，不代表真人表现。

## 计算定义

章节 `c` 的有效已评分题集合为 `V_sc`：

`B0_sc = Σ(i∈V_sc) chapter_weight_ic × normalized_score_si / Σ(i∈V_sc) chapter_weight_ic`

- 两类题都参与；满分先由上游归一化，章节权重不是满分权重。
- 编程/主观子均值单独返回，只作诊断；不生成作业总分、综合rating或置信区间。
- NOT_COVERED：未布置，前端隐藏；NO_EVIDENCE：布置了但没有有效成绩，留空。
- LOW_EVIDENCE：默认不足3题或评分覆盖不足50%，显示数值和提示。阈值是可配置工程选择。
- 全零、全一、全等只作诊断，不自动降级。有效0分正常保留。
- 观测min/max仅描述已评分题目的分数范围，不是对未知表现的区间。
- 后端固定输出11章/学生，页面按章节顺序过滤未布置的轴；少于3个可见章节用条形/证据表。

核心实现 `ability_b0.analyze` 只做纯函数计算；时间 `O(P+S×11)`，按学生和章节可计算并行，但跨章共享题目的统计证据有关联。

## 章节映射

`data/analysis/chapter-taxonomy.json` 定义原始11文件夹的代码、名称及顺序；`question-chapter-mapping.json` 包含120题映射与依据。

70编程题按原目录归属，50主观题中45已暂定映射、5个UNMAPPED保留单题结果但不进雷达。4题跨章权重及部分归类仍标记复核；它们是工程归因而非测量校准。本轮不扩展第12轴。

## 接口与版本

| 接口 | 权限与含义 |
|---|---|
| POST `/api/v1/analysis/courses/{id}/student-ability/b0-batches` | 课程教师；body `{mode:"DEMO",request_id:"unique-id"}`；只创建任务 |
| GET `/api/v1/analysis/batches/{id}/input` | 课程教师；查询已冻结输入、参数和hash |
| GET `/api/v1/analysis/batches/{id}` | 课程教师；状态与保存的输出 |
| GET `/api/v1/courses/{id}/my-ability` | 当前课程学生；只看本人正式结果 |
| GET `/api/v1/courses/{id}/my-ability/demo` | 当前课程学生；只看本人合成演示 |
| GET `/api/v1/analysis/b0-contract` | 登录用户；专用算法JSON Schema |

契约 `ability-b0-v1`；算法key `ability_b0`、实现名 `ability_b0`、实现版本 `2`。为保持历史15槽位catalog与样例兼容，新B0作为独立版本扩展注册，不替换旧ability插件。

输入有独立匿名学生集合、已布置expected_pairs、固定章节词表、逐题元数据与归因权重、已定版成绩及来源/映射/评分政策版本。后端固定快照后worker读取它，输出包含每生每章的分数、题数、权重和、Kish量、覆盖与缺失分类。学生投影不返回其他学生或完整输入。

最新结果只在同课程、B0、COURSE范围、对应来源类型中选择；最新等待/失败批次返回真实状态，不静默拿旧值替代。无布置学生仍在独立名单中，可得到11个NOT_COVERED。

## 正式来源依赖

2026-10-30整合更新：正式编程计分与互评复核已通过课程快照接入，见[完整接入设计](student-ability-integration.md)。下述无来源等待及历史契约边界继续保留。

REAL_INPUT 无来源会WAITING_INPUT；旧格式来源缺少范围、状态和题目元数据时也等待，不从实时库猜历史。课程范围的 `result_snapshot` artifact 可提供 `payload.ability_input_v2` 完整冻结输入，必须 `source_kind=DATABASE` 且来源批次、ROOT、artifact均非mock。

`SYNTHETIC_FIXTURE` 即使由真实B0计算，仍然是mock证据，只能进入演示投影。正式接口不会使用演示补位。

## 重跑与验证

```powershell
# 工程根：实际HTTP登录、创建批次、执行worker、读取与隔离校验；不输出凭据。
.\.venv\Scripts\python.exe scripts/smoke_ability_b0_http.py
# backend：核心和集成
..\.venv\Scripts\python.exe -m pytest tests/test_ability_b0.py tests/test_ability_b0_flow.py -q --tb=short
# frontend
pnpm test
pnpm build
```

无需数据库迁移，复用现有4张分析表。数据库测试只使用 `algorithm_review_test`；完整开发配置与启动方式仍按README。

AI协作说明：设计由人确定交付范围和解释边界，AI辅助代码、测试与会议图生成；团队应理解并能解释公式、状态、权限和验证。
