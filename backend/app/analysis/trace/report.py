"""Assemble the stored and user-facing report from a trace conclusion.

The database columns already used by the old implementation are reused with new
content: ``trace_meta`` (was ``static_analysis``) holds adapter and ladder
metadata, ``trace_series`` (was ``growth``) holds the per-rung counts and the
fitted/recurrence evidence. The projection that the API returns is assembled
here so the service layer stays about the state machine.
"""
from __future__ import annotations

from .infer import TraceConclusion
from .schema import LadderTrace

WORK_UNIT_NOTES = {
    'python-monitoring-v1': '工作量单位是执行的行事件 + 跳转事件，已知代价的库函数按参数规模折算',
    'native-gcov-v1': '工作量单位是被插桩源码行的执行次数；标准库算法的预编译实现不可见，'
                      '按调用次数与输入规模折算理论代价',
}


def base_limitations(adapter: str) -> list[str]:
    return [
        '输入由平台按题目伸缩档合成，报告描述的是在这类输入上的增长，不代表最坏情况或全部合法输入',
        '复杂度来自真实执行轨迹的计数，不是形式化证明；等价改写的程序可能得到不同类别',
        WORK_UNIT_NOTES.get(adapter, '工作量单位是执行轨迹里的事件计数'),
    ]


def build(ladder: LadderTrace, conclusion: TraceConclusion, *,
          language: str, language_label: str, profile_family: str | None) -> dict:
    time_payload = conclusion.time.to_payload()
    space_payload = conclusion.space.to_payload()
    opaque: dict[str, int] = {}
    for point in ladder.points:
        for name, count in (point.opaque_calls or {}).items():
            opaque[name] = opaque.get(name, 0) + count
    limitations = list(base_limitations(ladder.adapter))
    if profile_family:
        limitations.append(f'该题使用的输入形态族：{profile_family}')
    if opaque:
        names = '、'.join(sorted(opaque)[:6])
        limitations.append(f'调用了未计价的库函数：{names}；这些调用按常数计，可能低估其真实代价')
    limitations.extend(ladder.notes)
    limitations.extend(conclusion.limitations)
    trace_meta = {
        'adapter': ladder.adapter,
        'work_unit': ladder.work_unit,
        'input_family': ladder.input_family,
        'stop_reason': ladder.stop_reason,
        'deterministic': ladder.deterministic,
        'repeat_delta': None if ladder.repeat_delta is None else round(ladder.repeat_delta, 4),
        'language_label': language_label,
        'opaque_calls': dict(sorted(opaque.items())),
    }
    trace_series = dict(ladder.to_payload())
    trace_series['time'] = time_payload
    trace_series['space'] = space_payload
    trace_series['evidence'] = list(conclusion.evidence)
    summary = {
        'time': {
            'class': conclusion.time.time_class,
            'confidence': conclusion.time.confidence,
            'source': 'TRACE',
            'method': conclusion.time.method,
            'closed_form': conclusion.time.closed_form,
            'recurrence': None if conclusion.time.recurrence is None
            else conclusion.time.recurrence.expression,
        },
        'space': {
            'class': conclusion.space.space_class,
            'confidence': conclusion.space.confidence,
            'source': conclusion.space.source,
        },
    }
    return {'summary': summary, 'trace_meta': trace_meta, 'trace_series': trace_series,
            'limitations': limitations}
