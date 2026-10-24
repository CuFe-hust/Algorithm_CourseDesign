# 全量结构化数据与导入

当前快照在data/formatted，manifest记录SHA-256与数量。原题源在data/source；格式化器独立解析70份Markdown及50题Word，保留49处公式的LaTeX和原OMML、15份主观题Python代码。编程参考实现210份，主观完整教师答案50份，主观代码15份；入库reference_solutions共275行。参考实现与测试仅通过结构检查，尚未执行验证。

## 队友默认流程

先按README建PostgreSQL、`alembic upgrade head`和`python -m scripts.seed_demo`，再在backend执行：

```powershell
..\.venv\Scripts\python.exe -m scripts.import_full_data
```

默认读取公开的students.anonymized.json，导入独立课程ALGO_FULL_2026：120题、217学生、8班。DEMO_ALGO/4题/6学生仍供最小链路演示；因此整个项目库合计124题和224账号（含教师），不要误认全量导入重复。全量课程不自动创建作业与应交名单；教师后续从题库选择版本发布作业。

文件哈希先校验，整个导入事务提交，任一步失败全部回滚。course/code、login_name、class_code稳定；重复导入创建数量均为0。题目内容hash变化创建新FROZEN版本，不改旧版本；源题类型变更须新code。源题标签权重归一化为1；测试相对权重20归一化为每组0.2。CPU1000ms、内存262144KiB、python3是明确标注的项目默认，未核实可执行；仍由模拟worker处理，不代表真实判分。

学生账号PENDING、password_hash为空，不能登录；公开合成身份并非预设通用密码。激活与密码分发由教师模块后续实现。题目源JSON含教师答案与隐藏测试，供后端开发，不作为学生前端静态资源。

## 真实名册仅本机

原始xlsx、真实JSON、随机盐和稳定映射均不在Git仓库。转换脚本默认把私有资料写到 `%LOCALAPPDATA%/AlgorithmReview/private-data/`。仅在持有原名册且明确需要的本机，可在backend运行：

```powershell
..\.venv\Scripts\python.exe -m scripts.import_full_data --students-file "$env:LOCALAPPDATA/AlgorithmReview/private-data/students.real.json" --allow-private
```

真实版和公开版使用相同稳定导入键，身份字段不同。不能向同一课程先导入公开版再覆盖为真实版；发现冲突就回滚，应各用独立数据库。私有文件必须在仓库之外。CLI只输出计数与状态，不输出姓名/学号；SQL连接隐藏参数。数据库目录、导出备份和真实身份日志均不得上传。此次本机项目库用真实版，验证库仅用合成身份。

## 重新格式化

在backend运行 `python -m scripts.format_full_data --help`。仅重新生成名册的转换步骤需要本地原始xlsx；队友直接用公开快照无需xlsx。JSON以UTF-8/LF保存，Windows和Linux克隆后hash一致。请保留本地私有注册表以维持匿名映射；不要把它放入Git。修改快照后必须重新生成manifest并跑格式化及导入测试。

## 教师CSV功能边界

教师CSV建议student_no,full_name,class_name，UTF-8，学号按字符串处理。预览检查非空、重复学号、班级对应与已有资料冲突，确认阶段重校并事务写入；缺失学生不自动删除。当前批量快照CLI已实现，交互式CSV预览/确认页面及API仍由教师Issue实现。
