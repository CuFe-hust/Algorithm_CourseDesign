# 数据库设计讨论稿 V0.1.0

> 历史记录：本文保留早期MySQL方案及当时验证结果。当前已切换PostgreSQL，启动与全量数据以README、POSTGRESQL_MIGRATION.md为准；当前4K图已更新。

- 日期：2026-10-21。
- 已对齐方向：统一网站工程；教师、学生、数据库与分析三个开发范围；各人独立本地数据库，以升级脚本同步结构。
- 技术基线：Vue 3、TypeScript、Vite；Python、FastAPI；MySQL、SQLAlchemy、Alembic。具体依赖及数据库版本在创建工程时固定。
- 本文主体：用户与教学组织、题库与版本、作业与参与名单、正式提交，共13张基础表的设计依据。
- 实施进展：已在独立MySQL中实现最小链路，共21张业务表。后续补充的配置/任务/结果/登录会话实际字段见[实际数据字典](../design/shared/database-schema.md)，数据流见[契约](../design/contracts/foundation-v1.md)，启动见[工程说明](../../README.md)。互评、聚合及正式成绩等仍属后续范围，不能将本稿视为最终完整平台设计。

## 1. 通用约定

| 项目 | 约定 |
|---|---|
| 表名与字段名 | 英文小写加下划线；表名用复数 |
| 主键 | 每张表有 `id BIGINT UNSIGNED` 自增主键，除非另有说明 |
| 通用时间 | 每张表有 `created_at DATETIME(6)`；允许修改的记录另有 `updated_at DATETIME(6)`，均必填，由服务端维护 |
| 时间语义 | 统一保存 UTC，接口时间带时区，界面显示北京时间；截止以服务端接收时间为准 |
| 字符 | 数据库使用 utf8mb4；学号按字符串保存。登录名、学号、题号等业务编码在应用层明确大小写及空白规范 |
| 金额式数值 | 分值用 `DECIMAL(8,2)`；权重用 `DECIMAL(8,6)`，不用浮点数保存需要精确汇总的分数 |
| 状态与类型 | 使用 VARCHAR 保存约定枚举，服务端校验，建库时根据固定 MySQL 版本补数据库约束 |
| 删除 | 有提交、互评或成绩的业务记录禁止级联物理删除；用户停用、成员退出、题目归档使用状态表示 |
| 内容 | 题干与主观答案使用支持 LaTeX 公式的 Markdown；程序源码按原始文本保存。显示内容时进行安全渲染 |
| ID 交换 | 数据库内使用整数关联；接口统一把 ID 作为十进制字符串传递，前端按字符串使用，避免 JavaScript 大整数精度问题 |
| JSON | 核心身份、关联、状态和分值使用明确字段；后续算法参数与可变证据详情可以用 JSON |

下列字段表省略通用 `id`、`created_at`；需要 `updated_at` 的表在说明中标明。所有 `*_id` 的数据库类型均为 BIGINT UNSIGNED；完整迁移必须落实外键及索引。

## 2. 用户与教学组织

### 2.1 users：统一账号

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| login_name | VARCHAR(64) | 是 | 登录名，唯一；导入学生时可使用规范化学号 |
| student_no | VARCHAR(32) | 否 | 学号，非空值唯一；教师允许为空，不能用空字符串代替空值 |
| full_name | VARCHAR(100) | 是 | 姓名，允许重名 |
| password_hash | VARCHAR(255) | 否 | 密码哈希；待激活账号可以为空，不能保存明文密码 |
| status | VARCHAR(16) | 是 | PENDING、ACTIVE、DISABLED；默认 PENDING |

含 updated_at。全局账号不直接保存“教师/学生”课程角色，由 course_members 决定。PENDING 账号不能正常登录，激活及初始密码分发方案在登录设计时确定；导入学号姓名不等于自动授权登录。

### 2.2 classes：班级

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| class_code | VARCHAR(64) | 是 | 班级稳定编码，唯一 |
| name | VARCHAR(100) | 是 | 显示名称 |
| status | VARCHAR(16) | 是 | ACTIVE、ARCHIVED |

含 updated_at。导入模板至少包含班级名称；班级编码缺省时由系统生成。相同名称出现多个候选班级时要求教师选择，不能静默合并。

### 2.3 student_profiles：学生资料

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| user_id | ID | 是 | 关联 users，唯一，一人一份学生资料 |
| class_id | ID | 是 | 关联 classes，当前行政班级 |

含 updated_at。姓名和学号只从 users 获取。转班更新此表；历史作业统计使用发布时保存的参与名单与班级记录。

### 2.4 courses：课程开课实例

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| code | VARCHAR(64) | 是 | 开课实例编码，唯一 |
| name | VARCHAR(100) | 是 | 例如算法设计与分析 |
| term | VARCHAR(32) | 是 | 学年学期标识，格式在初始化时统一 |
| created_by | ID | 是 | 关联 users，创建人 |
| status | VARCHAR(16) | 是 | ACTIVE、ARCHIVED |

含 updated_at。同一课程名称在不同学期建立不同记录；首版只初始化一个开课实例即可。

### 2.5 course_members：课程成员与角色

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| course_id | ID | 是 | 关联 courses |
| user_id | ID | 是 | 关联 users |
| role | VARCHAR(16) | 是 | TEACHER、STUDENT |
| status | VARCHAR(16) | 是 | ACTIVE、INACTIVE |

含 updated_at。`(course_id, user_id)` 唯一，首版一个用户在一门课程只有一个角色；不同课程可有不同角色。教师端所有管理操作先检查课程角色与资源所属课程，学生端还需检查本人或任务归属。

## 3. 题库与版本

### 3.1 problems：题目身份

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| course_id | ID | 是 | 关联 courses，题目所属课程 |
| code | VARCHAR(32) | 是 | 原题号或系统题号，例如 P01、A01 |
| question_type | VARCHAR(32) | 是 | PROGRAMMING、ALGORITHM_ANALYSIS、PROOF、OPEN_QUESTION |
| created_by | ID | 是 | 关联 users，入库操作人 |
| status | VARCHAR(16) | 是 | ACTIVE、ARCHIVED |

含 updated_at。`(course_id, code)` 唯一，题型在创建后固定；若需要从编程题改成证明题，建立新的题目身份。

### 3.2 problem_versions：题目内容版本

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| problem_id | ID | 是 | 关联 problems |
| version_no | INT UNSIGNED | 是 | 从 1 开始，`(problem_id, version_no)` 唯一 |
| title | VARCHAR(200) | 是 | 标题 |
| statement_md | LONGTEXT | 是 | 完整题干，包含必要代码片段与公式 |
| answer_requirements_md | TEXT | 否 | 学生作答要求 |
| input_spec_md | TEXT | 否 | 编程题输入说明 |
| output_spec_md | TEXT | 否 | 编程题输出说明 |
| data_constraints_md | TEXT | 否 | 编程题数据范围 |
| public_examples_md | TEXT | 否 | 学生可见的公开样例及说明，不作为隐藏测试的存放位置 |
| difficulty_level | TINYINT UNSIGNED | 是 | 教师设定难度 1～5；源资料难度先保留，导入时由教师确认映射 |
| source_reference | TEXT | 否 | 题目来源说明、链接或相对来源标识 |
| created_by | ID | 是 | 本版本编辑人 |
| status | VARCHAR(16) | 是 | DRAFT、FROZEN |
| frozen_at | DATETIME(6) | 否 | 首次冻结时间，FROZEN 时必填 |

草稿含 updated_at；冻结后内容不可修改。作业发布时冻结所用版本；改题创建下一版本。首次导入时间只说明系统入库时间，不伪造为原始文件作者的创作时间。

参考答案和标准程序不放在 statement_md，也不放在学生接口的通用响应中；对应独立教师参考表将在题型配置章节设计。

### 3.3 knowledge_points：知识点字典

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| course_id | ID | 是 | 关联 courses |
| code | VARCHAR(64) | 是 | 稳定编码；课程内唯一 |
| name | VARCHAR(100) | 是 | 显示名，例如贪心算法、区间调度 |
| status | VARCHAR(16) | 是 | ACTIVE、ARCHIVED |

含 updated_at。`(course_id, code)` 唯一。导入资料的分类和标签先经过字典映射，避免“分治”和“分治算法”无意中被当成不同概念。

### 3.4 problem_version_tags：题目版本与知识点关系

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| problem_version_id | ID | 是 | 关联 problem_versions |
| knowledge_point_id | ID | 是 | 关联 knowledge_points |
| mastery_weight | DECIMAL(8,6) | 是 | 该知识点在本题掌握统计中的权重，范围 (0,1] |

`(problem_version_id, knowledge_point_id)` 唯一。冻结前该题各知识点权重和必须为 1；未设置比例时由服务端等分并处理小数尾差。题目至少有一个知识点才能发布。冻结后关系与权重一并固定。应用服务检查知识点与题目属于同一课程。

## 4. 作业与参与名单

### 4.1 assignments：一次布置

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| course_id | ID | 是 | 关联 courses |
| title | VARCHAR(200) | 是 | 作业标题 |
| description_md | TEXT | 否 | 整体说明 |
| created_by | ID | 是 | 关联 users，创建教师 |
| submission_deadline | DATETIME(6) | 是 | 提交截止 |
| review_deadline | DATETIME(6) | 否 | 有主观题时必填，晚于提交截止；纯编程作业允许为空 |
| submission_status | VARCHAR(16) | 是 | DRAFT、OPEN、CLOSED |
| published_by | ID | 否 | 作业发布人，不是成绩发布人 |
| published_at | DATETIME(6) | 否 | 作业发布时间 |

含 updated_at。OPEN 时发布信息必填，发布时间早于提交截止。互评开启与成绩发布分别记录在后续评审批次、成绩发布表中；不能把 submission_status 当成整个作业所有流程的唯一状态。

### 4.2 assignment_items：作业中的题目

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| assignment_id | ID | 是 | 关联 assignments |
| problem_version_id | ID | 是 | 关联固定的 problem_versions |
| sort_order | INT UNSIGNED | 是 | 作业内显示顺序 |
| max_score | DECIMAL(8,2) | 是 | 本次作业中题目的满分，必须大于 0 |
| score_weight | DECIMAL(8,6) | 是 | 作业总分中的权重，范围 (0,1] |
| required_reviewers | SMALLINT UNSIGNED | 是 | 主观题大于 0；编程题为 0 |
| test_suite_id | ID | 否 | 编程题必填，主观题为空；引用后续测试集版本表 |
| rubric_id | ID | 否 | 主观题必填，编程题为空；引用后续评分量表版本表 |

草稿含 updated_at，作业发布后固定配置。`(assignment_id, sort_order)`、`(assignment_id, problem_version_id)` 分别唯一。首版禁止一份作业重复添加同一个 problem_id 的不同版本，该跨表条件由发布服务检查。

发布校验：各题 score_weight 之和为 1；题目所属课程一致；测试集与量表关联所选题目版本且已经冻结；题型必填项齐全。测试集及量表表设计补齐后才能形成可执行的完整迁移。

作业总分建议统一显示为 0～100：`100 × Σ(题目成绩 / max_score × score_weight)`。量表原始分按量表总满分归一化再换算到 max_score；未出分不直接代入零，缺交政策另行确认。

### 4.3 assignment_participants：发布时的应交名单

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| assignment_id | ID | 是 | 关联 assignments |
| student_id | ID | 是 | 关联 users，必须是本课程学生 |
| class_id_at_publish | ID | 是 | 布置时的班级，关联 classes |
| class_name_at_publish | VARCHAR(100) | 是 | 当时班级显示名快照，避免班级改名改变历史展示 |

`(assignment_id, student_id)` 唯一。教师可以按班级或具体学生选名单，发布时保存实际结果。发布后的名单不随转班或新入课自动变化；补加、退出等特殊变更后续走明确的教师操作与审计规则。

课程成员随后退出不删除历史记录；是否允许继续提交由当次作业的访问政策决定，首版默认要求账号可用、课程成员有效且在作业名单内。

## 5. 正式提交

### 5.1 submissions：每次确认提交产生一条记录

| 字段 | 类型 | 必填 | 含义与约束 |
|---|---|---|---|
| assignment_item_id | ID | 是 | 关联 assignment_items |
| student_id | ID | 是 | 关联 users，必须在本次作业名单中 |
| version_no | INT UNSIGNED | 是 | 同一学生、同一作业题目内递增，从 1 开始 |
| content | LONGTEXT | 是 | 主观答案或程序源码；服务器按题型解释 |
| language | VARCHAR(32) | 否 | 编程题必填，主观题为空；允许语言由评测配置决定 |
| submitted_at | DATETIME(6) | 是 | 服务端收到本次提交的时间，不接受客户端指定 |
| status | VARCHAR(16) | 是 | SUBMITTED、WITHDRAWN；默认 SUBMITTED |
| withdrawn_at | DATETIME(6) | 否 | 撤回时间，WITHDRAWN 时必填 |
| client_request_id | VARCHAR(64) | 是 | 客户端为一次逻辑提交生成的幂等标识 |

`(assignment_item_id, student_id, version_no)`、`(student_id, client_request_id)` 分别唯一。同一次网络重试返回已存在记录；相同幂等标识携带不同内容时返回冲突，不能偷偷产生另一版本。

内容、语言、版本与提交时间保存后不可覆盖。版本号通过事务及并发控制生成，不直接依赖无保护的 MAX+1。撤回只允许在截止前、且尚未固定进入评审的情形；重交另建版本。草稿不进入此表，自动保存草稿的需求单独设计。

建议索引：`(assignment_item_id, student_id, submitted_at)`，支持教师按题目和学生查询提交历史。判题状态保存在评测任务及结果中，不能把 SUBMITTED、AC、RUNNING 混进一个枚举。

## 6. 四段数据流与写入责任

| 场景 | 操作入口 | 数据动作 | 保持的条件 |
|---|---|---|---|
| 导入学生名单 | 教师模块 | 校验预览后，写 users、classes、student_profiles、course_members | 同学号对应同账号，姓名可重名；名单缺少某人不自动删除他 |
| 导入题目 | 教师模块 | 写 problems、problem_versions、knowledge_points 与标签关系；后续接题型专用配置 | 来源材料的题干、参考答案、测试数据分开；不自动假定资料里的测试已全部正确 |
| 发布作业 | 教师模块 | 固定 assignment_items、参与名单与引用版本，设置 OPEN 和发布信息 | 所有发布校验通过后在一个事务完成；失败整体回滚 |
| 查看题目 | 学生模块 | 检查身份、名单、作业状态，读取 assignment_items 指向的题目版本 | 返回学生可见字段，不返回教师参考答案、隐藏测试或身份映射 |
| 提交答案 | 学生模块 | 校验题型、名单、截止；新增 submissions；编程题后续同事务登记分析任务 | 接收时刻必须严格早于截止；重复请求不重复写入，提交成功后任务不能丢失 |
| 教师查看过程 | 教师模块 | 在权限范围内查询名单、题目与提交 | 按题目、学生、班级得到同一份事实；最终成绩尚需后续成绩表 |

这些是逻辑写入责任。数据库模型和公共校验由统一后端复用，三个开发范围不各自复制建表定义。

## 7. CSV 导入首版约定

模板字段建议为 `student_no,full_name,class_name`，明确使用 UTF-8；教师在页面上选择要导入的课程。原始 xlsx 文件先通过本地转换或教师端适配映射到同一导入结构。

1. 预览阶段检查空字段、同文件重复学号、已有学号对应姓名不同、班级无法唯一识别等问题。
2. 同文件同学号重复默认报错，避免无法判断哪一行生效。重名但不同学号合法。
3. 已存在学生默认复用账号，预览展示将新增或变更的资料；不静默覆盖姓名、转班或课程角色。
4. 首版建议整批校验通过后一次确认入库，存在错误先修文件；确认时重新校验并用事务保证一致性。
5. 导入操作在后续审计中记录操作人、时间和新增/更新数量；原始学生名单和本地数据库不作为公开演示种子提交到公共仓库，仓库使用合成演示数据。

## 8. 本轮待讨论的默认选择

- 一个用户在一门课程只有一个课程角色；首版不支持同一课程兼任教师与学生。
- 作业一旦发布，题目、权重、量表、测试集和应交名单按本稿固定；更正需明确操作和记录。
- 每份作业的总分统一换算为 100，题目满分与总分权重分别保存。
- 主观题进入互评时选择哪个正式提交版本、编程题采用哪次有效成绩，以及未交政策，在后续评审与成绩章节确定。
- 当前“班级”指行政班；如果还需要课程内分组、跨班分组，增加独立分组结构，不能直接覆盖行政班。

## 9. 下一段设计范围

补齐测试集与测试用例、参考答案、量表与维度；再设计评审批次、任务、评分、算法任务与结果、异常处置及成绩发布。全部核心结构与数据流确认后，生成 SQLAlchemy 模型、Alembic 首次迁移、合成演示数据和前后端接口样例。

## 10. 最小链路实施补充

2026-10-21已补齐test_suites、test_cases、reference_solutions、rubrics、rubric_items、analysis_jobs、judge_results及auth_sessions，并实现SQLAlchemy模型和0001/0002迁移。本稿ID/UTC/版本/权限/应交名单原则已进入实现。

实现中的client_request_id采用区分大小写排序规则；数据库会话只存随机Bearer token的HMAC摘要，默认2小时有效。模拟评测任务保存测试集和题目版本输入引用，输出明确标记模拟，资源指标为空。作答事务同时保存代码提交和任务，主观提交仅保存答案。实际字段、约束与后续变更以工程模型及迁移为执行依据。
