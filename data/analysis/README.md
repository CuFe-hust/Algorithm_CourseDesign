# 分析黑盒合成契约

15插件JSON Schema、完整输入及成对输出，全部由六名合成身份生成，无真实名册或真实作答。algorithm_key对应catalog.py，输出is_mock=true。

在backend运行python -m scripts.export_analysis_contracts重新导出；不读数据库。替换指南见docs/design/analysis/black-boxes.md。NOT_IMPLEMENTED是真实模式缺实现，不得与DEMO模拟结果混淆。

`code_similarity` 自 2026-10-28 起为真实算法输出（`winnowing_token` v2），DEMO 样例来自六份合成提交，包含名称改写后的高相似对与一个 4 成员簇；其余未实现插件仍为模拟占位。
