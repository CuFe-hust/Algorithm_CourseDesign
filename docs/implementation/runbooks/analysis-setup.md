# 当前分析流程（2026-10-27）

已按会议决定取消作业总分与总分发布依赖；作业仍负责出题、名单和截止管理。单题满分、主观题互评分聚合、知识点权重均保留。

当前流程：题目结果 → result_snapshot → 掌握 / 能力 / 基础统计 / 经验难度；行为指标独立。analysis-v2，pg0006，23步骤，15插件。

会议分工：学生同学负责原第1–2线，教师同学负责第3–4线，第5线撤销，你负责第6线。

在backend目录按README安装依赖后执行：

```powershell
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.seed_demo
..\.venv\Scripts\python.exe -m scripts.demo_analysis --auto-events --supplement
```

逐段事件为OPEN_REVIEW → SUBMIT_REVIEWS → RESOLVE，需要补评时追加SUBMIT_SUPPLEMENT；之后自动保存题目结果快照并运行学习分析，不再等待发布动作。原schema批次只保留为历史，更新后新建批次，不再使用旧批次3继续演示。

研究算法大多仍是模拟槽位；真实模式缺输入明确等待，不以模拟值代替真实结果。精确契约、JSON样例、当前数据流图见仓库的docs/design/analysis和data/analysis。


## 相似检测与复杂度分析（2026-10-28）

迁移会到 pg0009，新增 `problem_complexity_profiles` 与 `complexity_reports` 两张表（pg0007 建表，pg0009 切换到执行轨迹证据）。升级后先给题库写入规模伸缩档，再启动两个 worker：

```powershell
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.seed_complexity_profiles
```

```powershell
# 相似批次（纯计算，秒级）
..\.venv\Scripts\python.exe -m scripts.run_analysis --watch
# 复杂度测量（会真实执行学生代码）
..\.venv\Scripts\python.exe -m scripts.run_complexity --watch
```

`seed_complexity_profiles` 幂等，重复运行不会覆盖已有行。它用题库自带的 Python 参考解做**验收**：参考解要能跑通生成的输入，且工作量从最小档到最大档至少增长 1.5 倍（排除格式对了但程序提前返回的题）；不通过就降级为 `EXISTING_CASES`（不可测）并记录原因。早期入库的伸缩档可以用 `--revalidate` 重验并修正。离线核对用 `python -m scripts.validate_complexity_profiles`。

没有伸缩档或因验收失败被降级的题，报告状态是 `NOT_MEASURABLE`，明确写"无法给出结论"及原因，不做静态结构猜测。Java 目前没有精确的循环计数采集器，请求会返回 409 并说明；当前支持的采集语言是 Python、C、C++。

仅想验证状态机、不执行代码时可加 `--no-trace`：

```powershell
..\.venv\Scripts\python.exe -m scripts.run_complexity --limit 5 --no-trace
```

教师想给一整道题的全班已通过提交排队分析时用教师端「复杂度分析」页的排队按钮，对应接口 `POST /analysis/courses/{course_id}/complexity/batch`，不需要逐个请求。

两个 worker 都只处理自己的队列：`run_analysis` 不碰 JUDGE 与复杂度报告，`run_complexity` 不碰 JUDGE 与相似批次。轨迹采集有单档 10 秒、总计 60 秒的预算上限，超时会写进报告，不会无限跑。

完整链路验证（需 API 以 LOCAL 启动）：

```powershell
.venv/bin/python scripts/smoke_similarity_complexity_http.py
```

脚本读本机 `.env` 的演示口令，不打印凭据；只接受 localhost 地址；只使用合成演示账号。
