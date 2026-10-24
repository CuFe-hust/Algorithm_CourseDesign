from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None, headers=None):
        self.status, self.code, self.message, self.details = status, code, message, details
        self.headers = headers or {}


def error_response(request: Request, status: int, code: str, message: str, details=None, headers=None):
    request_id = getattr(request.state, 'request_id', '')
    merged = {'X-Request-ID': request_id, **(headers or {})}
    return JSONResponse(status_code=status, content={
        'code': code, 'message': message, 'details': details,
        'request_id': request_id,
    }, headers=merged)
