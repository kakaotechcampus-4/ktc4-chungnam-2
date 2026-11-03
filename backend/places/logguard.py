"""호환용 — 접근 로그 가리기는 common/logguard.py로 옮겼다(#1201). 쿼리스트링을 경로와 무관하게 모두 지운다."""

from common.logguard import MaskRequestFilter, install, mask_request_target  # noqa: F401
