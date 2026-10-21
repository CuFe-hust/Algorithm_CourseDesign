# 全量结构化快照

数据版本：2026-10-21.1。JSON 使用 UTF-8 和 LF 换行，文件 SHA-256 在 Windows、Linux 及 Git 检出后保持一致；编程题 70 道，主观题 50 道，合成学生 217 位、8 班。`manifest.json` 记录数量、文件 SHA-256 与结构验证结果。

在 backend 目录运行 `python -m scripts.format_full_data` 可重新读取本机源资料。可用 `--roster-source` 指定本机原始名册；仅此转换步骤需要真实原表。其他环境可直接导入这里的公开 JSON，无需原表。

题目共用字段为 code/type/title/difficulty/tags/statement/requirements/input/output/constraints/examples/source/references/tests/reference_solutions/rubric，不适用字段使用空字符串或空数组。编程题保留原星级 1–5、公开样例、输入输出与数据范围、350 组原始测试、C/C++/Python 共 210 份参考实现；测试的 public=false 表示供开发验证，不把原测试当作学生公开样例。tests.weight 是源测试的相对权重，每组为 20；导入数据库时统一归一化为总和 1 的比例（每组 0.2）。原题未提供资源限制，未自行添加。参考实现与测试结果尚未独立运行验证。

主观题按原编号 SUB-A01…A20（ALGORITHM_ANALYSIS）、SUB-P01…P20（PROOF）、SUB-O01…O10（OPEN_QUESTION）保存。metadata 保留原难度文字、满分、建议分钟，difficulty 将基础/中等/进阶映射为 1/3/4。reference_answer 保留完整教师答案；Code 段以 Python 围栏保留换行与缩进，reference_solutions 单独保存参考代码。49 个 OMML 表达式转为内联 LaTeX，source_math_omml 同时保存原 XML 便于核对。rubric 保留原评分维度及分值，各题合计 100。references 保存原 R 编号、标题与超链接，source_file/source_anchor 可回溯公开 Word 正文。顶端索引表不作为题目导出。

students.anonymized.json 的 privacy 为 anonymized，所有姓名、学号、班名均为合成，保留班级人数结构。学号始终为字符串。record_key/login_name/class_code 是稳定导入键，不是数据库内部 ID。

真实身份 JSON、随机盐和稳定注册表仅写入本机 LOCALAPPDATA/AlgorithmReview/private-data/，不在仓库。真实版 privacy=real-local-only，与公开版使用相同 record_key/login_name/class_code；仅姓名、学号、班名不同。私有注册表首次以随机盐 HMAC 打散源行序，后续重排原表不会改变对应关系。请勿删除私有目录后期待沿用旧映射；无需将私有目录复制到公开仓库。

只验证本模块可运行：`python -m unittest tests.test_data_formatting`。测试身份均为虚构，无需真实名册。
