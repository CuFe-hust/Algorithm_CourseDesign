from app.analysis.contracts import JudgeInput,JudgeOutput


def judge(input:JudgeInput)->JudgeOutput:
    return JudgeOutput(verdict='MOCK_ACCEPTED',is_mock=True,algorithm_name='deterministic_mock',algorithm_version='1',
                       message='仅为接口联调模拟结果：未编译、未执行测试，不代表程序正确或正式成绩。')
