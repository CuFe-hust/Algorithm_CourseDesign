# D1算法、实验与演示验收证据

2026-10-29。用户授权自行设计、实验验证并交付最终算法及演示；全部改动本地保留，未提交推送，未新增数据库迁移或重置密码。

## 实验

- 80模拟学生×66题×11章，6种场景、每场景6个独立最终种子，另有2种整题留出场景。
- 72次D1验证拟合+36次独立D0验证拟合；选择参数后才生成最终数据。
- 192次最终评估中48次B0不需拟合，144次优化全部收敛，最多134/180扫描；完整实验99.26秒。
- 固定参数learner_l2=.05,item_l2=.3,difficulty_scale=.75,max_iterations180,tolerance1e-6。
- 实验源代码/核心SHA-256、验证/最终seed隔离、192原始结果、每组6个重复及汇总均值均由主会话独立审计通过。
- 难度有信号：B0 RMSE .29530，D1 .12703；无真实难度：B0 .13595，D1 .13903，后者6/6次退化。新题教师错标仅4/6次胜出，全部负例保留。
- Matplotlib从冻结summary.json生成3840×2160PNG和SVG，无重新拟合。离线画图依赖位于忽略目录.logs/plot-runtime，未增加产品依赖。

## 自动化与评审

- 核心先看到50个未实现失败，再实现并50通过。
- 新D1入口先因404失败，再实现通过；映射小数精度、固定难度来源、缺失提交序号分别有红绿回归。
- 后端全量232 passed,19 skipped，195.08秒（当时收集的测试）；随后最终核心/适配/实验/新旧集成组合67 passed，12.10秒。没有把未重跑全量后的新增项包装成全量结果。
- 前端最终71 tests passed，生产构建与类型检查通过。
- 独立审查未发现阻塞，提出2项边界问题均修复并测试：固定难度不能声称校准；序号缺口不能伪装相邻提交。
- git diff --check通过。

## 实际运行

- 真实localhost HTTP smoke通过：course1,batch17,method DIFFICULTY_FRACTIONAL，参数冻结、converged=true、12个过程题；正式投影无模拟回退。
- 最终算法注册ability_d1 / difficulty_fractional / version2。内部version1已完成批次保留，不改历史artifact。
- Edge真实登录页登录已有demo.student01；未打印密码/token；桌面D1页面无pageerror、雷达和原均值对照存在，未布置章节隐藏、空分无数据点。
- 390px窄屏document/body均390；正式/演示切换后无合成结果残留。
- 截图保留于忽略目录.logs/difficulty-personal-panel.png及mobile版本。

## 交付入口

- 页面：http://127.0.0.1:5173/student/courses/1/ability?demo=1&model=d1
- 设计：docs/design/analysis/student-ability-difficulty-model.md
- 实验报告：docs/design/analysis/difficulty-experiments.md
- 原始协议与数据：data/analysis/experiments/difficulty-v1/
- 复现：backend下python -m scripts.experiment_ability_difficulty；演示：python -m scripts.demo_student_ability_difficulty。

演示成绩及过程是标明来源的合成输入，实际执行真实算法。当前结果验证受控模拟条件，不代表已验证真人能力或岗位效度。正式评分与互评领域接入仍按原边界等待。
