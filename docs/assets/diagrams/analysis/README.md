# 分析模块会议图（设计稿）

日期2026-10-26。两图均为3840×2160，原生绘制；附可编辑SVG。当前状态是设计待确认，新分析框架尚未实现。图中的“已有”依据main 77f7cbc的学生LOCAL评测及已有查询，教师最新接入参照独立分支9865289。

- [六条业务链路 PNG](03-analysis-data-flow-4k.png) / [SVG](03-analysis-data-flow-4k.svg)：串行、并行条件、人工等待、反馈与汇合点。
- [算法黑盒输入输出 PNG](04-algorithm-black-boxes-4k.png) / [SVG](04-algorithm-black-boxes-4k.svg)：15个插件槽位，其中JUDGE复用、基础统计优先用规则，其余可选择研究实现。
- [完整设计与依赖表](../../../superpowers/specs/2026-10-26-analysis-framework-design.md)：输入输出、范围、版本、拟新增持久化、拟定接口及验收。
- [会议讲解稿](../../../design/analysis/meeting-walkthrough.md)：建议讲解顺序及认领问题。

六条线是业务场景分组，不是六个微服务，也不等于每条都必须并行执行。异常时长不依赖初步聚合；学习行为不依赖成绩。图中的聚合/检测框是概览，精确依赖以设计表为准。

DEMO与真实输入模式分开，人工节点不能自动跳过；真实缺数据就等待，未实现就明确返回。新分析接口、真实互评与成绩发布都不能依据本图当作已经上线。

重绘：在仓库根执行`python scripts/build_analysis_diagrams.py`，依赖Pillow、SQLAlchemy及已有制图字体；不连接数据库、不读取凭据或名册。PNG SHA256见manifest.json。
