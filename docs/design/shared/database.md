# 数据库业务地图与写入边界

当前：PostgreSQL，21张业务表+alembic_version，迁移head为pg0001。SQLAlchemy模型是开发入口，Alembic迁移是建库/升级入口，字段见[数据字典](database-schema.md)。

## 1. 当前表分组

| 组 | 表 | 关联与用途 | 主写入口 |
|---|---|---|---|
| 账号 | users、auth_sessions | users存唯一账号/可空学号/姓名/密码哈希/状态；会话只存token摘要与到期 | 账号导入T，登录公共auth |
| 教学组织 | classes、student_profiles、courses、course_members | 一个学生资料关联当前班；一个用户在每门课只有一个角色 | T |
| 题库 | problems、problem_versions | problem是稳定身份和题型，version存某次题干、难度、作者、来源和冻结时间 | T |
| 知识点 | knowledge_points、problem_version_tags | 多对多；版本上的知识点权重和为1 | T配置，A统计读取 |
| 编程配置 | test_suites、test_cases | 测试集固定题目版本、资源限制和允许语言；用例有输入输出、顺序、权重和公开性 | T |
| 教师参考 | reference_solutions | 某个题目版本的参考答案/标准程序，language可空 | T，只向受信任后台提供 |
| 主观配置 | rubrics、rubric_items | 量表版本关联题目版本，每维满分与说明固定 | T |
| 作业 | assignments、assignment_items、assignment_participants | 本次选题/权重/截止/人数及发布时学生班级快照 | T |
| 正式作答 | submissions | 学生对作业题目每次确认提交，保留内容和版本，撤回不删记录 | S |
| 计算与结果 | analysis_jobs、judge_results | 编程提交的JUDGE任务及唯一模拟结果，固定输入引用，保存执行状态 | S事务建任务，A消费并写结果 |

其中course_members只表示选课/任课关系，不等于所有课程学生都自动参加所有作业；能否作答还要检查assignment_participants。

## 2. 关键字段怎样理解

| 字段 | 含义 | 使用规则 |
|---|---|---|
| id、*_id | 内部关联 | 数据库存BIGINT（有符号64位，最大9223372036854775807）；HTTP用字符串，前端不转Number |
| student_no | 学号 | 字符串、非空唯一；教师可空，空值用NULL |
| created_by/published_by | 创建/发布操作人 | 指向users.id，后端从登录身份写入，不相信前端冒充的ID |
| version_no | 所属对象内的版本 | 题目/测试集/量表按对象；提交按学生+作业题目，不是全库流水号 |
| problem_version_id | 本次题干与要求 | 作业引用冻结版本，修改题库不改变已布置作业 |
| test_suite_id、rubric_id | 题目专用配置 | 编程题仅测试集，主观题仅量表；必须对应同一题目版本 |
| max_score、score_weight | 题目满分、作业总分权重 | 分别保存；总分按100×Σ(题分/满分×权重)汇总，待评不能自动当0 |
| required_reviewers | 本次主观题的评审人数 | 编程为0，主观>0；真正是否能分配由A的约束检查决定 |
| class_id_at_publish、class_name_at_publish | 布置时班级 | 历史统计使用快照，学生后来转班/班级改名不改变旧作业 |
| submitted_at | 服务端接收时间 | UTC，严格早于deadline才接收新提交，不能用浏览器自报时间 |
| client_request_id | 一次逻辑提交的幂等键 | 同一学生内唯一，严格区分大小写；重试复用，重新作答生成新键 |
| parameters | 算法输入引用/参数 | 当前JUDGE含test_suite_id及problem_version_id；不是存随机结果的位置 |
| is_mock、algorithm_name/version | 结果来源 | 消费者必须显示模拟标记，实验需记录算法版本 |

示例：主观题满分80、量表满分100，原始评价先按量表规则归一化，再换算到80；作业权重0.25参与最终总分。具体聚合公式由A后续实现，此处只固定尺度。

## 3. 当前约束与事务

- 同学号不同姓名需要人工确认；姓名重名合法。课程编码、班级编码、课程内题号唯一。
- 同一课程用户只有一条成员记录；同一作业学生只有一条参与记录。
- 题目版本、测试集、量表按所属对象+version_no唯一；题目版本冻结后不覆盖。
- 同学生同题version_no唯一；同学生client_request_id唯一；同提交JUDGE任务唯一；同任务和提交的判题结果唯一。
- 题目配置有外键与部分CHECK；课程一致性、权重总和、冻结不可编辑等跨表规则仍需在服务层校验。当前没有通用触发器阻止任意SQL修改，队友不得绕过服务规则直接改业务表。
- 正式代码提交和JUDGE任务在一个事务里完成；任务写入失败，提交也回滚。应用启动不隐式create_all。
- 当前连接READ COMMITTED；提交锁账号行和名单行再分配版本，避免同一用户并发重复版本。
- 业务记录不级联清空。历史依赖存在时使用停用、归档、撤回或新版本。

## 4. 当前状态

| 对象 | 值 | 注意 |
|---|---|---|
| users.status | PENDING / ACTIVE / DISABLED | 只有ACTIVE可登录 |
| course_members.status | ACTIVE / INACTIVE | 每次资源访问检查 |
| problem_versions.status | DRAFT / FROZEN | 发布引用FROZEN |
| test_suites/rubrics.status | 当前实现仅FROZEN | 以后若支持配置草稿，A协调新增状态与迁移 |
| assignments.submission_status | DRAFT / OPEN / CLOSED | 不表示互评状态或成绩发布状态 |
| submissions.status | SUBMITTED / WITHDRAWN | 判题状态不放在这里 |
| analysis_jobs.status | PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED | 目前kind只使用JUDGE |
| API的AWAITING_REVIEW | 主观题无JUDGE任务时的派生显示值 | 不是数据库任务状态，不要插进analysis_jobs.status |

撤回时优先显示submissions.status=WITHDRAWN；主观题没有任务记录，因此可能仍带派生的AWAITING_REVIEW，不能据此把已撤回答案放入评审。

## 5. 现有任务框架的边界

analysis_jobs.submission_id当前必填，按一份代码提交组织。匹配整批作品、整轮聚合或关系检测不能伪造submission_id塞进该表。A先设计新的批次任务/输入快照或迁移扩展，再提交契约供T/S接入。

未来需要的评审批次、评审任务、原始评分/分项评分、评分修订、聚合结果、异常证据、教师处置、成绩发布与明细**尚未建表**。这些由A在[分析Issue](../../issues/03-database-analysis.md)优先补齐；T/S可先对接[规划DTO](../contracts/next-phase.md)和本地fixture做页面。

## 6. 分数、时间与统计口径

分数DECIMAL(8,2)、权重DECIMAL(8,6)，HTTP均字符串；TIMESTAMP WITH TIME ZONE（UTC读写）与带时区ISO响应；CPU毫秒、内存KiB。当前模拟资源为空，不是0。

后续统计必须区分学生通过率与提交通过率、最终发布分与预览分、未交与待评。重测不新增学生提交次数；知识点掌握只使用有依据的已出分记录，并显示缺失和样本量。教师设定难度与从得分估计的经验难度分别保存和命名。

## 7. 本地副本与升级

每个人自行创建PostgreSQL与.env，运行 `alembic upgrade head`、演示种子及全量结构化导入。通过Git共享模型/迁移/fixture，不交换原始数据库目录。当前固定head=pg0001；主干新增迁移后，拉取代码先升级再启动。`/ready`不接受旧或不识别的迁移版本。

真实名册和密码不进入仓库。测试会重建algorithm_review_test的已知表，不得放真实资料；项目演示库algorithm_review不会在测试中被清空。数据字典是实现快照，不代替迁移。
