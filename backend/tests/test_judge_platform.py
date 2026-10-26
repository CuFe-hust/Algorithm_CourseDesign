import os
import pytest
from app.judge import config,locks


def test_local_driver_reports_actual_platform_support():
    assert config.driver_available('MOCK')
    assert config.driver_available('LOCAL') == (os.name=='posix')


def test_lifecycle_lock_excludes_other_handle(judge_work_root):
    with locks.job_lock(987654321):
        with pytest.raises((BlockingIOError,OSError)):
            with locks.job_lock(987654321,blocking=False):pass
    with locks.job_lock(987654321,blocking=False):pass
