# 分析黑盒合成契约

15插件JSON Schema、完整输入及成对输出，全部由六名合成身份生成，无真实名册或真实作答。algorithm_key对应catalog.py，输出is_mock=true。

在backend运行python -m scripts.export_analysis_contracts重新导出；不读数据库。替换指南见docs/design/analysis/black-boxes.md。NOT_IMPLEMENTED是真实模式缺实现，不得与DEMO模拟结果混淆。
