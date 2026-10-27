# 分析框架运行与会议演示

日期2026-10-26。范围：任务编排、四类持久化记录、15插件契约、24步骤、六条合成链路和真实输入适配。真实互评/正式成绩发布领域服务与多数研究算法仍待后续实现。

## 启动

分析分支包含教师集成9865289和学生主干77f7cbc，迁移为pg0005（依赖pg0004）；共28张业务表。拉取代码后停旧API/worker，再按README安装依赖、启动项目PostgreSQL。不要将测试库当业务库，测试只使用algorithm_review_test。

在工程根目录PowerShell：

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.seed_demo
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端在backend运行分析worker：

```powershell
..\.venv\Scripts\python.exe -m scripts.run_analysis --watch
```

仅消费通用analysis_runs，不领取JUDGE，不执行学生源码。Linux/macOS使用自己的venv Python和相同模块命令。当前LOCAL评测使用POSIX启动门；原生Windows的driver_available(LOCAL)=false，使用MOCK和分析演示，不能声称测得真实代码资源。

## 今晚演示：先图，再一步步跑

打开[业务图](../../assets/diagrams/analysis/03-analysis-data-flow-4k.png)、[黑盒图](../../assets/diagrams/analysis/04-algorithm-black-boxes-4k.png)，按[讲解稿](../../design/analysis/meeting-walkthrough.md)介绍。

以下CLI会自行有界消费READY任务，无需watch worker。演示时可暂时停watch，便于逐步观察；不会清空真实业务表。

```powershell
..\.venv\Scripts\python.exe -m scripts.demo_analysis
```

它创建合成DEMO批次并运行到第一次人工等待，输出id。后续替换实际批次ID，每次查看输出WAITING_HUMAN：

```powershell
..\.venv\Scripts\python.exe -m scripts.demo_analysis --batch-id 3 --event OPEN_REVIEW
..\.venv\Scripts\python.exe -m scripts.demo_analysis --batch-id 3 --event SUBMIT_REVIEWS
..\.venv\Scripts\python.exe -m scripts.demo_analysis --batch-id 3 --event RESOLVE
..\.venv\Scripts\python.exe -m scripts.demo_analysis --batch-id 3 --event RELEASE
```

新建一份自动演示全流程，或者包含补评路径：

```powershell
..\.venv\Scripts\python.exe -m scripts.demo_analysis --auto-events
..\.venv\Scripts\python.exe -m scripts.demo_analysis --auto-events --supplement
```

--auto-events明确授权模拟教师/学生动作，仅DEMO可用。最终COMPLETE、is_mock=true、formal_grade_release=false。默认路线上补评两步骤SKIPPED；补评路线24步骤均完成，并保留原始评分和新聚合版本。

API打开[Swagger](http://127.0.0.1:8000/docs)，演示教师demo.teacher，密码仅在本机.env的DEMO_PASSWORD中查看。登录后可调catalog、创建DEMO、GET批次、提交demo-events；输入/状态参见[API](../../design/analysis/api.md)。

## 研究交接与验证

先读[黑盒交接](../../design/analysis/black-boxes.md)，直接使用data/analysis的合成JSON。导出命令`python -m scripts.export_analysis_contracts`不连接数据库。

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_analysis_contracts.py tests/test_analysis_examples.py tests/test_analysis_storage.py tests/test_analysis_flow.py -q
```

模型/接口变更后运行完整pytest，迁移测试会重建专用验证库。原生Windows的POSIX LOCAL执行用例明确跳过，其余权限/提交/教师/分析/迁移测试仍执行；POSIX节点应运行全部LOCAL测试。前端沿用现有界面，本轮未新增分析面板。
