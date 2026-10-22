# 教师端实测界面

采集日期：2026-10-22（北京时间）。页面运行于本机 Vue 开发服务，数据来自隔离 PostgreSQL 演示库，全部为合成身份与验收题目。

| 文件 | 展示内容 |
|---|---|
| [01-course-overview.jpg](01-course-overview.jpg) | 课程选择、真实统计、题型分布与快捷入口 |
| [02-student-import-preview.jpg](02-student-import-preview.jpg) | 实际选择 CSV 后的逐行预览、处理方式、汇总与确认按钮 |
| [03-reference-code.jpg](03-reference-code.jpg) | 已冻结编程题的教师专用标准代码和版本记录 |

名册截图中的 `00188001`、`00188002` 为专门创建的合成学号；“验收学生甲/乙”为合成姓名。截图不含真实名册、密码、访问令牌或本机私有配置。题目与人数会随本机合成验收数据增加而变化，其他成员首次运行演示种子的计数不必与截图相同。

这些图片仅是开发验收证据。功能边界与复现步骤以 [teacher_setup.md](../../teacher_setup.md) 为准。
