"""Render 3840x2160 engineering diagrams and editable SVG, with verified schema references.

Requires Pillow and SQLAlchemy in the rendering Python environment. No database connection,
credentials, student data or external API is used. Source metadata is imported read-only.
"""
from __future__ import annotations
import csv
from functools import lru_cache
from html import escape
import json
import math
import os
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.db.base import Base
from app.db import models

W, H = 3840, 2160
OUT = ROOT / 'docs/diagrams'
BG, INK, MUTED, LINE = '#F4F7FB', '#102A43', '#53677F', '#8295AA'
BLUE, GREEN, AMBER = '#2563EB', '#059669', '#C87914'
PALE = {'#2563EB':'#EAF1FF', '#059669':'#E6F6F0', '#C87914':'#FFF2DF', '#52657B':'#EDF1F5', '#0D9488':'#E4F6F3'}
FONT = os.environ.get('DIAGRAM_FONT', 'C:/Windows/Fonts/msyh.ttc')
BOLD = os.environ.get('DIAGRAM_FONT_BOLD', 'C:/Windows/Fonts/msyhbd.ttc')


@lru_cache(None)
def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


class Canvas:
    def __init__(self):
        self.image = Image.new('RGB', (W, H), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
                    f'<rect width="{W}" height="{H}" fill="{BG}"/>']
        self.text_boxes = []
        self.edges = []

    def rectangle(self, xy, fill, outline=None, width=2, radius=0, dashed=False):
        x,y,x2,y2=xy
        self.draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=None if dashed else outline, width=width)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" rx="{radius}" fill="{fill or "none"}" stroke="{outline or "none"}" stroke-width="{width}"'+(' stroke-dasharray="14 10"' if dashed else '')+'/>')
        if dashed:
            for a,b in [((x,y),(x2,y)),((x2,y),(x2,y2)),((x2,y2),(x,y2)),((x,y2),(x,y))]:
                self.line([a,b],outline,width,dashed=True,svg=False)

    def text(self, x,y,value,size=30,color=INK,bold=False,max_width=None,center=False,background=None):
        if max_width:
            while self.draw.textlength(value,font=font(size,bold))>max_width and size>20:size-=1
            if self.draw.textlength(value,font=font(size,bold))>max_width:
                raise ValueError('Text does not fit: '+value)
        width=self.draw.textlength(value,font=font(size,bold))
        if center:x-=width/2
        if background:self.rectangle((x-10,y-4,x+width+10,y+size+8),background,radius=6)
        assert x>=0 and x+width<=W and y>=0 and y+size*1.3<=H,(value,x,y,width)
        self.draw.text((x,y),value,font=font(size,bold),fill=color,anchor='lt')
        self.svg.append(f'<text x="{x:.1f}" y="{y+size:.1f}" font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(value)}</text>')
        self.text_boxes.append((x,y,x+width,y+size,value))

    def line(self, points, color=LINE, width=3, dashed=False, arrow=False,svg=True):
        if dashed:
            for a,b in zip(points,points[1:]):
                length=math.dist(a,b)
                if not length:continue
                for start in range(0,int(length),24):
                    end=min(start+14,length)
                    self.draw.line([(a[0]+(b[0]-a[0])*start/length,a[1]+(b[1]-a[1])*start/length),
                                    (a[0]+(b[0]-a[0])*end/length,a[1]+(b[1]-a[1])*end/length)],fill=color,width=width)
        else:self.draw.line(points,fill=color,width=width,joint='curve')
        if svg:
            self.svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="none" stroke="'+color+f'" stroke-width="{width}" stroke-linejoin="round"'+(' stroke-dasharray="14 10"' if dashed else '')+'/>')
        if arrow:
            a,b=points[-2:];angle=math.atan2(b[1]-a[1],b[0]-a[0]);length=14
            triangle=[b,(b[0]-length*math.cos(angle-0.45),b[1]-length*math.sin(angle-0.45)),
                      (b[0]-length*math.cos(angle+0.45),b[1]-length*math.sin(angle+0.45))]
            self.draw.polygon(triangle,fill=color)
            if svg:self.svg.append('<polygon points="'+' '.join(f'{x:.1f},{y:.1f}' for x,y in triangle)+f'" fill="{color}"/>')

    def title(self,index,title,subtitle,badge):
        self.text(90,38,f'ALGORITHM COURSE REVIEW  /  TEAM BRIEFING  /  {index}',25,MUTED)
        self.text(90,96,title,74,bold=True)
        self.text(90,203,subtitle,32,MUTED,max_width=3650)
        self.rectangle((2680,98,3750,180),'#E6EDF7',radius=18)
        self.text(3215,126,badge,28,center=True,max_width=1000)
        self.line([(90,270),(3750,270)],'#CCD7E4',2)

    def save(self,name):
        OUT.mkdir(parents=True,exist_ok=True)
        self.image.save(OUT/(name+'.png'),optimize=True,dpi=(160,160))
        (OUT/(name+'.svg')).write_text('\n'.join(self.svg+['</svg>']),encoding='utf-8',newline='\n')
        return {'file':name+'.png','size':[W,H],'labels':len(self.text_boxes)}


NODES = [
 ('users',0,0,'用户账号',['id PK · student_no UQ','login_name UQ · full_name','status · password_hash'],'#52657B'),
 ('auth_sessions',0,1,'登录会话',['user_id FK','token_hash UQ','expires_at'],'#52657B'),
 ('student_profiles',0,2,'学生资料',['user_id FK UQ','class_id FK'],'#52657B'),
 ('classes',0,3,'行政班级',['class_code UQ','name · status'],'#52657B'),
 ('courses',1,0,'开课实例',['code UQ · name · term','created_by FK','status'],BLUE),
 ('course_members',1,1,'课程成员与角色',['course_id FK · user_id FK','UQ(course_id, user_id)','role · status'],BLUE),
 ('knowledge_points',1,2,'知识点字典',['course_id FK · code','name · status','UQ(course_id, code)'],BLUE),
 ('problems',2,0,'题目身份',['course_id FK · code','question_type','created_by FK'],BLUE),
 ('problem_versions',2,1,'题目内容版本',['problem_id FK · version_no','statement_md · difficulty_level','status · frozen_at'],BLUE),
 ('problem_version_tags',2,2,'版本与知识点',['problem_version_id FK','knowledge_point_id FK','mastery_weight'],BLUE),
 ('reference_solutions',2,3,'教师参考资料',['problem_version_id FK','language · content','created_by FK'],BLUE),
 ('test_suites',3,0,'测试集版本',['problem_version_id FK','version_no · allowed_languages','cpu_limit_ms · memory_limit_kib'],'#0D9488'),
 ('test_cases',3,1,'测试用例',['test_suite_id FK','input_text · expected_output','weight · is_public'],'#0D9488'),
 ('rubrics',3,2,'评分量表版本',['problem_version_id FK','version_no · name','status · frozen_at'],'#0D9488'),
 ('rubric_items',3,3,'评分维度',['rubric_id FK','name · max_score','description · sort_order'],'#0D9488'),
 ('assignments',4,0,'一次作业',['course_id FK · created_by FK','submission_deadline / review_deadline','submission_status'],BLUE),
 ('assignment_items',4,1,'作业中的题目',['problem_version_id FK','test_suite_id FK / rubric_id FK','max_score · score_weight · 互评人数'],BLUE),
 ('assignment_participants',4,2,'应交名单快照',['assignment_id FK · student_id FK','class_id_at_publish FK','class_name_at_publish'],BLUE),
 ('submissions',5,0,'学生正式提交',['assignment_item_id FK · student_id FK','version_no · content · language','UQ(student_id, client_request_id)'],GREEN),
 ('analysis_jobs',5,1,'代码分析任务',['submission_id FK','kind=JUDGE · status','parameters · 输入版本引用'],AMBER),
 ('judge_results',5,2,'评测结果',['job_id FK UQ · submission_id FK UQ','verdict · is_mock','CPU ms / 内存 KiB（模拟为空）'],AMBER),
]
BOXES={name:(90+col*620,430+row*360,650+col*620,690+row*360) for name,col,row,*_ in NODES}


def schema_diagram():
    canvas=Canvas()
    canvas.title('01','数据库模式图','当前数据库现状：配置、作答、计算结果分别保存；所有模块共用同一套事实。','已实现 21 张业务表  ·  PostgreSQL  ·  迁移 pg0001')
    headings=[('账户与身份','公共基础 / T导入'),('课程与知识点','T配置 / 公共权限'),('题库与内容版本','T配置 / S读取'),('题型专用配置','T配置 / A计算'),('作业与应交名单','T发布 / 固定依据'),('作答与计算结果','S提交 / A消费')]
    for i,(title,sub) in enumerate(headings):
        x=90+620*i
        canvas.text(x,312,title,35,bold=True,max_width=560)
        canvas.text(x,363,sub,24,MUTED,max_width=560)
    foreign_keys={(fk.column.table.name,table.name,fk.parent.name) for table in Base.metadata.tables.values() for fk in table.foreign_keys}
    def edge(parent,child,fk,points,label=None,at=None):
        assert (parent,child,fk) in foreign_keys,(parent,child,fk)
        canvas.line(points,LINE,3,arrow=True)
        if label:canvas.text(*at,label,22,MUTED,background=BG)
        canvas.edges.append((parent,child,fk))
    def vertical(a,b,fk):
        aa,bb=BOXES[a],BOXES[b]
        if bb[1]>aa[1]:pts=[((aa[0]+aa[2])/2,aa[3]),((bb[0]+bb[2])/2,bb[1])]
        else:pts=[((aa[0]+aa[2])/2,aa[1]),((bb[0]+bb[2])/2,bb[3])]
        edge(a,b,fk,pts)
    vertical('users','auth_sessions','user_id')
    vertical('classes','student_profiles','class_id')
    edge('users','student_profiles','user_id',[(650,550),(668,550),(668,1280),(650,1280)])
    vertical('courses','course_members','course_id')
    edge('users','course_members','user_id',[(650,605),(690,605),(690,920),(710,920)])
    edge('courses','knowledge_points','course_id',[(1270,560),(1288,560),(1288,1280),(1270,1280)])
    edge('courses','problems','course_id',[(1270,550),(1330,550)])
    vertical('problems','problem_versions','problem_id')
    vertical('problem_versions','problem_version_tags','problem_version_id')
    edge('knowledge_points','problem_version_tags','knowledge_point_id',[(1270,1280),(1330,1280)])
    edge('problem_versions','reference_solutions','problem_version_id',[(1890,930),(1906,930),(1906,1640),(1890,1640)])
    edge('problem_versions','test_suites','problem_version_id',[(1890,850),(1920,850),(1920,550),(1950,550)])
    edge('problem_versions','rubrics','problem_version_id',[(1890,1000),(1936,1000),(1936,1280),(1950,1280)])
    vertical('test_suites','test_cases','test_suite_id')
    vertical('rubrics','rubric_items','rubric_id')
    edge('courses','assignments','course_id',[(1050,430),(1050,404),(2850,404),(2850,430)])
    vertical('assignments','assignment_items','assignment_id')
    edge('problem_versions','assignment_items','problem_version_id',[(1750,790),(1750,745),(2730,745),(2730,790)])
    edge('test_suites','assignment_items','test_suite_id',[(2510,550),(2530,550),(2530,955),(2570,955)])
    edge('rubrics','assignment_items','rubric_id',[(2510,1280),(2548,1280),(2548,1005),(2570,1005)])
    edge('assignments','assignment_participants','assignment_id',[(3130,550),(3148,550),(3148,1280),(3130,1280)])
    edge('assignment_items','submissions','assignment_item_id',[(3130,920),(3168,920),(3168,550),(3190,550)])
    vertical('submissions','analysis_jobs','submission_id')
    vertical('analysis_jobs','judge_results','job_id')
    edge('submissions','judge_results','submission_id',[(3750,605),(3780,605),(3780,1280),(3750,1280)])
    assert set(BOXES)==set(Base.metadata.tables), 'Diagram must show all current business tables.'
    for name,col,row,title,fields,color in NODES:
        x,y,x2,y2=BOXES[name]
        canvas.rectangle((x,y,x2,y2),'#FFFFFF','#D4DFEA',2,18)
        canvas.rectangle((x+2,y+2,x2-2,y+10),color,radius=4)
        canvas.text(x+24,y+28,title,34,color,bold=True,max_width=512)
        canvas.text(x+24,y+77,name,27,INK,max_width=512)
        canvas.line([(x+24,y+119),(x2-24,y+119)],'#E0E7EF',2)
        for i,value in enumerate(fields):canvas.text(x+24,y+142+38*i,value,25,MUTED,max_width=512)
    notes=[(1,'权限跟着课程走',['角色取 course_members','名单决定本次作业能否提交','学生端只看本人有权访问的数据']),
           (4,'发布固定依据',['题目 / 测试集 / 量表版本','应交学生与当时班级','修改不覆盖历史作答']),
           (5,'当前只模拟代码评测',['MOCK_ACCEPTED 不等于 AC','is_mock=true；资源为空','主观答案等待下一阶段互评'])]
    for col,title,lines in notes:
        x=90+col*620;y=1538
        canvas.line([(x+10,y),(x+10,y+185)],AMBER if col==5 else BLUE,5)
        canvas.text(x+34,y+4,title,32,bold=True,max_width=500)
        for i,line in enumerate(lines):canvas.text(x+34,y+63+i*41,line,26,MUTED,max_width=500)
    canvas.text(90,1840,'讲解主线：课程 → 作业题目 → 提交版本 → 任务 → 结果',36,bold=True)
    canvas.text(90,1900,'箭头：被引用表 → 引用表（通常 1:N）；带唯一外键为 1:0..1。各表都有 id 主键和 created_at。',28,MUTED,max_width=3650)
    canvas.rectangle((90,1960,3750,2070),'#FFF0DB',radius=14)
    canvas.text(120,1980,'下一阶段 A01：新增评审批次 / 任务 / 原始评分；再接聚合、异常与正式成绩发布。上述表当前尚未创建。',30,'#84500E',max_width=3590)
    canvas.text(120,2025,'本图列全 21 表，只绘制主干关系；操作者等辅助外键见完整 CSV 和数据字典。',26,'#84500E')
    canvas.text(90,2110,'PK 主键   UQ 唯一约束   FK 外键   ·   三人各用本地副本，通过模型、迁移和契约保持一致。',25,MUTED)
    info=canvas.save('01-database-schema-4k')
    info['tables']=len(BOXES);info['drawn_relationships']=len(canvas.edges);info['actual_foreign_keys']=len(foreign_keys)
    return info


def interaction_diagram():
    c=Canvas()
    c.title('02','交互流程与三人分工','数据库底座已就绪；教师和学生做业务入口，分析逐步把占位流程替换成真实实现。','实线：当前 API    虚线：下一阶段流程')
    xs=[120,1390,2660];width=1060;ys=[430,790,1150,1510];height=250
    groups=[('教师模块 · 队友 T',BLUE),('学生模块 · 队友 S',GREEN),('数据库与分析 · 你 A',AMBER)]
    for x,(title,color) in zip(xs,groups):
        c.rectangle((x,305,x+width,390),PALE[color],radius=16)
        c.text(x+28,329,title,38,color,bold=True,max_width=1000)
    cards=[
      (0,0,True,'名单 / 题库 / 作业发布',['上传 CSV、四类题与量表','发布时固定版本与应交名单'],'待 T01–T03 · 已有全量快照 · 写入入口待接'),
      (0,1,False,'查看提交过程',['按课程查询，限定任课范围','查看作答版本、源码与模拟状态'],'已实现 API · 教师页面待接'),
      (0,2,True,'预览分配 → 确认开放互评',['查看负载、真实映射与无解原因','教师确认后正式生成评审任务'],'待 T05 + A01'),
      (0,3,True,'复核证据 → 确认发布',['保留 / 降权 / 作废补评 / 改分','实际变更调用分析服务并留痕'],'待 T05 + A02 / A03'),
      (1,0,False,'登录 → 选课 → 读取题目',['角色取当前课程，不硬编码 ID','只读学生可见题干、样例与量表'],'已实现 API · 页面待 S01'),
      (1,1,False,'提交代码 / 主观答案',['版本入库，重试复用幂等键','代码排队；主观题返回待互评'],'已实现 API · 页面待 S01 / S02'),
      (1,2,True,'匿名任务 → 分项分数与评语',['只看本人任务，隐藏作者身份','校验量表、截止与任务归属'],'待 S03 · 依赖 A01'),
      (1,3,True,'查看已发布成绩与反馈',['只看本人结果与匿名修改建议','区分未交、待评、模拟和正式'],'待 S04 · 依赖 A02 / A03'),
      (2,0,False,'数据库底座 / 统一契约',['21 表、迁移、合成种子与权限','同一套字段、API 与输入输出'],'已完成 · 你维护共享结构'),
      (2,1,False,'代码任务 → 持久化模拟结果',['读取固定提交与测试集引用','MOCK_ACCEPTED；未执行源码'],'已完成 · 后续接真实沙箱'),
      (2,2,True,'冻结答案 → 匹配 → 任务',['先做数据、状态和受约束基线','复杂匹配算法后续替换'],'你下一步：A01'),
      (2,3,True,'聚合 / 检测 → 处置 → 发布',['先稳定流程、证据和结果版本','再三人并行研究核心算法'],'后续 A02 / A03；A04 真实评测'),
    ]
    def arrow(points,label,at,planned=False):
        c.line(points,AMBER if planned else '#637A93',4,dashed=planned,arrow=True)
        if label:c.text(*at,label,25,'#84500E' if planned else MUTED,center=True,background=BG)
    arrow([(1180,550),(1390,550)],'作业 / 题目',(1285,510),True)
    arrow([(1920,680),(1920,790)],'作答',(1990,720))
    arrow([(2450,860),(2660,860)],'代码任务',(2555,820))
    arrow([(2660,980),(2450,980)],'模拟结果',(2555,940))
    arrow([(1390,920),(1180,920)],'提交查询',(1285,880))
    arrow([(650,1150),(650,1105),(3190,1105),(3190,1150)],'请求预览 / 开放',(1920,1070),True)
    arrow([(2660,1225),(2450,1225)],'匿名任务',(2555,1185),True)
    arrow([(2450,1350),(2660,1350)],'原始评分',(2555,1310),True)
    arrow([(3190,1400),(3190,1510)],None,(3280,1440),True)
    arrow([(3290,1510),(3290,1460),(650,1460),(650,1510)],'候选成绩 + 异常证据',(1920,1425),True)
    arrow([(650,1760),(650,1820),(3190,1820),(3190,1760)],'教师决定 → 分析执行',(1920,1783),True)
    arrow([(2660,1670),(2450,1670)],'发布结果',(2555,1630),True)
    for col,row,planned,title,lines,badge in cards:
        x,y=xs[col],ys[row];color=groups[col][1]
        c.rectangle((x,y,x+width,y+height),'#FFFFFF',color,3,16,dashed=planned)
        c.text(x+28,y+28,title,37,color,bold=True,max_width=1000)
        for i,value in enumerate(lines):c.text(x+28,y+95+44*i,value,30,INK,max_width=1000)
        c.rectangle((x+22,y+193,x+width-22,y+235),PALE[color],radius=8)
        c.text(x+36,y+201,badge,25,color,max_width=970)
    c.rectangle((120,1880,3720,2040),'#E5ECF5',radius=18)
    c.text(155,1908,'共享 PostgreSQL：当前已保存配置 / 名单 / 提交 / 代码任务 / 模拟结果',34,bold=True,max_width=3500)
    c.text(155,1966,'后续新增互评、聚合、异常与发布记录；所有箭头都经统一后端，浏览器不直连数据库。',29,MUTED,max_width=3500)
    c.text(120,2090,'今晚讲解：先演示实线最小链路，再确认 T00 / S01 / A01；复杂算法研究在流程稳定后并行认领。',28,MUTED,max_width=3600)
    return c.save('02-interaction-flow-4k')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'database-foreign-keys.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file,lineterminator='\n');writer.writerow(['child_table','child_column','parent_table','parent_column'])
        for table in Base.metadata.sorted_tables:
            for fk in sorted(table.foreign_keys,key=lambda fk:fk.parent.name):
                writer.writerow([table.name,fk.parent.name,fk.column.table.name,fk.column.name])
    reports=[schema_diagram(),interaction_diagram()]
    (OUT/'manifest.json').write_text(json.dumps({'resolution':[W,H],'diagrams':reports},ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    print(json.dumps(reports,ensure_ascii=True))


if __name__=='__main__':main()
