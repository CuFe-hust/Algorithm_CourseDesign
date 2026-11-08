# 难度感知章节模型与自主实验设计

2026-10-30接入更新：B0/D1已通过课程级冻结快照连接真实编程与互评复核来源，并提供教师生成及学生本人入口；[当前接入设计](student-ability-integration.md)。本页此前关于等待上游的说明为交付时状态。

方法依据：Papke与Wooldridge的[分数响应建模](https://www.nber.org/papers/t0147)支持对含0/1的比例结果建模；[教育Elo/多维追踪原文](https://pmc.ncbi.nlm.nih.gov/articles/PMC9796260/)提供区分学生与题目参数的背景；[PST论文](https://yxonic.github.io/pdfs/li2022pst.pdf)提供关注编程过程的依据。本实现的章节载荷、二次惩罚、优化器及诊断是本项目设计，不声称复现这些论文或商业平台的完整算法。

2026-10-29。用户授权自行设计、验证并交付最终算法与演示，不再逐项请求确认。

## 模型

mu_si=sigmoid(sum_c q_ic*theta_sc - b_i)。最小化连续分数交叉熵加learner_l2/2*sum(theta²)+item_l2/2*sum((b-anchor_i)²)，anchor_i=difficulty_scale*(teacher_level-3)。这是正则化分数响应模型，非严格二元IRT似然或贝叶斯后验；没有自动置信区间。严格正惩罚用于稳定估计和锚定量尺，不能代替真人效度验证。

用训练集拟合theta与题目难度；通过独立验证集选择惩罚和难度尺度。测试集不参与选择。迭代采用确定性坐标Newton/等价稳定凸优化，使用稳定sigmoid/softplus及有界更新。输出参考难度0上的模型期望分sigmoid(theta)，与B0历史均值分别标注。

## 产品

保持B0线路、历史快照和正式/合成隔离。新增D1独立算法/管线，输入为{learning_input:AbilityInputV2,model_parameters:{learner_l2,item_l2,difficulty_scale,max_iterations,tolerance}}。D1参数随输入冻结；改变实现或参数均新建批次。参考分只给有实际评分的章节，未布置隐藏、待评留空。正式数据仍需上游定版契约。

D1输出保持B0章节证据字段，另加baseline_value,theta,score_semantics；metadata说明模型/参数/优化与实验版本。个人面板在B0与D1间显式切换，显示模型值、原始均值及差异解释。独立过程诊断只描述首次表现、提交/错误恢复，不把次数/间隔作为能力扣分；缺数据不生成。

## 验证

- B0、无难度正则化模型D0、难度校准D1、固定难度对照（若可实现）。
- 任务：已有学生未见作答；另外单独验证新题泛化，分数均按逐题期望而非直接比较不同含义的雷达轴。
- 按学生×题目的完整记录分割，重复提交不得跨分割泄漏。校准/选择/最终评估seed隔离。
- 场景：难度影响、难度错标、非随机缺失、稀疏、模型失配/弱难度；所有场景保留，不只展示赢的。
- 指标：测试RMSE/MAE、分数预测校准、known模拟参数相关、收敛、耗时；按独立重复数据集报告配对变化。
- 合成数据只能支持受控模拟结论。若升级在某类失配数据退化，报告并给出使用边界，不删除失败场景。

## 交付

模型与单元/集成测试；可复现实验脚本和JSON/CSV/图；设计与实验报告；数据库快照→worker→artifact→本人面板的真实算法演示；没有作业总分/rating/未经校准CI。

## 最终实现与版本

算法key `ability_d1`，实现名 `difficulty_fractional`，实现版本 `2`，输入/输出契约 `ability-difficulty-v1`。版本1为内部接线验证批次；版本2补齐固定难度来源标记、缺失事件序号处理和数值映射精度，旧artifact不改写。

- `difficulty_model.fit`：只用Python标准库的稀疏坐标Newton优化器。交叉熵对线性预测子凸，严格正的二次惩罚固定量尺并给出唯一正则化最优解。每步截断并回溯验证目标下降，使用softplus防止0/1端点溢出。
- 单次扫描遍历稀疏关联。若R条成绩、L为每题非零章节数、D为活跃参数数，缓存预测子后空间O(RL+D)，T次扫描约O(T(RL+D))，回溯次数有固定上限。达到梯度容差才记为收敛，耗尽扫描预算不会伪装成功。
- 参数由独立验证数据集冻结：learner_l2=.05、item_l2=.3、difficulty_scale=.75、max_iterations=180、tolerance=1e-6、calibrate_items=true。每个新批次复制这些值入快照；历史批次不随参数文件变化。
- D1输入的章节权重仅在契约允许的十进制舍入范围内归一化为模型浮点权重；原始输入不改写，B0证据统计仍按原数值计算。
- 输出逐章的参考期望得分、theta、baseline_value与原有证据元数据；题型分项保留为原始成绩诊断，不冒充模型分项。
- 过程轨迹独立显示；本轮演示轨迹为明确标记的合成输入，不参与模型拟合。序号有缺口时不把两条记录当成相邻提交，也不重编号首次AC。

## 运行和验收

```powershell
# backend目录，使用已有演示账号及验证选定参数，创建新快照并实际执行模型
..\.venv\Scripts\python.exe -m scripts.demo_student_ability_difficulty
# 工程根，实际HTTP创建/读取与正式-演示隔离校验
.\.venv\Scripts\python.exe scripts/smoke_ability_difficulty_http.py
```

本机当前入口：`http://127.0.0.1:5173/student/courses/1/ability?demo=1&model=d1`。使用已有demo.student01，密码仅在本地.env。不同机器以CLI返回course_id为准。

页面包含：模型/B0切换、同一D1输入上的模型与原始均值双轨雷达、逐章证据与差值、编程/主观原始分项、可用时的过程观察、优化收敛与输入版本。未布置章节隐藏；待评留空；模型与B0差异不解释为学习进步。

新增接口：POST `/api/v1/analysis/courses/{id}/student-ability/difficulty-batches`（教师）；GET `/api/v1/courses/{id}/my-ability/difficulty`及`/demo`（本人）；GET `/api/v1/analysis/difficulty-contract`（登录用户读取schema）。复用原批次输入/结果查询、worker和表，无需迁移。

正式来源复用B0的课程级冻结输入契约。REAL_INPUT缺少正式上游时等待，不从实时库猜历史，也不用模拟补位。正式过程证据尚未接入时输出available=false，而不根据题分生成轨迹。

## 实验结论与边界

[完整实验报告](difficulty-experiments.md)与`data/analysis/experiments/difficulty-v1/`记录协议、所有对照、原始数据、失败场景和图表。测试集未参与选参。192次最终对照评估包括144次优化，全部收敛。

在有难度差异的已有题留出评分上，RMSE从B0的0.29530降到D1的0.12703；无真实难度时反而从0.13595升至0.13903，六次重复均退化。新题错标只胜出4/6次，不能把已有题目校准效果外推为能够纠正未知题。

这些结果验证实现和受控模拟条件，不证明真人能力或岗位效度。B0仍保留作为适用边界外的透明对照；不依据本轮测试反复调参以抹去负例。
