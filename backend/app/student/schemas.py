from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubmissionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    content: str=Field(min_length=1,max_length=262144)
    language: str | None=Field(default=None,max_length=32)
    client_request_id: str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('content')
    @classmethod
    def meaningful_content(cls,value):
        if not value.strip():
            raise ValueError('content is empty')
        return value


class RejudgeInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    client_request_id: str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')


class StatusQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    submission_ids: list[str]=Field(min_length=1,max_length=100)

    @field_validator('submission_ids')
    @classmethod
    def numeric_ids(cls,value):
        for item in value:
            if not item.isdigit() or int(item) <= 0 or int(item) > 9223372036854775807:
                raise ValueError('submission_ids must be positive integers')
        return value
