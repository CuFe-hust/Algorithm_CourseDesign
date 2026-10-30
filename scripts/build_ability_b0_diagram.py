"""Render B0 delivery architecture as native 3840x2160 PNG and editable SVG."""
from pathlib import Path
import build_meeting_diagrams as d

d.OUT=Path(__file__).resolve().parents[1]/'docs/assets/diagrams/analysis'
c=d.Canvas()
c.title('07','第六条线：B0 与个人面板','章节作答表现：冻结输入 → 真实计算 → 保存结果 → 本人读取；合成演示与正式数据分开。','2026-10-29 · 会议交付')
cards=[('01 逐题结果',['编程题 + 主观题','单题归一化成绩','未交 / 待评不补零','正式评分由上游负责']),
       ('02 冻结本次输入',['章节词表与120题映射','学生名单与已布置关系','成绩、状态、政策版本','保存输入快照与 hash']),
       ('03 B0 纯函数',['逐学生、逐章节聚合','Σ(章节权重 × 单题成绩)','再除以有效章节权重和','不求作业总分 / rating']),
       ('04 结果持久化',['现有分析 worker 执行','记录实现版本与输入 hash','artifact 保存真实计算值','查询不重算、不生成随机值']),
       ('05 个人面板',['本人只读 API + Vue','未布置的章节隐藏','待评无证据留空，不补零','雷达 + 题型分项 + 证据表'])]
for i,(title,lines) in enumerate(cards):
    x=100+i*740
    c.rectangle((x,520,x+650,1180),'#FFFFFF',d.BLUE,3,20)
    c.text(x+30,570,title,42,d.BLUE,bold=True,max_width=590)
    for j,line in enumerate(lines):c.text(x+30,700+j*100,line,32,max_width=590)
    if i<4:c.line([(x+650,850),(x+740,850)],d.BLUE,5,arrow=True)
c.rectangle((100,1320,3710,1580),'#E6F6F0',radius=20)
c.text(140,1370,'已实现：真实 B0、数据库快照/结果、本人权限、章节雷达、明确标记的合成演示。',40,d.GREEN,bold=True,max_width=3500)
c.text(140,1465,'固定11章词表；页面只显示已布置章节。两类题不额外各占50%，保留分项结果。',35,max_width=3500)
c.rectangle((100,1680,3710,1980),'#FFF2DF',radius=20)
c.text(140,1730,'证据边界：这是课程章节作答表现，不是掌握概率、真实能力或岗位胜任力。',38,d.AMBER,bold=True,max_width=3500)
c.text(140,1825,'待队友接入：正式编程计分、真实互评聚合与带完整元数据的课程结果快照。',35,max_width=3500)
c.text(140,1900,'模拟数据可以演示全链路；正式面板缺少上游数据时明确等待，不用模拟结果顶替。',33,max_width=3500)
print(c.save('06-student-ability-b0-delivery-4k'))
