"""Single-worker public demo limits; credentials remain on the server."""
import os
import time
from threading import Lock
from collections import deque
from fastapi import Request
from starlette.responses import JSONResponse

_lock = Lock()
_calls = 0
_requests = deque()


def reserve_model_call():
    global _calls
    if os.getenv('PUBLIC_DEMO') != '1':
        return
    with _lock:
        if _calls >= int(os.getenv('MODEL_CALL_LIMIT', '100')):
            raise RuntimeError('Public demo model-call budget exhausted')
        _calls += 1


async def public_limits(request: Request, call_next):
    if request.method == 'POST' and request.url.path.startswith('/api/'):
        if os.getenv('PUBLIC_DEMO') == '1':
            with _lock:
                now = time.monotonic()
                while _requests and now - _requests[0] > 3600:
                    _requests.popleft()
                if len(_requests) >= int(os.getenv('REQUESTS_PER_HOUR', '30')):
                    return JSONResponse({'detail':'Public demo capacity reached. Please try again later.'}, status_code=429)
                _requests.append(now)
        limit = 10 * 1024 * 1024 + 65536
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                return JSONResponse({'detail':'Request exceeds upload limit'},status_code=413)
        request._body = bytes(body)
    return await call_next(request)
