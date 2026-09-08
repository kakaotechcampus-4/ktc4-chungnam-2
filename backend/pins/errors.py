"""
`backend/common/errors.py`(PR #49)가 머지되기 전까지 이 모듈이 자체적으로 쓰는 에러 타입.
머지되면 이 클래스를 지우고 `common.errors.AppError`로 교체한다 — 그 전까지 호출부
(core/service/router)가 이 클래스 하나만 알면 되게 모아둔다.
"""


class PinError(Exception):
    def __init__(self, status_code: int, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail
