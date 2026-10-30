# 整合版本运行与检查

当前head pg0010，36张业务表。先阅读README配置数据库和依赖，已有数据库升级前备份；不要覆盖队友私有.env或导入真实名单到公开仓库。

## 启动

在backend执行迁移并初始化已有题目的复杂度输入配置：

```bash
../.venv/bin/alembic upgrade head
../.venv/bin/python -m scripts.seed_complexity_profiles
```

macOS/Linux本地真实执行联调分别启动以下进程，配置仅影响对应进程：

```bash
JUDGE_EXECUTION_MODE=LOCAL ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
JUDGE_EXECUTION_MODE=LOCAL ../.venv/bin/python -m scripts.run_judge --loop --mode LOCAL
../.venv/bin/python -m scripts.run_analysis --watch
JUDGE_EXECUTION_MODE=LOCAL ../.venv/bin/python -m scripts.run_complexity --watch
```

前端在frontend执行 `pnpm dev`，打开127.0.0.1:5173。MOCK仅用于演示，不能用于逐题真实分数；原生Windows的LOCAL限制沿用现有README，不把它伪装成Linux沙箱。

- 教师：分析中心→各链路入口；逐题结果→选择已关闭作业→填写理由→固定快照。
- 学生：作答→提交/评测→已通过代码可申请复杂度；我的互评→提交本人评价；学习报告→查看教师已固定的本人题目结果。
- 当前②、⑥仍有占位研究模型，见分析中心；不以演示值补齐。

## 复现验证

独立测试库先迁移到head，backend执行 `pytest -q -rs`；frontend执行 `pnpm test`、`pnpm typecheck`、`pnpm format:check`、`pnpm build`。测试只清理algorithm_review_test。

完整HTTP联调仅用于本机DEMO_ALGO合成课程。凭据文件沿用[互评手册](peer-review-setup.md)，不得提交：

```bash
cd backend
../.venv/bin/python -m scripts.review_http_smoke --credentials ../local-data/peer-review-qa/credentials.json --with-programming
```

脚本会追加混合作业并提交6份真实编程答案、6份主观作品，完成18份互评、1份补评、教师复核/改分、新版本及12份逐题结果；检查学生投影仅有本人2份。编程评测worker与API必须使用相同LOCAL上下文。运行会保留合成历史，不删除旧任务。

详见[整合设计与六链路状态](../../design/analysis/platform-integration.md)、[验收记录](../evidence/integration/2026-10-30-platform-integration.md)。截图是本机合成账户，不是真实学生成绩。
