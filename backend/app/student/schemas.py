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
