"""Route-scoped request body ceiling enforced before the handler parses JSON.

The middleware counts real received bytes, so a missing or forged
``Content-Length`` (streamed or chunked upload) cannot bypass the limit.
"""
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import limits


class BodyTooLarge(Exception):
    pass


def _too_large_response(scope: Scope, request_id: str, limit: int) -> bytes:
    import json
    payload = {
        'code': 'REQUEST_TOO_LARGE',
        'message': '请求内容超过该接口允许的大小',
        'details': {'limit_bytes': limit},
        'request_id': request_id,
    }
    return json.dumps(payload, ensure_ascii=False).encode()


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        limit = limits.body_limit_for(scope.get('path', ''), scope.get('method', 'GET'))
        declared = None
        for name, value in scope.get('headers', []):
            if name == b'content-length':
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                break
        request_id = uuid.uuid4().hex
        if declared is not None and declared > limit:
            await self._reject(scope, receive, send, request_id, limit)
            return

        buffered = bytearray()
        messages: list[Message] = []
        while True:
            message = await receive()
            messages.append(message)
            if message['type'] == 'http.disconnect':
                break
            body = message.get('body', b'')
            buffered.extend(body)
            if len(buffered) > limit:
                await self._reject(scope, receive, send, request_id, limit)
                return
            if not message.get('more_body'):
                break

        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        await self.app(scope, replay, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send, request_id: str, limit: int) -> None:
        body = _too_large_response(scope, request_id, limit)
        await send({
            'type': 'http.response.start',
            'status': 413,
            'headers': [(b'content-type', b'application/json; charset=utf-8'),
                        (b'content-length', str(len(body)).encode()),
                        (b'x-request-id', request_id.encode())],
        })
        await send({'type': 'http.response.body', 'body': body})
