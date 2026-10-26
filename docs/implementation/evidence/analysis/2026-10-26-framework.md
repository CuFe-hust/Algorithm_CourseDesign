# 分析框架交付证据（2026-10-26）

## 实际范围

独立四表、pg0005、28业务表；15插件Schema与成对样例；24步骤；DEMO及REAL_INPUT数据适配；教师权限API；输入/实现版本固定、依赖快照、幂等、人工等待、租约/显式重试；普通和补评合成链路。复用现有评测，不新增源码执行器。

## 验证

- 原生Windows PostgreSQL18.6，后端pytest：128passed、19skipped（POSIX启动门实际执行用例），仅上游Starlette弃用提示。
- 前端15测试文件、51测试通过；vue-tsc与Vite构建通过，未新增分析页面。
- pg0005从教师pg0004升级，测试库升级/往返与28模型一致；真实项目库完成升级且原数据保留。
- 新分析测试含坏插件输出、自评/外部引用/重复/人数不足、聚合零分与缺失、范围隔离、延迟任务版本变更、并发领取、过期token、补评/原评分保留、权限/幂等、真实模式不借用模拟。
- 实际HTTP：登录教师/学生、catalog15、创建DEMO、学生403、五类人工事件含补评、24任务SUCCEEDED、COMPLETE、is_mock=true、formal_grade_release=false；不打印密码/token。
- CLI普通路线22SUCCEEDED+2SKIPPED；补评路线24SUCCEEDED。固定seed生成，不代表算法研究已完成。
- PNG两张3840×2160，附SVG与hash；Schema/examples只用合成数据，不读取真实名册。

## 独立审阅修复

1. 框架必须复验替换插件输出，不能只做Pydantic形状验证：已加入validation.py及回归。
2. 按题范围必须先解析所属作业再采集全部数据：已将item条件下推到所有查询，使用发布名单。
3. 固定实现名和真实版本，包括尚未就绪的任务：已在创建时保存、执行时核对；变化后要求新批次。

## 仍待完成

多数研究算法当前仅DEMO有模拟输出，REAL_INPUT返回NOT_IMPLEMENTED；真实互评、教师处置、正式成绩发布领域服务和分析面板未实现。缺交与正式编程计分政策待会议确定。原生Windows不提供当前POSIX LOCAL执行器，不能把模拟成绩当真实分数。

## 现场讲解

本机批次3保留在教师开放前，可通过demo_analysis --batch-id 3 --event OPEN_REVIEW继续；克隆后的ID不同，按运行手册新建。运行命令见../../runbooks/analysis-setup.md；会议图与讲解稿见docs/design/analysis/meeting-walkthrough.md。

追加UTC回归：数据库时区Asia/Shanghai时，批次查询和快照时间仍统一转UTC；先复现+08:00响应，再修复并验证。最后全套128passed/19POSIX-only skipped。
