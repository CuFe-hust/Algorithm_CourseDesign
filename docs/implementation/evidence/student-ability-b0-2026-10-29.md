# 第六条线B0验收证据（2026-10-29）

- 基线 main 938a8d2；本次本地修改，未提交或推送。复用pg0006，无新增迁移。
- 首版真实算法 ability_b0 / version2；历史15槽位保留，新扩展独立注册。
- TDD：核心初次因模块未实现失败；新HTTP集成初次因入口404失败；实现后通过。

## 实际运行

- 后端全量：`python -m pytest -q --tb=short` → 169 passed, 19 skipped，168.23秒。现有Starlette/httpx弃用警告1个；19项为当前环境跳过项。
- 随后补充正式冻结来源与零布置/等待状态集成测试；最终核心+集成：`pytest tests/test_ability_b0_flow.py tests/test_ability_b0.py -q --tb=short` → 34 passed，6.18秒（含4项集成、30项核心）。此处不声称在加入最后2项后再次跑了全部套件。
- 前端：`pnpm test` → 17 files, 63 passed；`pnpm build` → vue-tsc与Vite成功。
- `git diff --check` 无输出。
- localhost真实HTTP：`python scripts/smoke_ability_b0_http.py` → passed，course1 / batch14，formal NO_REAL_ANALYSIS，demo OK，8个可见章节，未输出凭据。
- CLI实际数据库任务：course1 / batch13 COMPLETE，implementation ability_b0，is_mock=true；输入hash冻结，非随机输出。

## 浏览器

Playwright使用本机Edge无头浏览器，以.env中现有演示学生密码经真实登录页登录；未改密码、不输出token。检查桌面1600px与手机390px：

- 无pageerror；面板有真实SVG雷达。
- 未布置的数学/位运算/数组章节隐藏。
- 待评与未交章节无数据点，证据表留空，不补0。
- 分治0.0%、动态规划100.0%正常展示。
- 雷达轴使用中文章节名称；编程/主观分项及数量显示。
- 窄屏documentWidth/bodyWidth均390，无页面级横向溢出。
- 从合成演示切回正式分析，明确显示尚未生成，无演示结果残留。

本机截图（忽略目录，不提交账号会话等运行数据）：`.logs/b0-personal-panel.png`、`.logs/b0-personal-panel-mobile.png`。

## 会议材料

- docs/design/analysis/student-ability-b0.md：设计、接口、来源契约、逐步演示与重跑命令。
- docs/assets/diagrams/analysis/06-student-ability-b0-delivery-4k.png：3840×2160；同名SVG为编辑源；已经视觉检查。
- 4K图由Pillow生成，使用内置文档运行时的Pillow和项目SQLAlchemy，非运行时产品依赖；脚本为scripts/build_ability_b0_diagram.py。

## 边界

演示输入仍为合成数据，执行的B0是真实纯函数。正式编程计分、真实互评领域服务和正式课程快照仍由队友接入；正式入口缺数据明确等待，不用mock冒充。B0描述作答表现，不声称真实能力测量或置信区间。5个UNMAPPED题和部分章节权重保留复核标记。
