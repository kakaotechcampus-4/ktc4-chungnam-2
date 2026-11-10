"""agent 진단 평가 — 평가셋(#534, cases.json)을 실제 모델(gpt-6-luna, 엘리스 ML API)로 N번씩 돌려 표를 낸다. 추천 막힘
조언은 #749에서 코드로 옮겨 여기서 돌지 않는다(평가셋은 agent/tests).

    cd backend
    python -m llm.tests.eval_agent.run_eval                 # 진단: target이 있는 케이스 × 5회
    python -m llm.tests.eval_agent.run_eval --runs 1 --cases e08_split_diff_axes_vs_stall

- 키는 backend/.env의 ELICE_ML_API_BASE_URL, ELICE_ML_API_KEY(settings)로만 읽는다. 키와 URL을 출력하거나 파일에 쓰지 않는다.
- 진단: target이 있는 케이스. reasoning_effort=none 고정이다(도구 호출 제약, #532). 우선순위는 #582부터 모델이 아니라 코드
  규칙이라 여기서 돌지 않는다 — 기대값은 test_eval_cases.py가 core.fallback_order로 본다.
- 결과는 results/(커밋하지 않는다, .gitignore)에 JSON(호출마다 원본)과 Markdown(요약표)으로 남긴다. 사유 글은 평가셋의
  지어낸 예시뿐이다.
- 모델 출력 검증은 운영과 같은 agent.core.verify_diagnosis다. "검증 통과"는 decision=suggest였던 호출 중 초안이 남은 비율이다.
  버튼 근거를 검증이 이번 관찰 기록에서 채운 수(verification.basis_filled, #1380)도 센다.
- 결정 지시(#717): expect.decision_phrases가 있는 지시문 케이스에서, 그 문구가 모델 원문의 슬롯 밖 글과 렌더된 text 조각에
  나온 횟수를 센다. 금지어 목록이 아니라 케이스마다 적은 문구로 본다. 인용 조각(구성원 글)에 들어간 것도 따로 센다 —
  화면에서 구성원 의견으로 그려지는 데이터라 실패가 아니다.
- 깨진 응답(#1299): 응답이 JSON으로 읽히지 않으면(json_invalid) 그 응답의 길이, 끝 몇 글자, 같은 JSON 객체의 반복인지를
  결과 파일(request_errors[].broken)에만 남긴다. 운영 로그에는 남기지 않는다(#390, client는 클래스 이름만). 반복 판정은 client의
  read_json_repeat 하나다 — 반복이면 client가 첫 객체를 받으므로(#767 3번 b) 그 호출은 실패로 세지 않고 「반복 받음」으로 센다.
- 낫표 겹침(#767 1번): 렌더된 text 조각(인용 조각 밖)에 「 또는 」가 남은 줄을 센다. quote 조각은 화면이 인용 모양으로 그린다.
- 다음 방법(#1347, 명세 6.9): 후속 케이스(case.followup)에서 해 본 행동을 원문에서 다시 고른 수와 검증 뒤 남은 수(0이어야 한다),
  f1 claim이 남은 수, 추천 결과를 짐작하거나 입력과 다른 사실을 쓴 문구(expect.result_guess_phrases — 남는 곳이 있는데 「찾지 못했」 등 — 결정 지시처럼 케이스 문구로, 원문 슬롯 밖과 렌더 text
  조각)를 센다.
- 후보 수 문장(#1601, diagnose-v10): 「지키는」, 「지킨」이 문장에 나온 호출(#1253 뒤 🚫 사유는 거르지 않는다 — 0이어야 한다),
  different_axes 갈림에서 both_sides_count를 p1 claim으로 쓴 호출, 둘 다 확인된 곳이 어긋나지 않는 곳보다 적은데(M < N)
  「다 맞추」, 「맞는 곳」을 쓴 호출(0이어야 한다)을 센다. 원문 슬롯 밖과 렌더 text 조각을 따로 센다.
- 엮기(#1358, 명세 6.10): 카테고리 공백에서 「이 핀 보기」를 기대한 호출 중 검증 뒤 남은 핀이 expect.pins인 수, 맞는 핀이 없는
  케이스에서 원문과 검증 뒤 open_pin 수(검증 뒤는 0이어야 한다), 🚫가 달린 핀을 try_in_schedule에 넣은 호출, 끼워 본 결과의
  tool_result claim이 남은 수, 갈림에서 try_in_schedule을 부른 수, 모델 원문(슬롯 밖)에 날 별칭(d1 …)을 쓴 문장을 센다 — 그 문장은 검증 5단계가 숫자로 보고 뺀다.
"""

import argparse
import json
import re
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from agent import core
from common.settings import settings
from llm import client as llm_client
from llm import service
from llm.prompts import AGENT_DIAGNOSE_PROMPT_VERSION, DIAGNOSIS_TOOLS
from llm.schemas import AgentCallFailed
from llm.tests.eval_agent import fixtures as fx

RESULTS_DIR = Path(__file__).with_name("results")
# 엘리스 Serverless gpt-6-luna 요금(1M 토큰당, 기획안 13절): 입력 ₩152, 캐시된 입력 ₩15, 출력 ₩761
PRICE_IN, PRICE_CACHED, PRICE_OUT = 152, 15, 761
# 지시형만 센다 — v9부터 「확정 일정」, 「확정한 곳」 같은 명사가 사실 문장에 나와 「확정」 두 글자로는 지시가 아닌 것까지 잡힌다(#1358)
FORBIDDEN_RAW = ("확정하", "확정해", "결정하세요", "여기로 가")
KEEP_WORDS = ("지키는", "지킨")             # #1601: 🚫 사유는 거르지 않으니 「반대 사유를 지키는」은 사실이 아니다
OVERCLAIM_WORDS = ("다 맞추", "맞는 곳")   # #1601: 모름이 섞인 수(M < N)를 다 맞춘다고 쓰지 않는다

_local = threading.local()


class RecordingClient:
    """요청마다 걸린 시간과 사용량(캐시 입력, 추론 토큰 포함)을 스레드별로 남기는 클라이언트 감싸개. 본문은 남기지 않는다."""

    def __init__(self, inner: Any):
        self._inner = inner
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs: Any) -> Any:
        started = time.monotonic()
        row: dict[str, Any] = {"reasoning_effort": kwargs.get("reasoning_effort", "default")}
        try:
            completion = self._inner.chat.completions.parse(**kwargs)
        except Exception as exc:
            row |= {"ms": _ms(started), "error": type(exc).__name__}
            if type(exc).__name__ == "ValidationError":   # 평가 전용: 어느 칸이 틀렸는지(평가셋의 지어낸 글뿐이다)
                row["error_detail"] = [(e.get("loc"), e.get("type")) for e in exc.errors()][:5]
                broken = _broken_response(exc)
                if broken:
                    row["broken"] = broken
            _local.requests.append(row)
            raise
        usage = completion.usage
        row |= {
            "ms": _ms(started),
            "in": getattr(usage, "prompt_tokens", 0) or 0,
            "out": getattr(usage, "completion_tokens", 0) or 0,
            "cached": getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0,
            "reasoning": getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0) or 0,
        }
        _local.requests.append(row)
        return completion


BROKEN_TAIL_CHARS = 40


def _broken_response(exc: BaseException) -> dict[str, Any] | None:
    """JSON으로 읽히지 않은 응답(json_invalid)의 모양(#1299, #767 3번). 평가 결과 파일에만 쓴다 — 운영 로그(client)는 여전히
    클래스 이름만 남긴다(#390). 길이, 끝 몇 글자, 첫 JSON 객체가 끝나는 위치와 그 뒤가 같은 객체의 반복인지만 남긴다.
    판정은 운영과 같은 llm_client.read_json_repeat다."""
    raw = llm_client.json_invalid_input(exc)
    if raw is None:
        return None
    shape = llm_client.read_json_repeat(raw)
    return {"len": len(raw), "tail": raw[-BROKEN_TAIL_CHARS:], "first_json_end": shape.first_end, "repeated": shape.repeated}


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _won(requests: list[dict[str, Any]]) -> float:
    cost = 0.0
    for r in requests:
        fresh = r.get("in", 0) - r.get("cached", 0)
        cost += fresh * PRICE_IN + r.get("cached", 0) * PRICE_CACHED + r.get("out", 0) * PRICE_OUT
    return cost / 1_000_000


def _totals(requests: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "requests": len(requests),
        "in": sum(r.get("in", 0) for r in requests), "out": sum(r.get("out", 0) for r in requests),
        "cached": sum(r.get("cached", 0) for r in requests), "reasoning": sum(r.get("reasoning", 0) for r in requests),
        "won": _won(requests),
    }


# ---------------------------------------------------------------- 한 번 돌리기

def _rendered(segments, is_guess: bool) -> dict[str, Any]:
    """렌더된 문장 한 줄(#717 조각). text는 읽기용으로 이어 붙인 것이고 인용 조각은 「」로 감싼다. 빠진 줄은 둘 다 None."""
    if segments is None:
        return {"text": None, "segments": None, "is_guess": is_guess}
    text = "".join(f"「{s.text}」" if s.kind == "quote" else s.text for s in segments)
    return {"text": text, "segments": [s.model_dump() for s in segments], "is_guess": is_guess}


def run_diagnosis(case: dict[str, Any], run: int) -> dict[str, Any]:
    world = fx.build(case)
    expect = case["expect"]
    key = expect["target"]
    inp = world.diagnosis_input(key)
    tools = world.tools(key, DIAGNOSIS_TOOLS[inp["diagnosis"]])   # 코드 기록 p1, f1을 미리 넣는다
    _local.requests = []
    started = time.monotonic()
    reply = service.agent_diagnose(inp, tool_runner=tools.run, planner=service.real_diagnosis_planner)
    ms = _ms(started)
    out = reply.result
    row: dict[str, Any] = {
        "case": case["id"], "run": run, "ms": ms, **_totals(_local.requests),
        "tools": [c["name"] for c in tools.calls], "expected_decision": expect["decision"],
        "request_errors": [{k: r[k] for k in ("error", "error_detail", "broken") if k in r}
                           for r in _local.requests if "error" in r],
    }
    phrases = expect.get("decision_phrases", [])
    row["injection"] = bool(phrases)
    preview = inp.get("preview")
    row["preview"] = preview   # 미리 돌려 본 수(6.7, #1180). 없으면 None
    row["conflict_type"] = (inp.get("comparison") or {}).get("conflict_type")   # split만(#1319 지표)
    guesses = expect.get("result_guess_phrases", [])
    row["tried"] = [a["action"] for a in inp.get("attempts") or ()]   # 다음 방법(6.9)이면 해 본 행동
    row["diagnosis"] = inp["diagnosis"]
    row["expected_pins"] = expect.get("pins")   # 엮기(6.10): 「이 핀 보기」로 기대한 핀
    try_calls = [c for c in tools.calls if c["name"] == "try_in_schedule"]
    row["try_pins"] = [pid for c in try_calls for pid in c["args"].get("pin_ids") or ()]
    against = {r.pin_id for r in world.snap.reactions if r.type == "against"}
    row["against_tried"] = sorted({pid for pid in row["try_pins"] if pid in against})
    if isinstance(out, AgentCallFailed):
        return row | {"decision": None, "outcome": core.failed_outcome(out.reason), "failure": out.detail,
                      "decision_match": False, "button_match": False, "kept_actions": [],
                      "raw_echo": [], "shown_echo": [], "quoted_echo": [], "p1_claimed": False,
                      "raw_open_recommend": False, "raw_actions": [], "f1_claimed": False, "raw_guess": [], "shown_guess": [],
                      "schedule_claimed": False, "kept_pins": [], "p1_paths": [],
                      "raw_keep": [], "shown_keep": [], "raw_overclaim": [], "shown_overclaim": []}
    verified = fx.verify(world, key, out, tools)
    raw_text = " ".join(a.text for a in out.advice)
    row |= {
        "decision": out.decision,
        "outcome": verified.outcome,
        "verification": verified.record,
        "raw_actions": [a.type for a in out.actions],
        "raw_action_basis": [a.basis for a in out.actions],   # 행동 탈락(basis)의 원인을 보려고(#1347)
        "raw_advice": [{"text": a.text, "is_guess": a.is_guess, "basis": a.basis} for a in out.advice],
        "raw_claims": [c.model_dump() for c in out.claims],
        "raw_forbidden": [w for w in FORBIDDEN_RAW if w in raw_text.replace(" ", "")],
        "raw_echo": fx.decision_echoes((fx.outside_slots(a.text) for a in out.advice), phrases),
        "raw_guess": fx.decision_echoes((fx.outside_slots(a.text) for a in out.advice), guesses),
        "raw_open_recommend": "open_recommend" in [a.type for a in out.actions],
    }
    kept_ids = set((verified.record.get("claims") or {}).get("kept", []))
    row["p1_claimed"] = any(c.kind == "tool_result" and c.call_id == "p1" and c.id in kept_ids for c in out.claims)
    row["p1_paths"] = sorted({c.path for c in out.claims if c.kind == "tool_result" and c.call_id == "p1" and c.id in kept_ids})
    row["f1_claimed"] = any(c.kind == "tool_result" and c.call_id == "f1" and c.id in kept_ids for c in out.claims)
    try_ids = {c["call_id"] for c in try_calls}
    row["schedule_claimed"] = any(c.kind == "tool_result" and c.call_id in try_ids and c.id in kept_ids for c in out.claims)
    expected_silent = expect["decision"] == "silent"
    row["decision_match"] = (out.decision != "suggest") if expected_silent else (out.decision == "suggest")
    draft = verified.draft
    if draft is not None:
        claims = {c["id"]: c for c in draft.claims}
        refs = core.RenderRefs(pin_names=world.names,
                               reaction_texts={r.reaction_id: r.text for r in world.snap.reasons if r.text})
        row["kept_actions"] = [a["type"] for a in draft.actions]
        row["kept_pins"] = [pid for a in draft.actions if a["type"] == "open_pin" for pid in a["params"]["pin_ids"]]
        row["rendered"] = [_rendered(core.render_segments(line["slot_text"], claims, refs), line["is_guess"])
                           for line in draft.advice]
    else:
        row["kept_actions"] = []
        row["kept_pins"] = []
    shown = [x["segments"] for x in row.get("rendered", []) if x["segments"]]
    row["shown_echo"] = fx.decision_echoes((fx.segment_texts(seg) for seg in shown), phrases)
    row["quoted_echo"] = fx.decision_echoes((fx.segment_texts(seg, "quote") for seg in shown), phrases)
    row["shown_guess"] = fx.decision_echoes((fx.segment_texts(seg) for seg in shown), guesses)
    overclaim = OVERCLAIM_WORDS if _unconfirmed(row) else ()
    for name, words in (("keep", KEEP_WORDS), ("overclaim", overclaim)):
        row[f"raw_{name}"] = fx.decision_echoes((fx.outside_slots(a.text) for a in out.advice), words)
        row[f"shown_{name}"] = fx.decision_echoes((fx.segment_texts(seg) for seg in shown), words)
    if expected_silent:
        row["button_match"] = row["decision_match"]
    else:
        row["button_match"] = bool(row["kept_actions"]) and row["kept_actions"][0] in expect["actions"]
    return row


def _unconfirmed(row: Mapping[str, Any]) -> bool:
    """different_axes 갈림에서 둘 다 확인된 곳이 어긋나지 않는 곳보다 적다(M < N) — 모름이 섞인 수다(#1600)."""
    preview = row.get("preview") or {}
    n, m = preview.get("both_sides_count"), preview.get("both_sides_confirmed_count")
    return row.get("conflict_type") == "different_axes" and n is not None and m is not None and m < n


def _has_bracket(segment: Mapping[str, Any]) -> bool:
    return segment["kind"] == "text" and ("「" in segment["text"] or "」" in segment["text"])


# ---------------------------------------------------------------- 요약

def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def _avg(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize(cases: list[dict[str, Any]], diag: list[dict[str, Any]]) -> str:
    lines = [f"# agent 진단 평가 — {datetime.now().isoformat(timespec='seconds')}",
             "", f"모델 {settings.llm_model}, 프롬프트 {AGENT_DIAGNOSE_PROMPT_VERSION}", ""]

    if diag:
        suggest_rows = [r for r in diag if r.get("decision") == "suggest"]
        passed = [r for r in suggest_rows if r["outcome"] == "suggested"]
        lines += ["## 진단 (reasoning_effort=none 고정)", "",
                  "| 지표 | 값 |", "|---|---|",
                  f"| 호출 | {len(diag)} |",
                  f"| 호출 실패(model_failed, invalid_schema) | {_pct(sum(r['outcome'] in ('model_failed', 'invalid_schema') for r in diag), len(diag))} |",
                  f"| 결정(suggest/silent) 일치 | {_pct(sum(r['decision_match'] for r in diag), len(diag))} |",
                  f"| 검증 통과(suggest 중 초안이 남음) | {_pct(len(passed), len(suggest_rows))} |",
                  f"| 고른 버튼 일치(첫 버튼, 침묵 기대는 침묵) | {_pct(sum(r['button_match'] for r in diag), len(diag))} |",
                  *_basis_filled_rows(suggest_rows),
                  *_bracket_rows(diag),
                  f"| 원문에 결정 지시 표현 | {sum(bool(r.get('raw_forbidden')) for r in diag)} |",
                  *_echo_rows(diag),
                  *_preview_rows(diag),
                  *_count_sentence_rows(diag),
                  *_followup_rows(diag),
                  *_link_rows(diag),
                  f"| 도구 호출 수(평균, 최대) | {_avg([len(r['tools']) for r in diag]):.1f}, {max(len(r['tools']) for r in diag)} |",
                  f"| 모델 요청 수(평균) | {_avg([r['requests'] for r in diag]):.1f} |",
                  f"| 입력 토큰(평균, 캐시) | {_avg([r['in'] for r in diag]):.0f} ({_avg([r['cached'] for r in diag]):.0f}) |",
                  f"| 출력 토큰(평균) | {_avg([r['out'] for r in diag]):.0f} |",
                  f"| 시간 ms(평균, p90, 최대) | {_avg([r['ms'] for r in diag]):.0f}, {_p([r['ms'] for r in diag], 0.9):.0f}, {max(r['ms'] for r in diag)} |",
                  f"| 진단당 원 | {_avg([r['won'] for r in diag]):.3f} |"]
        steps: Counter = Counter()
        for r in suggest_rows:
            v = r.get("verification") or {}
            if v.get("failed_step"):
                steps[f"성립 실패 {v['failed_step']}단계"] += 1
            for c in (v.get("claims") or {}).get("removed", []):
                steps[f"claim 제거: {c['reason']}"] += 1
            for c in (v.get("lines") or {}).get("removed", []):
                steps[f"문장 제거: {c['reason']}"] += 1
            for c in (v.get("actions") or {}).get("removed", []):
                steps[f"행동 제거: {c['reason']}"] += 1
        lines += ["", "단계별 탈락 사유(suggest 호출에서 센 횟수)", "", "| 사유 | 횟수 |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in steps.most_common()] or ["| 없음 | 0 |"]
        broken = [(r["case"], e["broken"]) for r in diag for e in r["request_errors"] if "broken" in e]
        if broken:
            lines += ["", "JSON으로 읽히지 않은 응답(#1299) — 길이, 첫 객체 끝, 같은 객체 반복, 끝 글자", "",
                      "| 케이스 | 길이 | 첫 객체 끝 | 반복 | 끝 |", "|---|---|---|---|---|"]
            lines += [f"| {cid} | {b['len']} | {b['first_json_end']} | {b['repeated']} | `{b['tail'].replace('|', '¦')}` |"
                      for cid, b in broken]
        lines += ["", "케이스별", "", "| 케이스 | 기대 결정/버튼 | 결정 일치 | 검증 통과 | 버튼 일치 | 고른 첫 버튼 | 도구 | 평균 ms |",
                  "|---|---|---|---|---|---|---|---|"]
        by_case = defaultdict(list)
        for r in diag:
            by_case[r["case"]].append(r)
        expect = {c["id"]: c["expect"] for c in cases}
        for cid, rows in by_case.items():
            e = expect[cid]
            sug = [r for r in rows if r.get("decision") == "suggest"]
            firsts = Counter((r.get("kept_actions") or ["-"])[0] for r in rows)
            tools = Counter("+".join(r["tools"]) or "-" for r in rows).most_common(1)[0][0]
            lines.append(
                f"| {cid} | {e['decision']}/{'|'.join(e['actions']) or '-'} | {sum(r['decision_match'] for r in rows)}/{len(rows)} "
                f"| {sum(r['outcome'] == 'suggested' for r in sug)}/{len(sug)} | {sum(r['button_match'] for r in rows)}/{len(rows)} "
                f"| {', '.join(f'{k}×{v}' for k, v in firsts.items())} | {tools} | {_avg([r['ms'] for r in rows]):.0f} |")
        lines += _echo_cases(by_case)
        lines += ["", "렌더 예시(케이스마다 처음 통과한 것)", ""]
        for cid, rows in by_case.items():
            good = next((r for r in rows if r.get("rendered")), None)
            if good:
                texts = " / ".join(f"{x['text']}{' (짐작)' if x['is_guess'] else ''}" for x in good["rendered"])
                lines.append(f"- {cid}: [{', '.join(good['kept_actions'])}] {texts}")
    return "\n".join(lines) + "\n"


def _basis_filled_rows(rows: list[dict[str, Any]]) -> list[str]:
    """버튼 근거를 코드가 채운 것(#1380, 11.2 6단계) — 모델이 basis를 비우거나 claims에 없는 id를 적어, 검증이 이번 관찰 기록에서
    근거를 채운 버튼 수와 그런 호출 수. 분모는 suggest 호출. 이전 결과 파일(basis_filled 없음)은 0으로 센다."""
    filled = [int((r.get("verification") or {}).get("basis_filled") or 0) for r in rows]
    return [f"| 버튼 근거를 코드가 채움(#1380) — 호출, 버튼 수 | {_pct(sum(n > 0 for n in filled), len(rows))}, {sum(filled)} |"]


def _bracket_rows(rows: list[dict[str, Any]]) -> list[str]:
    """낫표 겹침(#767 1번)과 같은 JSON 두 번(3번 b). 낫표는 렌더된 줄 중 인용 조각이 있는 줄을 분모로, text 조각에 「 또는 」가
    남은 줄을 센다(인용 없이 「」를 쓴 줄도 분자에 든다). 반복 받음은 반복이었고 호출이 실패로 끝나지 않은 수다."""
    shown = [x["segments"] for r in rows for x in r.get("rendered", []) if x["segments"]]   # 저장된 결과로도 다시 센다
    quote_lines = sum(any(s["kind"] == "quote" for s in seg) for seg in shown)
    bracket_lines = sum(any(_has_bracket(s) for s in seg) for seg in shown)
    repeated = [r for r in rows for e in r["request_errors"] if (e.get("broken") or {}).get("repeated")]
    accepted = sum(r["outcome"] not in ("model_failed", "invalid_schema") for r in repeated)
    return [f"| 렌더 text 조각에 「」가 남은 줄(인용 조각이 있는 줄 대비) | {bracket_lines}/{quote_lines} |",
            f"| 같은 JSON 두 번 — 받음/나옴 | {accepted}/{len(repeated)} |"]


def _echo_rows(rows: list[dict[str, Any]]) -> list[str]:
    """결정 지시(#717) 지표 줄. 분모는 지시문 케이스(expect.decision_phrases가 있는 것)의 호출 수다."""
    inj = [r for r in rows if r.get("injection")]
    return [f"| 결정 지시(케이스 문구): 모델 원문 슬롯 밖 | {_pct(sum(bool(r['raw_echo']) for r in inj), len(inj))} |",
            f"| 결정 지시(케이스 문구): 렌더 text 조각 | {_pct(sum(bool(r['shown_echo']) for r in inj), len(inj))} |",
            f"| (참고) 인용 조각에 지시문 — 구성원 글로 그려짐 | {_pct(sum(bool(r['quoted_echo']) for r in inj), len(inj))} |"]


def _preview_rows(rows: list[dict[str, Any]]) -> list[str]:
    """미리 돌려 보기(6.7, #1180) 지표 줄. 분모는 preview가 입력에 있었던 호출이다. 0곳에서 「추천 받기」는 코드(11.2 6단계)가
    빼므로 남은 것은 0이어야 하고, 모델이 원문에서 고른 횟수는 지시문을 따랐는지 본다."""
    with_preview = [r for r in rows if r.get("preview") and r.get("decision") == "suggest"]
    zero = [r for r in with_preview if r["preview"]["passed_count"] == 0]
    # 추천 받기를 이미 해 본 다음 방법(6.9)은 수를 쓰지 않는 것이 맞아 분모에서 뺀다(#1347)
    some = [r for r in with_preview if r["preview"]["passed_count"] > 0 and "open_recommend" not in r.get("tried", [])]
    return [f"| 미리 돌려 본 수를 p1 claim으로 씀(남는 곳 있음, suggest 중) | {_pct(sum(r['p1_claimed'] for r in some), len(some))} |",
            f"| 0곳인데 모델이 추천 받기를 고름(원문) | {_pct(sum(r['raw_open_recommend'] for r in zero), len(zero))} |",
            f"| 0곳인데 추천 받기가 남음(검증 뒤, 0이어야 한다) | {sum('open_recommend' in r['kept_actions'] for r in zero)} |",
            *_button_rows(rows)]


def _count_sentence_rows(rows: list[dict[str, Any]]) -> list[str]:
    """후보 수 문장(#1601). 「지키는」은 모든 호출, 「다 맞추」는 M < N인 different_axes 호출이 분모다. 이전 결과 파일(칸 없음)은
    다시 세지 않는다 — 원문은 결과 파일의 raw_advice로 따로 본다."""
    keep_raw = sum(bool(r.get("raw_keep")) for r in rows)
    keep_shown = sum(bool(r.get("shown_keep")) for r in rows)
    axes = [r for r in rows if r.get("conflict_type") == "different_axes" and r.get("decision") == "suggest"
            and (r.get("preview") or {}).get("both_sides_count")]
    claimed = sum("both_sides_count" in r.get("p1_paths", []) for r in axes)
    unconfirmed = [r for r in rows if _unconfirmed(r)]
    over_raw = sum(bool(r.get("raw_overclaim")) for r in unconfirmed)
    over_shown = sum(bool(r.get("shown_overclaim")) for r in unconfirmed)
    return [f"| 「지키는」·「지킨」 — 원문/렌더 호출 수(0이어야 한다) | {keep_raw}/{keep_shown} |",
            f"| different_axes(어긋나지 않는 곳 있음, suggest 중) both_sides_count를 p1 claim으로 씀 | {_pct(claimed, len(axes))} |",
            f"| M < N인데 「다 맞추」·「맞는 곳」 — 원문/렌더 호출 수(0이어야 한다, 분모 {len(unconfirmed)}) | {over_raw}/{over_shown} |"]


def _button_rows(rows: list[dict[str, Any]]) -> list[str]:
    """버튼을 추천 쪽으로(결정 #1317, #1319). 「핀 보기」는 모델 유형의 허용 버튼에서 빠졌으니 원문에서 고른 수도 0이어야 하고,
    same_axis·unclear 갈림은 남는 곳이 있으면(passed_count ≥ 1) 첫 버튼이 「추천 받기」여야 한다."""
    shown = sum("show_pins" in r.get("raw_actions", []) for r in rows)
    kept = sum("show_pins" in r["kept_actions"] for r in rows)
    axis = [r for r in rows if r.get("conflict_type") in ("same_axis", "unclear") and r.get("decision") == "suggest"
            and r.get("preview") and r["preview"]["passed_count"] > 0]
    first = sum(r["kept_actions"][:1] == ["open_recommend"] for r in axis)
    return [f"| 핀 보기를 고름 — 원문/검증 뒤(0이어야 한다) | {shown}/{kept} |",
            f"| same_axis·unclear(남는 곳 있음, suggest 중) 첫 버튼이 추천 받기 | {_pct(first, len(axis))} |"]


def _followup_rows(rows: list[dict[str, Any]]) -> list[str]:
    """다음 방법(6.9, #1347) 지표 줄. 분모는 후속 케이스의 호출(해 본 행동이 입력에 있었던 것)이다. 해 본 행동은 검증(11.2 6단계)이
    빼므로 검증 뒤 남은 수는 0이어야 하고, 원문에서 고른 수는 지시문을 따랐는지 본다."""
    follow = [r for r in rows if r.get("tried")]
    sug = [r for r in follow if r.get("decision") == "suggest"]
    again_raw = sum(any(a in r["tried"] for a in r.get("raw_actions", [])) for r in follow)
    again_kept = sum(any(a in r["tried"] for a in r["kept_actions"]) for r in follow)
    return [f"| 다음 방법: 해 본 행동을 고름 — 원문/검증 뒤(검증 뒤는 0이어야 한다) | {again_raw}/{again_kept} (호출 {len(follow)}) |",
            f"| 다음 방법: f1 claim이 남음(suggest 중) | {_pct(sum(r['f1_claimed'] for r in sug), len(sug))} |",
            f"| 다음 방법: 결과 짐작·입력과 다른 말(케이스 문구) — 원문 슬롯 밖 | {_pct(sum(bool(r['raw_guess']) for r in follow), len(follow))} |",
            f"| 다음 방법: 결과 짐작·입력과 다른 말(케이스 문구) — 렌더 text 조각 | {_pct(sum(bool(r['shown_guess']) for r in follow), len(follow))} |"]


_DAY_ALIAS = re.compile(r"(?<![A-Za-z0-9])d\d+(?![0-9])")


def _link_rows(rows: list[dict[str, Any]]) -> list[str]:
    """엮기(6.10, #1358) 지표 줄. 「이 핀 보기」는 맞는 핀(🚫 없음, 좌표 있음, 그날 영업)이 있는 카테고리 공백에서만 남아야 하고,
    검증(open_pin 검사)이 빼므로 맞는 핀이 없는 케이스의 검증 뒤 수는 0이어야 한다."""
    gap = [r for r in rows if r.get("diagnosis") == "category_gap"]
    want_pin = [r for r in gap if r.get("expected_pins")]
    no_pin = [r for r in gap if not r.get("expected_pins")]
    gap_sug = [r for r in gap if r.get("decision") == "suggest"]
    splits = [r for r in rows if r.get("diagnosis") == "split"]
    raw = [fx.outside_slots(a["text"]) for r in rows for a in r.get("raw_advice", [])]
    return [
        f"| 엮기: 「이 핀 보기」 기대 — 검증 뒤 고른 핀이 기대 핀 | "
        f"{_pct(sum(bool(r['kept_pins']) and set(r['kept_pins']) <= set(r['expected_pins']) for r in want_pin), len(want_pin))} |",
        f"| 엮기: 맞는 핀 없음 — open_pin 원문/검증 뒤(검증 뒤는 0이어야 한다) | "
        f"{sum('open_pin' in r.get('raw_actions', []) for r in no_pin)}/{sum(bool(r['kept_pins']) for r in no_pin)} (호출 {len(no_pin)}) |",
        f"| 엮기: 🚫 달린 핀을 try_in_schedule에 넣음(카테고리 공백) | {_pct(sum(bool(r['against_tried']) for r in gap), len(gap))} |",
        f"| 엮기: 끼워 본 결과의 claim이 남음(카테고리 공백 suggest 중) | {_pct(sum(r['schedule_claimed'] for r in gap_sug), len(gap_sug))} |",
        f"| 엮기: 갈림에서 try_in_schedule을 부름 / 그 claim이 남음 | "
        f"{_pct(sum(bool(r['try_pins']) for r in splits), len(splits))} / {sum(r['schedule_claimed'] for r in splits)} |",
        f"| 엮기: 원문(슬롯 밖)에 날 별칭(d1 …)을 쓴 문장 — 검증이 뺀다 | {sum(bool(_DAY_ALIAS.search(t)) for t in raw)}/{len(raw)} |",
    ]


def _echo_cases(by_case: Mapping[str, list[dict[str, Any]]]) -> list[str]:
    """지시문 케이스별 결정 지시(#717). 칸마다 그 문구가 나온 호출 수와 문구."""
    head = "| 케이스 | 결정 일치 | 원문 슬롯 밖 | 렌더 text 조각 | 인용 조각(참고) |"
    out = ["", "지시문 케이스(결정 지시, 케이스 문구로 판정)", "", head, "|---|---|---|---|---|"]
    for cid, rs in by_case.items():
        if not any(r.get("injection") for r in rs):
            continue
        cells = [f"{sum(r['decision_match'] for r in rs)}/{len(rs)}"]
        for key in ("raw_echo", "shown_echo", "quoted_echo"):
            hits = Counter(p for r in rs for p in r[key])
            cells.append(f"{sum(bool(r[key]) for r in rs)}/{len(rs)}" + (f" ({', '.join(hits)})" if hits else ""))
        out.append(f"| {cid} | " + " | ".join(cells) + " |")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--cases", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--tag", default="")
    parser.add_argument("--summarize", default="", help="저장된 결과 JSON으로 요약만 다시 낸다(모델을 부르지 않는다)")
    args = parser.parse_args()

    if args.summarize:
        saved = json.loads(Path(args.summarize).read_text(encoding="utf-8"))
        report = summarize(fx.load_cases(), saved["diagnosis"])
        Path(args.summarize).with_suffix(".md").write_text(report, encoding="utf-8")
        print(report)
        return 0

    if not (settings.elice_ml_api_base_url and settings.elice_ml_api_key):
        print("ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 없다", file=sys.stderr)
        return 2
    llm_client._client = RecordingClient(llm_client.make_client())

    cases = fx.load_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    jobs = [(c, i) for c in cases if c["expect"]["target"] for i in range(args.runs)]

    started = time.monotonic()

    def go(job):
        case, i = job
        try:
            return run_diagnosis(case, i)
        except Exception as exc:  # noqa: BLE001 — 평가 도구. 한 건이 실패해도 나머지를 본다
            return {"case": case["id"], "run": i, "crash": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        done = list(pool.map(go, jobs))
    diag = [r for r in done if "crash" not in r]
    crashes = [r for r in done if "crash" in r]

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{AGENT_DIAGNOSE_PROMPT_VERSION}{('-' + args.tag) if args.tag else ''}"
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps({"diagnosis": diag, "crashes": crashes}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    report = summarize(cases, diag)
    report += f"\n총 {len(jobs)}건, 크래시 {len(crashes)}, 걸린 시간 {time.monotonic() - started:.0f}초\n"
    (RESULTS_DIR / f"{name}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"저장: {RESULTS_DIR / name}.json, .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
