# 教师端与Peer Review报告复现证据

日期：2026-11-11。报告见 `docs/reports/teacher-peer-review-analysis.md`。

## 基准与数据

算法来自main提交837fa388ed1c39ba9f8da6300a43cfb49c9784b1的独立导出快照。replay-results.json中hashes已与git show origin/main对应文件逐项校验。全部为合成数据，不使用数据库、密码或真实学生记录。

- algorithm-tests.log：本次8项纯算法测试回执，非整个平台回归。
- replay-results.json：18次规模对照、两作品贪心反例、聚合/偏离/时长小例；包含环境、源码摘要、耗时、约束和断言。
- 使用3个种子，但原贪心不使用种子；不能将其当作3个独立随机课程。
- 本轮未执行数据库和HTTP/前端全链路。

## 重放

在含报告脚本与待测代码的仓库执行：

```bash
cd backend
../.venv/bin/python -m pytest tests/test_review_algorithms.py -q --tb=short
../.venv/bin/python -m scripts.replay_teacher_peer_review_report ../data/analysis/experiments/peer-review-report-new-run
```

建议另选输出目录保留本次回执。新运行会记录实际克隆HEAD；无.git的导出快照将记录null，需额外注明导出版本，并用hashes核对。耗时预期随机器变化，评分与负载等确定性结果才适合直接对照。
