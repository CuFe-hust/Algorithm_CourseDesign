# 主观互评与聚合复核运行手册

本功能位于独立功能分支，合并前由三位组员检查增量迁移与第五线交接。不要把本机合成数据当作真实学生成绩。

## 环境及升级

沿用仓库 README 的 PostgreSQL、Python依赖与前端安装方式。数据库应先到pg0006；迁移前用 pg_dump 备份已有开发库，并核对目标库，勿将测试命令指向共享生产库。

```bash
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端启动分析 worker：

```bash
cd backend
../.venv/bin/python -m scripts.run_analysis --watch
```

再按现有前端说明在 `frontend` 中运行 `pnpm dev`，打开 localhost:5173。`GET /api/v1/ready`应返回pg0007。worker 未启动时预览会显示“就绪”，没有自动计算；不能绕过它直接发布。

pg0007只新增6张业务表及约束，不删除原学生/教师数据。已有pg0006保留其取消作业总分的行为。降级pg0007会删除全部本模块表，应先备份并确认不存在要保留的任务/评价；正常联调使用升级，不降级共享库。

## 教师与学生操作

1. 教师备好主观题冻结量表、作业应交名单、每题评审人数及本题满分；学生提交答案。
2. 教师关闭提交并等待提交截止到达，进入“互评与复核”选择对应作业题目，设置未来评审截止、最低样本及方法，生成预览。
3. 等待分配结果；可查看可行性与负载。不可行时取消预览，调整未发布范围或政策后重建。确认时输入变化会被拒绝，需重新预览。
4. 教师显式确认开放。学生进入“我的互评”，阅读作品后按每个量表维度打分并填评语。提交后原始评价只读。
5. 教师刷新任务列表，填写理由并封存；提前封存有缺评时须勾选明确接受缺评。到期不会暗中自动发布成绩，仍需教师封存。
6. 等待四类检测完成，逐项查看证据和不足状态；需要时查看原作品和评语，添加每条处置及理由。填写总复核理由并逐项确认四类实际状态。
7. 不补评时提交会新建重算版本；需要补评时勾选补评、设未来截止，提交后进入新轮次，仍需确认开放及封存，再次复核后重算。
8. “本题候选结果”供第五线读取；保留明确空值和来源，本模块不发布正式成绩。

## 验证

后端测试只清理指定 `algorithm_review_test`；先在独立测试库升级迁移，再运行：

```bash
cd backend
DB_NAME=algorithm_review_test ../.venv/bin/alembic upgrade head
../.venv/bin/pytest -q
../.venv/bin/python -m scripts.review_experiments
```

前端：`pnpm test`、`pnpm typecheck`、`pnpm build`、`pnpm format:check`。纯算法规模实验写入 `data/analysis/review-experiments.json`，不读数据库。

真实 HTTP 验证脚本只访问 localhost:8000，且断言课程为DEMO_ALGO合成课程。先按已有seed脚本建立合成账户，将其现有演示密码保存在git忽略的本机文件 `local-data/peer-review-qa/credentials.json`（结构为password字段），不要提交凭据。启动后端后：

```bash
cd backend
../.venv/bin/python -m scripts.review_http_smoke --credentials ../local-data/peer-review-qa/credentials.json
```

脚本通过实际 HTTP 创建独立作业、六人作答、18份原始评价、作废补评1份及教师改分，调用独立 CLI worker，检查原分不变、3个分析版本和6份候选。会追加合成作业，重复运行不会覆盖旧轮次。报告在忽略目录 `local-data/peer-review-qa/http-report.json`。`--prepare-ui`仅准备六份作答，留给浏览器实际创建互评；不自动操作网页。

生成文档：在backend运行 `python -m scripts.generate_schema_doc`、`python -m scripts.export_analysis_contracts`，OpenAPI由 `app.main.create_app().openapi()`导出；不要提交任何真实学生内容、密码、token或私有.env。

## 故障处理

- READY不推进：检查独立worker和数据库目标是否一致。
- FAILED：按运行ID显式重试，最多3次；算法版本变化须新建批次，不覆盖旧结果。
- SOURCE_CHANGED / VERSION_CONFLICT：刷新并重新检查事实，不能修改浏览器参数强行确认。
- 补评不可行：检查作者、自定义禁止关系、此前已分配者排除与累计任务上限；不降低安全约束。可取消未开放补评，显式新分析后由教师独立改分并说明理由。
- 当前候选WAITING_INPUT：完成当前人工关卡、活动补评或重算，不回退旧版本冒充当前结果。
