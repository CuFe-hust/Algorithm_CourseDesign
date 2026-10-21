# PostgreSQL与全量数据同步方案

日期：2026-10-21；依据：团队决定改用PostgreSQL、全量结构化题库与名册同步；用户已选择GitHub只公开脱敏数据，真实姓名学号仅保存在本地。

## 目标与范围

迁移现有21表、连接/初始化、迁移脚本、种子和测试到真正PostgreSQL，保留API主要行为；整理70编程+50主观题及217位学生/8班的结构化快照、校验报告、可重复导入命令。分析业务框架仍维持现有模拟JUDGE，不在本轮新增互评/聚合/检测流程。

## 迁移选择

- 在本机启动独立PostgreSQL开发实例，优先5433，现有MySQL实例及数据保留，不做破坏性原地转换。
- PostgreSQL独立Alembic链以pg0001开始；旧MySQL0001/0002保留为历史，默认配置只执行PostgreSQL链。新库通过结构化数据导入重建，不把MySQL模拟提交/会话当真实课程数据迁移。
- BigInteger改为PostgreSQL有符号64位，API上限同步为9223372036854775807；Timestamp使用带时区UTC；JSON使用PostgreSQL JSONB或通用JSON的PG变体；去除MySQL排序规则和unsigned类型。
- 保留API字段名、字符串ID、分数字符串、提交版本/幂等、权限和模拟标记。PostgreSQL字符串天然按当前配置区分大小写，请求键仍区分大小写。
- 真实名册转换为本机LOCALAPPDATA下的JSON，公开文件只含合成姓名/学号/班名。私有对应关系/随机盐不进入仓库或日志。

## 全量数据契约

data/formatted/questions.programming.json和questions.subjective.json各为数组；每题字段：code、type、title、difficulty、tags、statement、requirements、input、output、constraints、examples、source、references、tests、reference_solutions、rubric。不适用字段为空或空数组。

- 编程code为CODE-P01等，tests为input/output/public/weight结构，参考实现包含language/content；原5组用例仅用于开发，未宣称全部已经验证正确。资源限制为显式项目默认，不冒充题库原限制。
- 主观code为SUB-A01/SUB-P01/SUB-O01；rubric维度为name/max_score/description。保留完整参考答案、代码换行与Word公式（OMML转LaTeX），不默默丢弃公式。
- data/formatted/students.anonymized.json包含schema_version、privacy、classes、students。classes字段class_code/name；students字段record_key/login_name/student_no/full_name/class_code。私有JSON保持相同外部record_key/login_name/class_code，姓名/学号/班名仅本地保留真实值。
- 不导出数据库内部自增ID、密码哈希或会话。按题号、班级编码、稳定login_name在导入时解析数据库外键；重复导入不重复插入，不静默覆盖冲突数据。
- 导入全量课程ALGO_FULL_2026；课程教师复用合成demo.teacher。新学生为PENDING且无密码，不自动激活真实学生。全量题库120题，无自动发布120题作业；现有DEMO_ALGO/4题/6演示学生可保留用于最小链路。

## 验证与交付

先观察现有PostgreSQL配置/类型和全量解析测试失败，再实施并验证：PostgreSQL真实建库/迁移、API回归、120题完整性、217学生/8班、公式/代码/评分量表、外键/重复导入、公开资料无真实身份。默认公开数据和本机私有数据都提供显式导入方式，执行时不同时覆盖同一课程的两套身份。

文档、数据字典、模式图标题和数据库启动说明同步更新，历史会议记录保留日期和旧环境说明，不把过去的MySQL描述误当当前方案。通过后同步GitHub，推送前检查远程main和脱敏范围。

## 已有MySQL副本如何切换

1. 停止本工程API/worker，保留旧MySQL实例和数据。
2. 按README安装新版依赖及PostgreSQL程序；运行项目setup_local_postgres.py。第一次切换将原.env备份到本机postgres-local/previous-mysql.env，再生成5433的新连接。
3. 在backend执行`python -m alembic upgrade head`，新库从空创建pg0001；不要把旧库的alembic_version拷进新库，不对旧MySQL库运行新迁移链。
4. `python -m scripts.seed_demo`，再`python -m scripts.import_full_data`导入公开版；本机持有真实名册时改用data-import.md中的私有命令。两种身份版不要导入同一库。
5. 重启API和模拟worker，检查`/api/v1/ready`返回pg0001，执行HTTP smoke。旧token失效，重新登录；历史MySQL模拟提交保留在旧实例，没有搬到新库。

共享数据以JSON快照和迁移重建，不提交PostgreSQL二进制、数据库目录、.env或原始真实名册。安装说明见[官方Windows下载](https://www.postgresql.org/download/windows/)及[Psycopg安装文档](https://www.psycopg.org/psycopg3/docs/basic/install.html)。

## 本轮验证记录

- PostgreSQL 18.6独立实例5433，项目与验证库分开，项目角色非超级用户。
- 46项自动化测试通过，覆盖迁移往返、21表模型比对、权限、并发幂等、数据格式、全量导入/重复导入/身份冲突/哈希篡改。仅上游Starlette TestClient的httpx弃用提示。
- 真实HTTP链路通过：登录、查题、提交重试、模拟结果、教师可见/其他学生隔离、主观答案保存。
- 本机项目库全量120题及真实217学生/8班，重复导入新增0；公开文件仅脱敏身份，真实名册及映射在LOCALAPPDATA。
- 两张3840×2160图、PostgreSQL数据字典和三人启动/导入说明同步更新。
