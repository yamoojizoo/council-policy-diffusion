"""이슈별 최초 관측, 의회 간 후속 논의 흐름, 근거 유형 판정.

문제 조건: '전파·확산 흐름'은 시간적 선후관계와 명시적 상호 참조로만 추정하고,
근거 없이 인과를 단정하지 않는다. 그래서 각 후속 의회마다 근거 유형을 셋으로 나눈다.
  - explicit   : 회의록 원문에 특정 타 광역(지명)과 도입·사례 등 단서어가 함께 등장
  - nonspecific: '타 시·도', '다른 지자체' 등 비특정 참조만 존재
  - temporal   : 참조 표현 없음. 시간적 선후만 확인(인과 단정 불가)
"""
import re

import pandas as pd

from .regions import ALIAS_RE, ASSEMBLY_NAME

# 타 지역을 '선행 사례'로 언급하는 표현만 단서로 인정 (단순 '시행', '도입'은 너무 흔해서 제외)
# 타 지역을 '선행 사례'로 언급하는 표현만 단서로 인정 (단순 '시행', '도입'은 너무 흔해서 제외)
CUE = re.compile(r"(?:사례|벤치마킹|선진|본받|처럼|참고|따라\s?하|모범|롤\s?모델|"
                 r"이미\s?(?:시행|도입|운영|제정|추진|하고)|먼저\s?(?:시행|도입|제정)|"
                 r"(?:도입|시행|제정|운영|추진|지원)\s?(?:한|했|하고\s?있|하고있|중인|되고\s?있|되어\s?있)|"
                 r"(?:에서도|에서는|같은\s?경우|의\s?경우)[^.?!]{0,25}?(?:하고\s?있|되고\s?있|했|시행|운영|도입))")
NONSPEC = re.compile(r"(?:타\s?시[·ㆍ]?도|타\s?지자체|다른\s?(?:시[·ㆍ]?도|지자체|광역|지역|의회)|타\s?광역|타\s?지역|"
                     r"타\s?의회|전국\s?최초|전국적으로|여러\s?지자체)")
UPSTREAM = re.compile(r"(?:법\s?개정|법률\s?개정|개정\s?법률|시행령|상위법|중앙정부|정부\s?지침|행정안전부|보건복지부|"
                      r"교육부|국토교통부|국회에서|법이\s?시행|법\s?시행)")


_SENT = re.compile(r"(?<=[다요까죠])[.?!]\s+|(?<=[.?!])\s+")
# 지명 뒤에 붙으면 해당 광역의회/지자체의 정책을 가리키지 않는 경우 (대학·교육청·지역 묶음 등)
_NOT_GOV = r"(?!\s?(?:대학|대\b|대학교|도립대|교육청|교육감|통합|권|·|ㆍ|지역|출신|방향|쪽))"
REF_RE = {code: re.compile(rf"(?:{rx.pattern}){_NOT_GOV}[^.?!]{{0,30}}?(?:{CUE.pattern})") for code, rx in ALIAS_RE.items()}


def _issue_sentence(row):
    """이슈가 언급된 문장(앞뒤 1문장 포함)만 잘라낸다."""
    sents = _SENT.split(row.context)
    for i, s_ in enumerate(sents):
        if row.matched and row.matched in s_:
            return " ".join(sents[max(0, i - 1):i + 2])
    return row.snippet


def find_refs(row):
    """이슈 언급 문장 주변에서 '타 광역 지명 + (30자 이내) 선행사례 단서어' 구조를 찾는다."""
    sent, own = _issue_sentence(row), row.assembly
    if not CUE.search(sent):
        return [], sent
    return [code for code, rx in REF_RE.items() if code != own and rx.search(sent)], sent


def analyze_issue(m):
    """m: 한 이슈의 언급 테이블(날짜순)."""
    m = m.sort_values(["date", "doc_id", "utt_id"])
    firsts = m.groupby("assembly", sort=False).head(1).reset_index(drop=True)
    origin = firsts.iloc[0]
    first_dates = dict(zip(firsts.assembly, firsts.date))

    refs = []
    for r in m.itertuples(index=False):
        srcs, sent = find_refs(r)
        for src in srcs:
            refs.append(dict(target=r.assembly, source=src, date=r.date, minutes_name=r.minutes_name,
                             speaker=r.speaker, snippet=sent,
                             consistent=src in first_dates and first_dates[src] <= r.date))
    refs = pd.DataFrame(refs)
    nonspec = m[m.snippet.str.contains(NONSPEC)]
    upstream = m[m.context.str.contains(UPSTREAM)]

    timeline = []
    for i, f in firsts.iterrows():
        a = f.assembly
        ex = refs[refs.target == a] if len(refs) else refs
        ns = nonspec[nonspec.assembly == a]
        if i == 0:
            rel = "origin"
        elif len(ex):
            rel = "explicit"
        elif len(ns):
            rel = "nonspecific"
        else:
            rel = "temporal"
        timeline.append(dict(
            order=i + 1, assembly=a, assembly_name=ASSEMBLY_NAME.get(a, a), first_date=f.date,
            minutes_name=f.minutes_name, committee=f.committee, speaker=f.speaker, snippet=f.snippet,
            lag_days=int((f.date - origin.date).days), relation=rel,
            earlier=[x for x in firsts.assembly[:i]],
            explicit_refs=ex.drop_duplicates("source").head(3).to_dict("records") if len(ex) else [],
            nonspec_ref=(ns.iloc[0][["date", "minutes_name", "speaker", "snippet"]].to_dict() if len(ns) else None),
        ))

    # 상위법령·중앙정부 계기로 인한 '동시 대응' 가능성: 확산이 아니라 공통 외부요인일 수 있음
    lags = sorted(t["lag_days"] for t in timeline)
    burst = sum(1 for d in lags if d - lags[0] <= 90) if lags else 0
    early = m[m.date <= m.date.min() + pd.Timedelta(days=90)]  # 초기 동시 관측 구간의 언급만 본다
    upstream_share = float(early.context.str.contains(UPSTREAM).mean()) if len(early) else 0.0
    upstream_flag = bool(len(firsts) >= 3 and burst >= 3 and upstream_share >= 0.15)

    monthly = m.set_index("date").resample("MS").size()
    # 화제성: 한 회의록 안에서 두 번 이상 언급된 비율. 지나가며 한 번 쓰인 일반 표현은 0에 가깝다.
    rep2 = float((m.groupby("doc_id").size() >= 2).mean())
    # 계절성(매년 같은 달에 반복: 결산·예산·감사 시즌 절차어) 판정
    moy = m.groupby([m.date.dt.year, m.date.dt.month]).doc_id.nunique()
    by_month = moy.groupby(level=1).sum()
    top3 = by_month.nlargest(3)
    years_in_top = {y for (y, mo) in moy.index if mo in set(top3.index)}
    # 동시다발형: 관측 의회의 절반 이상이 최초 관측 후 60일 안에 등장 -> 의회 간 전파보다 공통 외부 사건(정부 정책·사회적 사건)
    lag_list = [int((d - firsts.date.iloc[0]).days) for d in firsts.date]
    simultaneous = bool(len(lag_list) >= 4 and sum(l <= 60 for l in lag_list) >= len(lag_list) / 2)
    # 집중도: 최초 관측 이후 월별 관련 회의록 수의 최댓값/평균 (일반 용어는 낮고, 현안성 이슈는 높음)
    mdocs = m.set_index("date").resample("MS").doc_id.nunique()
    burstiness = float(mdocs.max() / max(mdocs.mean(), 1e-9)) if len(mdocs) else 0.0
    seasonal = bool(top3.sum() / max(by_month.sum(), 1) >= 0.7 and len(years_in_top) >= 2)
    return dict(
        n_mentions=int(len(m)), n_assemblies=int(len(firsts)), n_docs=int(m.doc_id.nunique()),
        origin=timeline[0], timeline=timeline,
        n_explicit=int(sum(t["relation"] == "explicit" for t in timeline)),
        upstream_flag=upstream_flag, upstream_share=round(upstream_share, 3), seasonal=seasonal, rep2=round(rep2, 3), simultaneous=simultaneous, burstiness=round(burstiness, 2),
        upstream_example=(upstream.iloc[0][["assembly", "date", "minutes_name", "snippet"]].to_dict()
                          if len(upstream) else None),
        monthly={k.strftime("%Y-%m"): int(v) for k, v in monthly.items()},
    )


def analyze_all(mentions):
    return {int(iid): analyze_issue(g) for iid, g in mentions.groupby("issue_id")}
