"""Reproducible 4K technical briefing figures. Reads only committed synthetic snapshots.

Uses Pillow and the existing diagram canvas. No database access or personal data.
Final outputs are PNG; layout/font bounds and actual source metrics are checked.
"""
from pathlib import Path
import json
import math
import hashlib
from PIL import ImageFont
import build_meeting_diagrams as d

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/assets/diagrams/analysis'
BLUE,TEAL,AMBER,INK,MUTED,GRAY='#2563EB','#087D8C','#B46D17','#102A43','#53677F','#8295AA'
WHITE,PALE,TPALE,AP='#FFFFFF','#EAF1FF','#E7F4F4','#FFF3E3'
DEMO=json.loads((OUT/'meeting-d1-demo-data.json').read_text(encoding='utf-8'))
assert DEMO['is_mock'] and DEMO['source_kind']=='SYNTHETIC_FIXTURE'
TAX=json.loads((ROOT/'data/analysis/chapter-taxonomy.json').read_text(encoding='utf-8'))['axes']
SUMMARY=json.loads((ROOT/'data/analysis/experiments/difficulty-v1/summary.json').read_text(encoding='utf-8'))
BRAND=Path('C:/Users/hwm20/.codex/skills/canvas-design/canvas-fonts/BricolageGrotesque-Bold.ttf')


def metric(scenario,model):
    return next(r['rmse_mean'] for r in SUMMARY if r['task']=='known_item' and r['scenario']==scenario and r['model']==model)


def fmt(v):return '—' if v is None else f'{float(v)*100:.1f}%'


class Canvas(d.Canvas):
    def header(self,seq,title,subtitle):
        face=ImageFont.truetype(str(BRAND),29) if BRAND.exists() else d.font(29,True)
        self.draw.text((110,55),'ALGOCLASS / ALGORITHM DESIGN BRIEFING',font=face,fill=MUTED,anchor='lt')
        self.text(110,117,title,78,INK,bold=True,max_width=3350)
        self.text(110,228,subtitle,35,MUTED,max_width=3600)
        self.text(3700,60,seq,36,BLUE,center=True)
        self.line([(110,298),(3730,298)],'#CCD7E4',2)
    def footer(self,text):
        self.line([(110,2050),(3730,2050)],'#CCD7E4',2)
        self.text(110,2085,text,27,MUTED,max_width=3600)
    def save_png(self,name):
        OUT.mkdir(parents=True,exist_ok=True)
        path=OUT/(name+'.png')
        self.image.save(path,optimize=True,dpi=(160,160))
        return dict(file=path.name,width=3840,height=2160,text_elements=len(self.text_boxes),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def card(c,x,y,w,h,title,color=BLUE,fill=WHITE,size=43):
    c.rectangle((x,y,x+w,y+h),fill,color,3,22)
    c.text(x+32,y+30,title,size,color,bold=True,max_width=w-64)


def lines(c,x,y,values,size=34,gap=65,width=800,color=INK):
    for j,t in enumerate(values):c.text(x,y+j*gap,t,size,color,max_width=width)


def pill(c,x,y,w,text,color=BLUE,fill=PALE):
    c.rectangle((x,y,x+w,y+66),fill,radius=14)
    c.text(x+w/2,y+19,text,30,color,bold=True,center=True,max_width=w-30)


def radar(c,cx,cy,r,rows,label_r=None):
    n=len(rows); label_r=label_r or r+90
    def point(index,value,radius=r):
        a=-math.pi/2+index*2*math.pi/n
        return (cx+math.cos(a)*radius*value,cy+math.sin(a)*radius*value)
    for level in (.25,.5,.75,1):
        pts=[point(i,level) for i in range(n)]
        c.line(pts+[pts[0]],'#D6E3F3',3)
    for i,e in enumerate(rows):
        c.line([(cx,cy),point(i,1)],'#E1E8F1',2)
        x,y=point(i,1,label_r)
        c.text(x,y-12,e['dimension_label'],31,MUTED,center=True,max_width=270)
        if e['value'] is None:c.text(x,y+30,'无有效评分',24,AMBER,center=True,max_width=270)
    for field,color,width in [('baseline_value',GRAY,4),('value',BLUE,6)]:
        for i,e in enumerate(rows):
            nxt=rows[(i+1)%n]
            if e[field] is not None and nxt[field] is not None:
                c.line([point(i,float(e[field])),point((i+1)%n,float(nxt[field]))],color,width,dashed=field=='baseline_value')
        for i,e in enumerate(rows):
            if e[field] is None:continue
            x,y=point(i,float(e[field]));rr=11 if field=='value' else 13
            c.draw.ellipse((x-rr,y-rr,x+rr,y+rr),fill=color if field=='value' else WHITE,outline=color,width=4)
    for level in (0,.5,1):c.text(cx+15,cy-r*level-10,f'{level:g}',24,GRAY)


def overview():
    c=Canvas();c.header('01 / 04','六条路线：第六线在系统中的位置','沿用会议分工与原始编号。第5线已取消；路线编号不代表所有任务必须依次执行。')
    rows=[
      (1,370,'编程评测线','学生端同学',['代码 + 测试版本','已有评测 → 单题计分','编程题结果'],BLUE),
      (2,670,'内容证据线','学生端同学',['同题代码 / 主观答案','相似性 / AI辅助信号','供教师复核的证据'],BLUE),
      (3,970,'主观互评线','教师端同学',['冻结答案与评审人群','匹配 → 开放 → 学生评阅','原始互评分'],AMBER),
      (4,1270,'聚合与异常线','教师端同学',['原始评价 + 历史','聚合 / 异常 → 人工复核','主观题定版结果'],AMBER),
      (6,1740,'学习分析线','我负责：本次重点',['前序定版的单题结果','B0 / D1 / 过程观察','本人雷达 + 证据表'],TEAL)]
    xs=[680,1460,2310];ws=[620,700,660]
    for number,y,title,owner,stages,color in rows:
        c.rectangle((110,y,2990,y+220),TPALE if number==6 else '#FFFFFF',color if number==6 else '#D7E0EB',3,20)
        c.text(145,y+34,f'{number:02}  {title}',42,color,bold=True,max_width=490)
        c.text(145,y+113,owner,31,MUTED,max_width=490)
        for x,w,text in zip(xs,ws,stages):
            c.rectangle((x,y+48,x+w,y+165),TPALE if number==6 else '#F2F6FC',radius=14)
            c.text(x+w/2,y+88,text,34,color,center=True,max_width=w-35)
        for i in range(2):c.line([(xs[i]+ws[i],y+108),(xs[i+1],y+108)],color,4,arrow=True)
    c.line([(2635,1190),(2635,1230),(990,1230),(990,1270)],AMBER,4,arrow=True)
    c.rectangle((110,1570,2990,1670),'#E9EDF2',radius=18)
    c.text(150,1597,'05  作业总分线：已撤销，不聚合作业总分，不构成第六线的前置条件。',37,MUTED,bold=True,max_width=2780)
    card(c,3100,370,630,650,'如何理解依赖',TEAL,TPALE,43)
    lines(c,3135,485,['01 / 04提供单题结果','第6线依赖定版题分','第2线可独立产出证据','内容信号不自动扣分','第3 / 4线含人工节点'],33,87,550)
    card(c,3100,1100,630,860,'今晚重点讲第六线',TEAL,WHITE,41)
    lines(c,3135,1225,['输入是什么？','模型内部怎样计算？','11个雷达轴从何而来？','B0与D1分别说明什么？','引入了哪些改进？','哪些场景有效或失效？'],32,105,550)
    c.footer('系统事实与算法结果通过数据库快照交接；图示依赖不表示当前已实现多worker并行。')
    return c.save_png('07-meeting-six-routes-4k')


def architecture():
    c=Canvas();c.header('02 / 04','第六条线：学生章节表现分析算法架构','同一冻结输入，三路逻辑分支；核心是学生章节参数与题目难度的联合拟合。')
    card(c,110,380,770,1390,'输入：逐题证据与语义',BLUE)
    lines(c,150,510,['① 定版成绩 y ∈ [0,1]','编程 + 分析 + 证明 + 问答','② 学生名单 / 已布置题目','区分未布置、未交、待评','③ 题目 → 章节权重 q','来自文件夹与逐题映射','④ 教师难度 d ∈ {1…5}','只作先验，不是已校准难度','⑤ 结果 / 计分 / 映射版本'],34,102,690)
    c.rectangle((145,1480,845,1705),PALE,radius=16)
    c.text(180,1520,'先校验，再冻结',43,BLUE,bold=True,max_width=620)
    lines(c,180,1603,['输入快照 + hash + 模型参数'],32,60,620)
    c.line([(880,1050),(970,1050)],BLUE,5,arrow=True)
    c.line([(970,525),(970,1595)],BLUE,4)
    for y in (525,1050,1595):c.line([(970,y),(1060,y)],BLUE,4,arrow=True)
    card(c,1060,380,1630,250,'B0  描述性基线',BLUE,PALE)
    lines(c,1100,475,['已评分题的章节加权均值：Σ(q × y) / Σq','回答：在本次已评分题目上表现怎样？'],34,66,1545)
    card(c,1060,720,1630,665,'D1  难度感知分数响应模型',TEAL,TPALE,44)
    c.text(1100,815,'预期得分 μ = sigmoid(Σ q·θ − b)',45,TEAL,bold=True,max_width=1550)
    card(c,1110,920,620,180,'学生章节参数 θ',TEAL,WHITE,39)
    c.text(1145,1010,'当前证据下的章节水平参数',31,MUTED,max_width=550)
    card(c,2010,920,620,180,'题目难度参数 b',TEAL,WHITE,39)
    c.text(2045,1010,'围绕教师难度先验校准',31,MUTED,max_width=550)
    c.text(1870,914,'联合迭代',32,TEAL,bold=True,center=True)
    c.line([(1750,990),(1990,990)],TEAL,5,arrow=True)
    c.line([(1990,1060),(1750,1060)],TEAL,5,arrow=True)
    c.text(1105,1150,'拟合目标：部分分交叉熵 + 学生参数惩罚 + 题目偏移惩罚',34,INK,bold=True,max_width=1540)
    c.text(1105,1230,'稀疏坐标Newton → 更新预测缓存 → 检查梯度收敛',35,TEAL,max_width=1540)
    c.text(1105,1300,'0 / 1端点稳定；正则化限制小样本与极端分数的参数发散',31,MUTED,max_width=1540)
    card(c,1060,1480,1630,290,'独立过程观察',AMBER,AP)
    lines(c,1100,1580,['提交次数 / 首次AC序号 / 首次、最近与最佳观测分','补充解释修改轨迹；不进入D1损失，不加成章节分'],33,75,1540)
    c.line([(2780,525),(2780,1595)],TEAL,4)
    for y in (525,1050,1595):c.line([(2690,y),(2780,y)],TEAL,4,arrow=True)
    c.line([(2780,1050),(2880,1050)],TEAL,5,arrow=True)
    card(c,2880,380,850,1390,'输出：每生 × 每章',BLUE)
    lines(c,2920,500,['模型参考分 σ(θ)','原始均值 B0 / 类型分项','题数 / 覆盖 / 缺失原因','优化状态 / 参数 / 版本'],36,86,770)
    c.rectangle((2920,930,3690,1100),PALE,radius=16)
    c.text(3305,965,'保存 artifact → 本人API',36,BLUE,bold=True,center=True,max_width=700)
    c.text(3305,1035,'刷新读取已保存结果，不重新随机生成',29,MUTED,center=True,max_width=700)
    rows=[e for e in DEMO['estimates'] if e['status']!='NOT_COVERED']
    radar(c,3305,1380,190,rows,260)
    c.text(3305,1695,'章节雷达 + 原始均值对照 + 证据表',29,BLUE,center=True,max_width=760)
    c.rectangle((110,1850,3730,1988),'#E6EDF7',radius=20)
    c.text(155,1892,'串行：冻结 → 计算 → 保存 → 本人读取；D1内部联合迭代，过程观察是独立分支。',40,INK,bold=True,max_width=3510)
    c.footer('算法反映：当前课程证据下的章节模型参考表现；不等同于真实能力、掌握概率或岗位胜任力。')
    return c.save_png('08-meeting-d1-algorithm-architecture-4k')


def dimensions():
    c=Canvas();c.header('03 / 04','雷达图：维度从哪里来，数值代表什么','章节是内容维度；B0是原始表现，D1是参考难度下的模型表现，两者不是同一个量。')
    card(c,110,380,1090,1340,'第一步：题库文件夹 → 11章词表',BLUE)
    for i,axis in enumerate(TAX):
        y=500+i*77
        c.text(150,y,axis['code'],30,BLUE,bold=True,max_width=130)
        c.text(315,y,axis['name'],35,INK,max_width=800)
    c.text(150,1430,'70编程题按目录归属；50主观题逐题映射',32,INK,max_width=1000)
    c.text(150,1510,'45主观题已映射，5题暂不进入章节雷达',31,MUTED,max_width=1000)
    c.text(150,1590,'跨章节权重保留依据与复核标记',31,MUTED,max_width=1000)
    c.line([(1200,1035),(1320,1035)],BLUE,5,arrow=True)
    card(c,1320,380,1010,1340,'第二步：逐题证据 → 章节结果',TEAL)
    c.text(1360,485,'合成例：贪心算法',42,TEAL,bold=True,max_width=920)
    for i,example in enumerate(DEMO['examples']):
        y=590+i*145
        kind='编程' if example['type']=='PROGRAMMING' else '主观'
        c.rectangle((1355,y,2290,y+112),TPALE,radius=16)
        c.text(1385,y+20,f"{example['code']}  /  {kind}  /  难度 {example['difficulty']}",31,TEAL,bold=True,max_width=870)
        c.text(1385,y+67,f"本章权重 q = 1；观测得分 {fmt(example['score'])}",31,INK,max_width=870)
    greedy=next(e for e in DEMO['estimates'] if e['dimension']=='CH01')
    c.text(1360,1080,f"B0 = {fmt(greedy['baseline_value'])}",53,GRAY,bold=True,max_width=920)
    c.text(1360,1160,'本章三道已评分题的加权均值',32,MUTED,max_width=920)
    c.text(1360,1270,f"D1 = {fmt(greedy['value'])}",53,BLUE,bold=True,max_width=920)
    lines(c,1360,1355,['联合使用同批评分校准题目难度','再投影到参考难度0；不只平均这三题','差值来自难度与正则化，不是学习进步'],31,76,920)
    c.text(1360,1600,'两种题型不额外规定各占50%',33,TEAL,bold=True,max_width=920)
    c.line([(2330,1035),(2450,1035)],TEAL,5,arrow=True)
    card(c,2450,380,1280,1340,'第三步：状态控制可见轴',BLUE)
    rows=[e for e in DEMO['estimates'] if e['status']!='NOT_COVERED']
    radar(c,3090,1015,330,rows,445)
    c.line([(2520,1510),(2630,1510)],BLUE,6)
    c.text(2660,1495,'D1模型参考分',31,BLUE)
    c.line([(3060,1510),(3170,1510)],GRAY,4,dashed=True)
    c.text(3200,1495,'B0原始均值',31,GRAY,max_width=470)
    c.text(2510,1600,'待评 / 未交留空；未布置章节隐藏',33,AMBER,bold=True,max_width=1160)
    c.rectangle((110,1820,3730,1988),'#E6EDF7',radius=20)
    c.text(155,1860,'能提供：各章当前表现线索、证据覆盖、需要补充题目的方向。',40,INK,bold=True,max_width=3510)
    c.text(155,1927,'不能据此证明：通用智力、创造力、努力程度、真实掌握概率或招聘胜任力。',33,MUTED,max_width=3510)
    c.footer('示例数值来自已保存的合成D1批次；未布置的数学/位运算/数组章节隐藏，已布置无成绩的章节不补零。')
    return c.save_png('09-meeting-radar-dimensions-4k')


def contributions():
    c=Canvas();c.header('04 / 04','本项目引入了什么，解决了什么问题','定位：面向课程场景的建模适配与工程组合；不是声称提出全新的统计测量理论。')
    headers=[(110,600,'原来会遇到的问题'),(800,1660,'本项目的引入 / 改进'),(2570,1160,'对应收益与验证')]
    for x,w,t in headers:pill(c,x,365,w,t,TEAL,TPALE)
    rows=[
      (480,'同样80分，来自的题目难度不同',['难度感知模型：μ = sigmoid(Σ qθ − b)','按11章归因，保留连续部分分；不只重加权'],
       [f"常规留出RMSE：{metric('difficulty_signal','B0'):.4f} → {metric('difficulty_signal','D1'):.4f}",'B0 → D1；检验的是逐题预测']),
      (790,'教师1—5级难度可能标错',['教师等级只作为先验锚点','学生章节θ与题目难度b联合校准'],
       [f"错标场景：{metric('mislabeled_teacher','Fixed'):.4f} → {metric('mislabeled_teacher','D1'):.4f}",'固定先验 → 校准；已有题有效']),
      (1100,'小样本 / 全0或全1 / 数值不稳定',['正则化 + 稀疏坐标Newton + 缓存更新','固定顺序、步长回溯、按梯度判断收敛'],
       ['对照共144次优化全部收敛','保持端点有限；失败状态不伪装成功']),
      (1410,'图形完整，却可能掩盖缺失和口径',['B0 / D1双轨 + 覆盖状态 + 快照版本','过程独立观察；本人API；不改正式题分'],
       ['未布置隐藏，待评留空','结果可追溯，原始分与模型分分开'])]
    for y,problem,mechanism,evidence in rows:
        c.rectangle((110,y,3730,y+255),WHITE,'#D7E0EB',2,18)
        c.text(145,y+62,problem,34,INK,bold=True,max_width=580)
        lines(c,840,y+60,mechanism,34,87,1550)
        lines(c,2610,y+60,evidence,33,87,1070,color=TEAL)
        c.line([(720,y+127),(790,y+127)],TEAL,4,arrow=True)
        c.line([(2470,y+127),(2550,y+127)],TEAL,4,arrow=True)
    c.rectangle((110,1760,3730,1990),AP,radius=20)
    c.text(155,1798,'必须一起讲的反例：没有真实难度差异时，复杂模型不是更好。',41,AMBER,bold=True,max_width=3500)
    c.text(155,1875,f"B0 {metric('no_difficulty','B0'):.5f} → D1 {metric('no_difficulty','D1'):.5f}，六次重复全部退化；新题错标只胜出4/6次。",34,INK,max_width=3500)
    c.footer('80名模拟学生 × 66题 × 11章；6个压力场景、独立验证/测试种子；192次最终评估不等于192次模型拟合。')
    return c.save_png('10-meeting-model-improvements-4k')


if __name__=='__main__':
    reports=[overview(),architecture(),dimensions(),contributions()]
    (OUT/'meeting-figures-manifest.json').write_text(json.dumps(dict(
        canvas=[3840,2160],source='committed algorithm + synthetic artifact + frozen experiment results',figures=reports),
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(reports,ensure_ascii=True))
