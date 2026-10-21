from pydantic import BaseModel, Field


class JudgeInput(BaseModel):
    submission_id:str
    source:str
    language:str
    test_suite_id:str


class JudgeOutput(BaseModel):
    verdict:str
    is_mock:bool
    algorithm_name:str
    algorithm_version:str
    cpu_time_ms:int|None=Field(default=None,ge=0)
    memory_kib:int|None=Field(default=None,ge=0)
    message:str
