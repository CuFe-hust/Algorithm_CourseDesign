"""Render design-only 4K meeting figures; no DB connection or personal data."""
from pathlib import Path
import hashlib
import json
import build_meeting_diagrams as drawing

OUT = Path(__file__).resolve().parents[1] / 'docs/assets/diagrams/analysis'
drawing.OUT = OUT
C = drawing.Canvas
BLUE, GREEN, AMBER, PURPLE = '#2563EB', '#059669', '#C87914', '#7C3AED'


def box(c, x, y, title, lines, color=AMBER, w=650, h=155):
    c.rectangle((x, y, x+w, y+h), '#FFFFFF', color, 3, 14)
    c.text(x+22, y+20, title, 34, color, bold=True, max_width=w-44)
    for n, line in enumerate(lines):
        c.text(x+22, y+77+n*36, line, 27, max_width=w-44)


def flow():
    c = C()
    c.title('03', '分析模块：六条业务链路',
            '箭头表示数据依赖；跨步骤通过数据库快照与结果交接。横向串行，不同链路可按条件并行。',
            '框架 / 合成演示已实现 · 研究算法待替换')
    rows = [
      ('01 编程评测线', 'P1逐提交执行；复用队友LOCAL评测。通过点数不直接冒充加权正式得分。', [
        ('固定提交与测试集', ['代码 / 语言 / 测试版本', '提交后立即入已有评测队列'], BLUE),
        ('ALG-JUDGE · 已有评测', ['复用 app/judge', 'LOCAL真实运行，资源不可用为空'], GREEN),
        ('评测摘要与采用候选', ['通过点数 / 判定 / 运行上下文', '沿用现有最佳候选规则'], GREEN),
        ('题目计分适配', ['需要明确计分规则与证据', '缺依据 → UNAVAILABLE'], AMBER),
        ('候选成绩数据', ['提供给第05线', '候选 ≠ 已发布成绩'], BLUE)]),
      ('02 内容证据线', 'P2 / X1 / X2快照后并行；不等待评测或互评。不自动扣分，先作为教师复核证据。', [
        ('同题作品集合快照', ['固定比较范围 / 提交版本', '去除姓名学号等非必要信息'], BLUE),
        ('三个独立黑盒 ∥', ['ALG-CODE / ALG-TEXT', 'ALG-AI：辅助信号接口'], AMBER),
        ('相似对 / 片段 / 信号', ['输入hash / 方法版本 / 局限', '未实现、样本不足单独表示'], AMBER),
        ('教师查看与决定', ['需要处置时记录理由与版本', '算法结果不是自动处罚'], PURPLE),
        ('版本化证据 / 处置', ['教师显式处置才影响后续', '算法不直接改学生原始记录'], BLUE)]),
      ('03 主观互评线', 'S1 → S2 → S3 → S4。必须等待教师开放与学生提交；补评复用匹配并排除作者/已评者。', [
        ('冻结答案与评审人群', ['截止后最后有效主观答案', '题目 / 量表 / 名单 / 截止版本'], BLUE),
        ('ALG-ALLOC · 匹配', ['人数 / 禁止关系 / 历史', '输出完整映射或不可行原因'], AMBER),
        ('教师确认开放', ['发布前检查输入hash未变', 'WAITING_HUMAN'], PURPLE),
        ('学生按量表评分', ['校验本人任务与评分范围', 'WAITING_HUMAN'], PURPLE),
        ('原始评价快照', ['分项分 / 评语 / 服务端时间', '作为第04线的固定输入'], BLUE)]),
      ('04 聚合与异常线', 'A4时长可早算；A2/A3/A5等待初步聚合。复核后重算新增版本，补评形成下一轮输入。', [
        ('原始评价与事件', ['固定评价集 / 量表 / 历史', '缺评与缺事件明确记录'], BLUE),
        ('ALG-AGG · 初步聚合', ['候选综合分 / 分歧 / 样本', '保存固定基准版本'], AMBER),
        ('四类异常检测 ∥', ['DEV / BIAS / TIME / REL', '证据不足 ≠ 未发现异常'], AMBER),
        ('教师复核与处置', ['保留 / 降权 / 作废 / 改分', '补评 → 回第03线'], PURPLE),
        ('ALG-AGG · 新版重算', ['复用聚合黑盒，不覆盖原分', '有效候选供第05线'], AMBER)]),
      ('05 成绩结算线', '第01与第04线在此汇合；模拟分、缺依据、待评不自动补零，也不进入正式发布。', [
        ('编程 / 主观有效结果', ['采用来源 / 版本 / 模拟标记', '等待必需的结果与教师处置'], BLUE),
        ('题目候选分', ['按题目满分归一化', '保留缺交 / 待评 / 系统失败'], BLUE),
        ('作业候选总分', ['固定权重与缺交政策', '输出总分或阻塞原因'], BLUE),
        ('教师确认发布', ['检查完整性 / 当前版本', '更正必须另存新版本'], PURPLE),
        ('成绩发布快照', ['正式发布只接真实有效来源', '演示发布始终标为模拟'], BLUE)]),
      ('06 学习分析线', '成绩后KNOW / ABILITY / STATS / DIFF可并行；BEHAV基于事件可独立运行，最后按版本汇合。', [
        ('成绩 / 标签 / 事件', ['固定发布版本与时间范围', '事件分支无需等待成绩'], BLUE),
        ('五个分析黑盒 ∥', ['掌握 / 能力 / 行为', '统计 / 经验难度'], AMBER),
        ('结果与数据覆盖', ['样本数 / 缺失 / 待评', '教师难度与经验难度分开'], BLUE),
        ('权限投影与查询', ['教师看本课，学生仅本人', '不从完成快推断态度或AI使用'], BLUE),
        ('班级 / 个人面板', ['相同范围与版本才能比较', '三类业务模块读取同一结果'], BLUE)]),
    ]
    xs = [110, 850, 1590, 2330, 3070]
    for r, (title, note, cards) in enumerate(rows):
        y = 400 + r*255
        c.text(110, y-50, title, 34, BLUE, bold=True)
        for x, card in zip(xs, cards):
            box(c, x, y, card[0], card[1], card[2])
        for x in xs[:-1]:
            c.line([(x+650, y+76), (x+740, y+76)], '#637A93', 4, arrow=True)
        c.text(110, y+174, note, 27, drawing.MUTED, max_width=3600)
    c.rectangle((90, 1940, 3750, 2115), '#E6EDF7', radius=16)
    c.text(120, 1966, '绿：已有代码能力　橙：可替换算法　紫：必须有人参与　蓝：数据 / 规则 / 查询', 31, bold=True, max_width=3580)
    c.text(120, 2022, 'DEMO合成数据与REAL_INPUT分开；真实缺输入就等待，模拟来源沿链传播。', 29, drawing.MUTED, max_width=3580)
    c.text(120, 2070, '图中“并行”指数据依赖与研究可并行；首版可单worker运行。正式互评与成绩发布仍需后续业务接入。', 27, drawing.MUTED, max_width=3580)
    return c.save('03-analysis-data-flow-4k')


def contracts():
    c = C()
    c.title('04', '算法黑盒：输入、输出与研究边界',
            '每人认领1–2个主黑盒。算法不直接读写数据库；服务固定输入、验证输出并记录版本。',
            '接口设计 · 真实 / 基线 / 模拟必须标明')
    cards = [
      ('ALG-JUDGE · 评测适配', '已有能力，复用，不重复研究',
       '提交 / 测试集 / 执行上下文', '现有JudgeResult与采用候选', '评测摘要 / 可用计分证据', '缺加权依据 → UNAVAILABLE', GREEN),
      ('ALG-ALLOC · 评审匹配', '研究：约束、公平性、历史关系',
       '答案作者 / 候选人 / 每份人数', '禁止关系 / 已有分配 / 历史 / seed', '完整分配边 / 负载指标', '或不可行报告，不私自少分配', AMBER),
      ('ALG-AGG · 评分聚合', '研究：稳定性、权重、分歧处理',
       '固定量表 / 分项评价 / 有效性', '最终权重 / 最低样本 / 参数', '归一化候选分 / 分歧 / 样本数', '无有效评价 → null，不是0分', AMBER),
      ('ALG-DEV · 单次偏离', '异常检测子算法①',
       '某条评价 / 同作品评分', '固定初步聚合基准 / 阈值', '异常对象 / 程度 / 证据', '样本不足独立表示', AMBER),
      ('ALG-BIAS · 长期偏差', '异常检测子算法②',
       '某评审者跨题评分与历史', '各作品固定基准 / 时间范围', '偏高 / 偏低方向及程度', '样本与依据，不自动降权', AMBER),
      ('ALG-TIME · 评价时长', '异常检测子算法③',
       '首次打开 / 提交的服务端时间', '任务 / 题目特征 / 阈值', '时长指标 / 信号 / 证据', '未记录事件 → 缺数据', AMBER),
      ('ALG-REL · 异常关系', '异常检测子算法④',
       '分配边 / 原评分 / 历史关系', '固定基准 / 最低样本数', '疑似边或群体 / 关联证据', '不直接判定作弊', AMBER),
      ('ALG-CODE · 代码相似', '研究：表示、比较、可解释片段',
       '同题代码集合 / 语言', '题干模板 / 比较范围', '相似作品对 / 相似度', '对应代码片段与方法版本', AMBER),
      ('ALG-TEXT · 文本相似', '研究：排除题干模板与公共表述',
       '同题主观答案集合', '题干 / 参考 / 公共模板', '相似作品对 / 相似度', '相似片段与方法局限', AMBER),
      ('ALG-AI · AI辅助信号', '研究接口，不预设可靠AI百分率',
       '答案 / 方法所需数据', '方法配置 / 适用范围', '信号 / 证据 / 局限', '未实现 → NOT_IMPLEMENTED', AMBER),
      ('ALG-KNOW · 知识点掌握', '研究：得分与知识点映射',
       '固定成绩 / 满分 / 标签权重', '学生范围 / 发布版本', '学生×知识点掌握估计', '样本数 / 缺失 / 方法依据', AMBER),
      ('ALG-ABILITY · 学生能力', '研究：多题表现与题目难度',
       '多题成绩 / 难度 / 范围', '固定发布版本 / 模型参数', '能力估计 / 依据 / 样本', '不反向改本轮原始分数', AMBER),
      ('ALG-BEHAV · 学习行为', '先做实际事件可解释指标',
       '提交 / 修改 / 撤回 / 评价事件', '固定时段 / 数据缺失类型', '节奏 / 次数 / 覆盖率', '不直接推断学习态度', AMBER),
      ('ALG-STATS · 基础统计', '规则与查询，通常不是研究重点',
       '名单 / 状态 / 有效成绩', '分母 / 分组 / 发布版本', '分布 / 完成率 / 通过率', '分子分母 / 缺交 / 待评', BLUE),
      ('ALG-DIFF · 经验难度', '研究或统计，与教师难度分开',
       '题目有效得分 / 满分', '指定人群 / 最低样本', '经验难度 / 样本量', '不足时返回不可用原因', AMBER),
    ]
    for n, (title, badge, i1, i2, o1, o2, color) in enumerate(cards):
        col, row = n % 3, n // 3
        x, y, w = 110+col*1230, 330+row*345, 1150
        c.rectangle((x, y, x+w, y+310), '#FFFFFF', color, 3, 14)
        c.text(x+25, y+20, title, 39, color, bold=True, max_width=w-50)
        c.text(x+25, y+77, badge, 27, drawing.MUTED, max_width=w-50)
        c.text(x+25, y+127, '输入：'+i1, 29, max_width=w-50)
        c.text(x+110, y+167, i2, 29, max_width=w-135)
        c.text(x+25, y+222, '输出：'+o1, 29, max_width=w-50)
        c.text(x+110, y+262, o2, 29, max_width=w-135)
    c.text(110, 2080, '统一元信息：schema版本 / 输入hash / 算法与实现版本 / 参数 / seed / is_mock / 业务状态 / 证据 / 局限', 29, drawing.MUTED, max_width=3600)
    return c.save('04-algorithm-black-boxes-4k')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = [flow(), contracts()]
    for r in reports:
        r['sha256'] = hashlib.sha256((OUT/r['file']).read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps({'status':'FRAMEWORK_AND_SYNTHETIC_DEMO_IMPLEMENTED',
        'base_main':'77f7cbc', 'teacher_reference':'9865289', 'diagrams':reports},
        ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(reports, ensure_ascii=True))


if __name__ == '__main__':
    main()
