# 当前分析流程（2026-10-27）

2026-10-29新增：[B0与个人面板4K图](06-student-ability-b0-delivery-4k.png)、[可编辑SVG](06-student-ability-b0-delivery-4k.svg)。新图反映真实B0和面板，旧05图为历史黑盒阶段；演示与契约见 `docs/design/analysis/student-ability-b0.md`。

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
