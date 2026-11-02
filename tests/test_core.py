"""핵심 판정 규칙 단위 테스트.  실행: python -m pytest tests -q

실제 회의록 없이 작은 가짜 표로 규칙이 의도대로 동작하는지 확인한다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import hypotheses as HY  # noqa: E402
from src.dashboard import issue_extras  # noqa: E402
from src.issues import apply_issue_start, drop_fragment_surfaces  # noqa: E402
from src.predict import make_rows  # noqa: E402
from src.spread import analyze_issue  # noqa: E402

ISSUE = "청소년 버스비"
TOPIC = (["청소년버스비"], ["청소년", "버스비"])


def mention(asm, date, ctx, speaker="○○○ 의원", iid=1, doc=None):
    return dict(issue_id=iid, utt_id=hash((asm, date, ctx)) % 10**9, doc_id=doc if doc is not None else hash((asm, date)) % 10**6,
                assembly=asm, date=pd.Timestamp(date), minutes_name="본회의 회의록 제1회", committee="본회의",
                speaker=speaker, matched=ISSUE, snippet=ctx, context=ctx)


def grades(rows):
    s = analyze_issue(pd.DataFrame(rows), TOPIC)
    return {t["assembly"]: t["evidence"] for t in s["timeline"]}


# ---------- 확산 근거 등급 (spread.py) ----------
def test_formal_reference_to_earlier_council_is_strong():
    rows = [mention("충남", "2024-04-01", "충남형 청소년 버스비 지원을 시작합니다."),
            mention("전북", "2025-07-18", "본 조례안의 제안설명을 드리겠습니다. 충남도에서 이미 시행하고 있는 청소년 버스비 지원을 우리 도에도 도입하려는 것입니다.")]
    assert grades(rows)["전북"] == "strong"


def test_question_reference_is_medium():
    rows = [mention("충남", "2024-04-01", "충남형 청소년 버스비 지원을 시작합니다."),
            mention("전북", "2025-07-18", "충남도에서 이미 시행하고 있는 청소년 버스비 지원을 우리도 검토해야 하지 않습니까?")]
    assert grades(rows)["전북"] == "medium"


def test_same_day_is_not_precedence_and_needs_time_claim():
    # 같은 날 처음 다룬 의회는 '먼저 했다'고 볼 수 없다. 시점 진술(이미, ~부터)도 없으면 참조로 인정하지 않는다.
    rows = [mention("충남", "2024-04-01", "청소년 버스비 지원을 검토합니다."),
            mention("전북", "2024-04-01", "충남처럼 청소년 버스비 지원을 하면 좋겠습니다.")]
    assert grades(rows)["전북"] == "temporal"


def test_reference_long_after_adoption_is_post_hoc():
    rows = [mention("충남", "2024-01-10", "청소년 버스비 지원을 시작합니다."),
            mention("전북", "2024-03-01", "청소년 버스비 지원 예산을 편성했습니다."),
            mention("전북", "2025-06-01", "충남도에서 이미 시행하고 있는 청소년 버스비 지원과 비교해 보겠습니다.")]
    s = analyze_issue(pd.DataFrame(rows), TOPIC)
    t = {x["assembly"]: x for x in s["timeline"]}["전북"]
    assert t["evidence"] == "temporal" and t["post_refs"]


def test_reference_about_other_topic_is_ignored():
    # 같은 발언 안에서 다른 사업의 타 지역 사례를 말한 문장은 이 의제의 선례가 아니다(대상 일치).
    rows = [mention("충북", "2024-02-01", "청소년 버스비 지원 조례안입니다."),
            mention("전북", "2024-05-01", "충북 사례는 노인 봉사일자리를 운영하고 있는 것입니다. 청소년 버스비 지원도 검토하겠습니다.")]
    assert grades(rows)["전북"] == "temporal"


def test_joint_action_is_not_reference():
    rows = [mention("광주", "2024-02-01", "청소년 버스비 지원 조례안입니다."),
            mention("전남", "2024-05-01", "전남도와 광주시는 청소년 버스비 지원을 함께 추진하고 있습니다.")]
    assert grades(rows)["전남"] == "temporal"


# ---------- 이슈 사전 보정 (issues.py) ----------
def test_fragment_surface_starting_mid_word_is_dropped():
    iss = pd.DataFrame([dict(issue_id=0, label="산업위기 선제대응지역",
                             surfaces=["산업위기선제대응지역", "산업위기선제", "위기선제"])])
    out, n = drop_fragment_surfaces(iss)
    assert n == 1 and "위기선제" not in out.surfaces[0] and "산업위기선제" in out.surfaces[0]


def test_issue_start_drops_earlier_event_mentions(tmp_path):
    f = tmp_path / "start.txt"
    f.write_text("대통령 탄핵: 2024-12-03\n", encoding="utf-8")
    iss = pd.DataFrame([dict(issue_id=7, label="대통령 탄핵")])
    m = pd.DataFrame([dict(issue_id=7, date=pd.Timestamp("2024-11-12")), dict(issue_id=7, date=pd.Timestamp("2024-12-10"))])
    out, n = apply_issue_start(m, iss, str(f))
    assert n == 1 and out.date.min() == pd.Timestamp("2024-12-10")


# ---------- 법률 대응 언급 탐지 (dashboard.py) ----------
def test_law_demand_kept_and_top_down_compliance_dropped():
    rows = [mention("전남", "2025-01-10", "청소년 버스비 지원 특별법 제정을 촉구하는 건의안입니다."),
            mention("경기", "2025-01-11", "상위법 개정에 따라 청소년 버스비 지원 조례의 인용 조항을 정비하였습니다.")]
    ex = issue_extras(pd.DataFrame(rows), [1])[1]["law"]
    assert ex["n_asm"] == 1 and ex["quotes"][0]["a"] == "전남"


# ---------- 예측 표본의 미래 정보 차단 (predict.py) ----------
def test_features_do_not_use_information_after_cutoff():
    T = pd.Timestamp("2024-06-30")
    base = [mention("서울", "2024-02-01", "청소년 버스비"), mention("경기", "2024-05-01", "청소년 버스비")]
    future = [mention("인천", "2024-08-01", "청소년 버스비"), mention("강원", "2024-09-01", "청소년 버스비")]
    docs = pd.DataFrame(dict(assembly=["서울", "경기", "인천", "강원", "충북"], date=pd.to_datetime(["2024-03-01"] * 5)))
    asms = sorted(docs.assembly)
    a = make_rows(pd.DataFrame(base), docs, asms, T)
    b = make_rows(pd.DataFrame(base + future), docs, asms, T)
    cols = [c for c in a.columns if not c.startswith("_")]
    pd.testing.assert_frame_equal(a[cols].reset_index(drop=True), b[cols].reset_index(drop=True))


# ---------- Bass 위험률 모형 (hypotheses.py) ----------
def test_bass_fit_recovers_parameters_on_simulated_data():
    rng = np.random.default_rng(0)
    M, p, q, dt = 17, 0.02, 0.10, 0.25
    segs = []
    for _ in range(400):
        n, t, out = 1, 0.0, []
        while t < 24 and n < M:
            h = p + q * n / M
            k = rng.binomial(M - n, 1 - np.exp(-h * dt))  # 짧은 구간 근사
            out.append((n, dt, k))
            n, t = n + k, t + dt
        segs.append(out)
    ph, qh = HY._bass_fit(segs, M)
    assert abs(ph - p) < 0.006 and abs(qh - q) < 0.03
