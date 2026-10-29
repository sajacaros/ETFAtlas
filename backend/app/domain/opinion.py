"""매수 의견: 관점별(차트·재무·보고서) 판정을 종합 의견으로 묶는 규칙.

관점별 판정은 LLM이 화면 데이터 요약을 읽고 내리지만, 종합은 같은 판정이면 늘 같은 답이 나오게 여기서 정한다.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

RATINGS = ("긍정", "다소 긍정", "중립", "다소 부정", "부정", "판단 불가")
SCORE = {"긍정": 2, "다소 긍정": 1, "중립": 0, "다소 부정": -1, "부정": -2}

BUY = "사 볼 만하다"
WAIT = "지켜본다"
AVOID = "사지 않는 편이 낫다"
UNDECIDED = "판단 보류"

MIN_JUDGED = 2  # 판정할 수 있는 관점이 이보다 적으면 종합하지 않는다
BUY_AT = 1.0    # 평균 점수가 이 이상이면 BUY
AVOID_AT = -1.0  # 이 이하면 AVOID


@dataclass
class Verdict:
    label: str
    score: Optional[float]  # 판정한 관점들의 평균 (-2 ~ 2)
    judged: int
    reason: str  # 왜 그 종합인지 (규칙으로 설명)


def combine(ratings: Dict[str, str]) -> Verdict:
    """관점 → 판정. 판정한 관점이 MIN_JUDGED개 미만이면 보류, 평균 점수로 정하되 '부정'이 하나라도 있으면 사지 않는다."""
    scores = {k: SCORE[r] for k, r in ratings.items() if r in SCORE}
    if len(scores) < MIN_JUDGED:
        return Verdict(UNDECIDED, None, len(scores), f"판단할 수 있는 관점이 {len(scores)}개뿐이라 종합하지 않았습니다")
    avg = sum(scores.values()) / len(scores)
    negative: List[str] = [k for k, s in scores.items() if s == SCORE["부정"]]
    if avg <= AVOID_AT:
        return Verdict(AVOID, avg, len(scores), f"관점 평균 {avg:+.1f}점으로 {AVOID_AT:+.0f}점 이하")
    if negative:
        return Verdict(WAIT, avg, len(scores), f"{', '.join(negative)} 관점이 부정이라 평균({avg:+.1f}점)과 상관없이 사지 않고 지켜봅니다")
    if avg >= BUY_AT:
        return Verdict(BUY, avg, len(scores), f"관점 평균 {avg:+.1f}점으로 {BUY_AT:+.0f}점 이상, 부정인 관점 없음")
    return Verdict(WAIT, avg, len(scores), f"관점 평균 {avg:+.1f}점 ({AVOID_AT:+.0f}점과 {BUY_AT:+.0f}점 사이)")
