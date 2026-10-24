"""AC16–AC18, AC29, AC36: LOCAL execution, comparison and start gating."""
import os
import threading
import time

import pytest

from app.judge import checker, config, local, locks
from app.judge.local import CaseInput


def test_checker_normalizes_line_endings_and_trailing_whitespace_only():
    assert checker.matches(b'1\r\n2\r\n', b'1\n2')
    assert checker.matches(b'a  \nb\t\n\n\n', b'a\nb')
    assert not checker.matches(b' a\nb', b'a\nb')  # leading space is significant
    assert not checker.matches(b'a b', b'ab')  # inner whitespace is significant
    assert not checker.matches(b'a\n\nb', b'a\nb')  # inner blank line is significant
    assert checker.matches(b'\xff\xfe', b'\xff\xfe')  # byte comparison, no decode error
    assert not checker.matches(b'\xff', b'\xfe')


def test_python_accepted_wrong_answer_runtime_and_compilation(judge_work_root):
    cases = [CaseInput(1, '1 2\n', '3\n'), CaseInput(2, '5 7\n', '12\n')]
    accepted = local.execute('a,b=map(int,input().split())\nprint(a+b)\n', 'python3', cases, 1000)
    assert accepted.verdict == 'ACCEPTED' and accepted.passed == 2 and accepted.total == 2
    assert accepted.executed == 2

    wrong = local.execute('a,b=map(int,input().split())\nprint(a-b)\n', 'python3', cases, 1000)
    assert wrong.verdict == 'WRONG_ANSWER' and wrong.passed == 0 and wrong.executed == 2

    broken = local.execute('a,b=map(int,input().split())\nprint(a//0)\n', 'python3', cases, 1000)
    assert broken.verdict == 'RUNTIME_ERROR'

    syntax = local.execute('def broken(:\n', 'python3', cases, 1000)
    assert syntax.verdict == 'COMPILATION_ERROR' and syntax.executed == 0 and syntax.total == 2
    assert syntax.compiler_message and str(judge_work_root) not in syntax.compiler_message


def test_wall_clock_and_output_limits(judge_work_root):
    endless = local.execute('while True:\n    pass\n', 'python3', [CaseInput(1, '', '')], 200)
    assert endless.verdict == 'TIME_LIMIT_EXCEEDED'
    assert endless.executed == 1

    noisy = local.execute('while True:\n    print("x" * 4096)\n', 'python3', [CaseInput(1, '', '')], 5000)
    assert noisy.verdict == 'OUTPUT_LIMIT_EXCEEDED'


def test_gate_rejection_never_runs_the_student_program(judge_work_root, tmp_path):
    marker = tmp_path / 'executed.txt'
    source = f"open({str(marker)!r}, 'w').write('ran')\nprint('ok')\n"

    def closed_gate(spawned):
        return False

    with pytest.raises(local.OwnershipLost):
        local.execute(source, 'python3', [CaseInput(1, '', 'ok\n')], 2000, gate=closed_gate)
    assert not marker.exists()


def test_job_lock_is_cross_process_exclusive(judge_work_root):
    held = threading.Event()
    released = threading.Event()

    def holder():
        with locks.job_lock(101):
            held.set()
            released.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)
    with pytest.raises(BlockingIOError):
        with locks.job_lock(101, blocking=False):
            pass
    released.set()
    thread.join(5)
    with locks.job_lock(101, blocking=False):
        pass


def test_unavailable_language_is_a_configuration_error(judge_work_root):
    with pytest.raises(local.ConfigurationError) as failure:
        local.execute('print(1)', 'rust', [CaseInput(1, '', '1\n')], 1000)
    assert failure.value.code == 'JUDGE_CONFIGURATION_UNSUPPORTED'


@pytest.mark.skipif(config.toolchain('cpp') is None, reason='g++ is not available on this host')
def test_cpp_local_execution(judge_work_root):
    source = '#include <iostream>\nint main(){long long a,b; if(!(std::cin>>a>>b)) return 0; std::cout<<a+b<<"\\n";}\n'
    outcome = local.execute(source, 'cpp', [CaseInput(1, '1 2\n', '3\n')], 1000)
    assert outcome.verdict == 'ACCEPTED'


@pytest.mark.skipif(config.toolchain('c') is None, reason='gcc is not available on this host')
def test_c_local_execution_and_compile_error(judge_work_root):
    source = '#include <stdio.h>\nint main(){long long a,b; if(scanf("%lld %lld",&a,&b)!=2) return 0; printf("%lld\\n",a+b); return 0;}\n'
    outcome = local.execute(source, 'c', [CaseInput(1, '2 3\n', '5\n')], 1000)
    assert outcome.verdict == 'ACCEPTED'
    broken = local.execute('int main( { return 0; }', 'c', [CaseInput(1, '', '')], 1000)
    assert broken.verdict == 'COMPILATION_ERROR'
    assert broken.compiler_message and 'compiler_message' not in broken.compiler_message


@pytest.mark.skipif(config.toolchain('java') is None, reason='javac is not available on this host')
def test_java_local_execution(judge_work_root):
    source = ('import java.util.*;\npublic class Main{public static void main(String[] a){'
              'Scanner s=new Scanner(System.in); long x=s.nextLong(),y=s.nextLong(); System.out.println(x+y);}}\n')
    outcome = local.execute(source, 'java', [CaseInput(1, '4 6\n', '10\n')], 2000)
    assert outcome.verdict == 'ACCEPTED', outcome.compiler_message


def test_temporary_directories_are_cleaned_up(judge_work_root):
    local.execute('print(1)\n', 'python3', [CaseInput(1, '', '1\n')], 1000)
    assert list(judge_work_root.glob('judge-*')) == []
