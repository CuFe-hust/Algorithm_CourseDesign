# 算法研究者交接：如何替换黑盒

三人共享同一输入输出，不各自建后端。插件目录是`backend/app/analysis/framework/catalog.py`的PLUGINS；类型在contracts.py，独立输出约束在validation.py，基线在`analysis/algorithms/baseline.py`，演示实现在mock.py。图中的ALG-*对应catalog里的key。

机器可读交付：[目录与JSON Schema](../../../data/analysis/catalog.json)、[完整输入样例](../../../data/analysis/example-inputs.json)、[对应输出样例](../../../data/analysis/example-outputs.json)。这些全部是合成数据，无需数据库或真实名单。

在backend目录运行：

```python
import json
from pathlib import Path
from app.analysis.framework.catalog import invoke

sample=json.loads(Path('../data/analysis/example-inputs.json').read_text(encoding='utf-8'))['allocation']
output=invoke(sample['algorithm_key'],sample['payload'],mode='REAL_INPUT',
              seed=sample['seed'],input_hash=sample['input_hash'])
print(output.model_dump_json())
```

REAL_INPUT在这里表示不用模拟研究算法回退；独立函数本身不读取真实数据库。匹配/聚合/事件计数/基础统计/代码相似有基线，其他研究插件目前明确NOT_IMPLEMENTED。DEMO调用未实现插件时才使用固定seed的演示输出，带is_mock=true。相同输入/seed/版本可复现，查询页面不重新生成随机值。

替换步骤：

1. 认领一个catalog key，读对应输入payload与output_schema；输出域外引用、非法分数、匹配自评/重复/不足人数等将被框架拒绝。
2. 在algorithms/中添加纯函数，参数为该插件的Pydantic输入对象；返回输出对象或符合schema的dict。禁止导入Web/数据库，不自行读取姓名学号、当前时间或全局随机状态。
3. 在catalog.invoke的实现分派处接入，并修改PLUGINS的implementation及version。**任何算法行为变化必须升级version**，不能原名原版本替换代码；旧批次不会自动升级，需创建新批次。纯函数需要随机性时显式接收seed。
4. 保存基础/改进算法、固定样本、成功/失败/不足样本、思想/复杂度/实验指标；测试同一份输入样例和额外边界数据。运行`python -m pytest tests/test_analysis_contracts.py tests/test_analysis_examples.py -q`。
5. 运行`python -m scripts.export_analysis_contracts`更新合成样例/schema。不得把真实名册、实际答案或真实评分导入公开样例。

当前分派保留简单显式结构，未来插件多时再拆注册handler，不为本轮引入额外插件依赖。只改一个函数并不完成研究，仍需要基线对比与失败场景。

`code_similarity` 已经从占位升级为真实实现（`winnowing_token` v2）：词法规格化 + Winnowing 指纹，输出相似对、行号区间与相似簇。参数 `k=12`、`window=4`、`minimum_tokens=40`、`threshold` 随输入快照保存，同一快照重算结果一致。算法说明、复杂度与失效场景见[同题代码相似检测](code-similarity.md)；DEMO 样例使用六份合成提交，其中四份互为改名版本，因此样例输出能看到 6 对证据与一个 4 成员簇。复杂度分析不使用这套插件，走独立的 `complexity_reports` 表与 `scripts/run_complexity.py`，见[复杂度分析](complexity.md)。

共同元信息包含schema_version、algorithm_key、input_hash、implementation_name/version、is_mock、status、payload、evidence、limitations。样例输入另带snapshot_id、parameters、seed供框架/实验记录；调用时参数阈值等目前已显式放入payload，parameters保留为空，不会偷偷影响计算。

NOT_IMPLEMENTED时payload={}，不能按成功payload的schema解读；成功或不足/无解的已实现插件仍给出各自结构。无评价分数为null，不是0；无解不能返回可发布的部分映射；不足不是“检测正常”。

复核/发布/CSV等是业务流程，不是独立研究黑盒。现有app/judge已负责LOCAL评测，不再重复实现。Windows上API与分析可运行，当前POSIX启动门不支持原生Windows LOCAL执行；MOCK与分析模拟不冒充真实评测。
