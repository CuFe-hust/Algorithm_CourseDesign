# 当前分析流程（2026-10-27）

## 2026-10-29 晚间会议图（全部3840×2160）

1. [六条路线总览](07-meeting-six-routes-4k.png)：原编号与分工，第5线撤销，第6线的输入依赖。
2. [第六线算法架构主图](08-meeting-d1-algorithm-architecture-4k.png)：输入、冻结、B0/D1/过程分支、联合迭代及输出。
3. [雷达维度与数值来源](09-meeting-radar-dimensions-4k.png)：11章词表、混合题型、实际合成例子、缺失轴。
4. [引入的改进与对应问题](10-meeting-model-improvements-4k.png)：模型/工程贡献、对照证据和负例。

逐图讲解与问答见[讲图提纲](../../../design/analysis/meeting-d1-talk-track.md)。只讲一张时使用第2张。旧05/06图保留历史阶段说明，不代表当前D1仍是占位黑盒。

渲染源为 `scripts/build_ability_meeting_figures.py`；只读输入为章节词表、冻结实验汇总和 `meeting-d1-demo-data.json`。后者来自明确标记为合成的已保存批次，不含学生姓名、学号或个人标识。尺寸、sha256与图中文字计数见 `meeting-figures-manifest.json`。

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
