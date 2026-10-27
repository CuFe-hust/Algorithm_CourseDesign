"""Native 4K diagram of the independent sixth line. Does not read the database."""
from pathlib import Path
import build_meeting_diagrams as d

d.OUT=Path(__file__).resolve().parents[1]/'docs/assets/diagrams/analysis'
c=d.Canvas()
c.title('06','第六条线：先贯通，再研究算法','独立运行：固定输入 → 一个学生能力黑盒 → 保存并查询输出。当前只验证线路，不定义能力模型。','线路已贯通 · 黑盒实现保持原样')
def card(x,y,w,title,lines):
    c.rectangle((x,y,x+w,y+650),'#FFFFFF',d.BLUE,3,18)
    c.text(x+35,y+40,title,46,d.BLUE,bold=True,max_width=w-70)
    for i,t in enumerate(lines):c.text(x+35,y+150+i*78,t,34,max_width=w-70)
card(120,660,900,'输入从哪里来',['数据库中的题目结果快照','或：明确标记的演示样例','核对课程、版本与数据来源','复制并保存本次输入','输入hash用于复现与核对'])
c.rectangle((1350,500,2470,1480),'#152A47',radius=28)
c.text(1910,650,'学生能力分析',66,'#FFFFFF',bold=True,center=True,max_width=1000)
c.text(1910,760,'一个大黑盒',58,'#FFCB78',bold=True,center=True,max_width=1000)
for i,t in enumerate(['内部算法暂不展开','继续使用现有占位实现','先确认输入和输出能接通','论文调研后再替换实现']):
    c.text(1910,960+i*92,t,39,'#FFFFFF',center=True,max_width=1000)
card(2790,660,900,'输出保存与查询',['保存黑盒返回内容','记录输入hash与实现版本','标明模拟 / 未实现状态','查询本次输入和结果','不将占位值当作真实能力'])
c.line([(1020,980),(1350,980)],d.BLUE,6,arrow=True)
c.line([(2470,980),(2790,980)],d.BLUE,6,arrow=True)
c.rectangle((120,1680,3690,1990),'#E6EDF7',radius=20)
c.text(160,1730,'当前独立批次只有一个 ability 任务，复用现有快照、任务、结果表与 worker。',36,bold=True,max_width=3470)
c.text(160,1820,'DEMO可直接演示；真实输入缺题目结果就等待；来源和模拟标记全程保留。',34,d.MUTED,max_width=3470)
c.text(160,1900,'调用入口、输入查询、结果查询已接通。能力维度与具体算法留待后续调研决定。',34,d.MUTED,max_width=3470)
print(c.save('05-student-ability-line-4k'))
