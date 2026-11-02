"""이슈별 최초 관측, 의회 간 후속 논의 흐름, 확산 근거의 증거 등급 판정.

회의록은 관찰 자료라 인과를 증명할 수 없다. 그래서 Campbell의 인과 추론 조건(시간적 선행·공변·경쟁가설 배제)과
과정추적의 검증 유형(Van Evera 1997; Collier 2011)에 따라, 후속 의회마다 '어디까지 주장할 수 있는가'를 등급으로 매긴다.
  - strong     : 결정적 증거. 도입 시점의 공식 입법 논리(제안설명·검토보고)에서 먼저 다룬 타 광역을 같은 정책의 선례로 언급
  - medium     : 명시적 참조. 도입 시점에 같은 정책의 선례로 타 광역을 언급(질의·답변 등)
  - predata    : 데이터 이전 선행. 언급된 타 광역의 논의가 데이터 기간 안에서는 더 늦지만, 발언이 '이미/~부터' 시행을 진술
  - nonspecific: 약한 정황. '타 시·도' 등 출처를 특정하지 않은 참조
  - temporal   : 고리 검증만 통과. 시간적 선후만 확인(인과 단정 불가)
도입 후 REF_WINDOW일이 지나 나온 타 광역 언급은 경로 근거가 아니라 '사후 참조(post_refs)'로 따로 둔다.
relation 은 strong·medium·predata 를 explicit 로 묶은 3분류(explicit/nonspecific/temporal)로 유지한다.
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


REF_WINDOW = 180   # 도입 결정 시점 근접성: 정례회 주기(연 2회)와 예측 기간에 맞춘 값. 민감도는 기술문서 3.3 참고
# 공식 입법 논리: 조례안 제안설명·검토보고 맥락
FORMAL = re.compile(r"제안\s?(?:설명|이유)|대표\s?발의|검토\s?(?:보고|의견|결과)|(?:제정|개정)\s?이유|조례안의?\s?주요\s?내용")
FORMAL_SPEAKER = re.compile(r"전문위원|입법조사관|입법정책관")
# 데이터 이전 선행을 뒷받침하는 시점 진술
TIME_CUE = re.compile(r"이미|부터|\d{2,4}\s?년|시행\s?중|운영\s?중|추진\s?중|하고\s?있|되고\s?있|해\s?오")
GRADE_ORDER = ["strong", "medium", "predata", "nonspecific", "temporal"]
GRADE_KO = {"origin": "최초 관측", "strong": "결정적 증거", "medium": "명시적 참조", "predata": "데이터 이전 선행",
            "nonspecific": "비특정 참조", "temporal": "시간적 후행"}
_SENT = re.compile(r"(?<=[다요까죠])[.?!]\s+|(?<=[.?!])\s+")
# 지명 뒤에 붙으면 해당 광역의회/지자체의 정책을 가리키지 않는 경우 (대학·교육청·지역 묶음 등)
_NOT_GOV = r"(?!\s?(?:대학|대\b|대학교|도립대|교육청|교육감|통합|권|·|ㆍ|지역|출신|방향|쪽|[을를]\s?제외|만\s?빼))"
REF_RE = {code: re.compile(rf"(?:{rx.pattern}){_NOT_GOV}[^.?!]{{0,30}}?(?:{CUE.pattern})") for code, rx in ALIAS_RE.items()}


def _issue_window(row):
    """이슈가 언급된 문장과 앞뒤 1문장을 문장 목록으로 돌려준다."""
    sents = _SENT.split(row.context)
    for i, s_ in enumerate(sents):
        if row.matched and row.matched in s_:
            return sents[max(0, i - 1):i + 2]
    return [row.snippet]


def _on_topic(sent, topic):
    """대상 일치: 참조 문장 자체가 이 이슈를 가리키는가. 이슈 매칭 표현이 있거나, 대표 명칭 단어의 절반 이상이 들어 있어야 한다."""
    if topic is None:
        return True
    flat = re.sub(r"[\s·ㆍ]", "", sent)
    surfaces, words = topic
    if any(sf in flat for sf in surfaces):
        return True
    return bool(words) and sum(w in flat for w in words) * 2 >= len(words)


def _joint(sent, own, src):
    """'전남도와 광주시는 함께 추진'처럼 자기 지역과 나란히 묶인 경우는 선례 참조가 아니라 공동 추진이다."""
    o, t = ALIAS_RE[own].pattern, ALIAS_RE[src].pattern
    return bool(re.search(rf"(?:{o})\S{{0,3}}\s?(?:와|과|및|하고|,|·|ㆍ)\s?(?:{t})|(?:{t})\S{{0,3}}\s?(?:와|과|및|하고|,|·|ㆍ)\s?(?:{o})", sent))


def find_refs(row, topic=None):
    """이슈 언급 문장(앞뒤 1문장 포함) 중에서, 그 문장 자체가 이 이슈를 가리키고(대상 일치)
    '타 광역 지명 + 30자 이내 선행사례 단서어'가 있는 문장을 찾는다.
    대상 일치를 보지 않으면 같은 답변 속 다른 사업의 타 지역 사례가 붙는 오류가 생긴다."""
    win, own = _issue_window(row), row.assembly
    shown = " ".join(win)
    found, sents = [], []
    for sent in win:
        if not CUE.search(sent) or not _on_topic(sent, topic):
            continue
        for code, rx in REF_RE.items():
            if code != own and code not in found and rx.search(sent) and not _joint(sent, own, code):
                found.append(code); sents.append(sent)
    return found, shown, " ".join(sents)


def analyze_issue(m, topic=None):
    """m: 한 이슈의 언급 테이블(날짜순). topic: (매칭 표현 목록, 대표 명칭 단어 목록) - 대상 일치 판정용."""
    m = m.sort_values(["date", "doc_id", "utt_id"])
    firsts = m.groupby("assembly", sort=False).head(1).reset_index(drop=True)
    origin = firsts.iloc[0]
    first_dates = dict(zip(firsts.assembly, firsts.date))

    refs = []
    for r in m.itertuples(index=False):
        srcs, shown, sent = find_refs(r, topic)
        for src in srcs:
            tgt_first = first_dates[r.assembly]
            prior = src in first_dates and first_dates[src] < tgt_first       # 시간적 선행(데이터로 확인, 같은 날은 선행 아님)
            near = (r.date - tgt_first).days <= REF_WINDOW                     # 도입 시점 근접성
            formal = bool(FORMAL.search(r.context) or FORMAL_SPEAKER.search(str(r.speaker)))
            if prior and near:
                grade = "strong" if formal else "medium"
            elif not prior and near and TIME_CUE.search(sent):
                grade = "predata"
            elif prior:
                grade = "post"                                                 # 사후 참조: 경로 근거 아님
            else:
                continue                                                       # 선행 불확인 + 시점 진술 없음: 인정 안 함
            refs.append(dict(target=r.assembly, source=src, date=r.date, minutes_name=r.minutes_name,
                             speaker=r.speaker, snippet=shown, grade=grade, formal=formal,
                             consistent=src in first_dates and first_dates[src] <= r.date))
    refs = pd.DataFrame(refs)
    nonspec = m[m.snippet.str.contains(NONSPEC)]
    upstream = m[m.context.str.contains(UPSTREAM)]

    timeline = []
    for i, f in firsts.iterrows():
        a = f.assembly
        # 명시적 참조: 해당 의회가 이 이슈를 처음 다룬 시점 전후(최초 관측 후 REF_WINDOW일 이내)의 발언이고,
        # 참조한 의회가 그보다 먼저 이 이슈를 다룬 경우만 인정한다. (나중에 우연히 언급한 타 지역 사례는 제외)
        mine = refs[refs.target == a] if len(refs) else refs
        ex = mine[mine.grade != "post"] if len(mine) else mine
        post = mine[mine.grade == "post"] if len(mine) else mine
        if len(ex):
            ex = ex.assign(_o=ex.grade.map(GRADE_ORDER.index)).sort_values(["_o", "date"]).drop(columns="_o")
        ns = nonspec[(nonspec.assembly == a) & (nonspec.date <= f.date + pd.Timedelta(days=REF_WINDOW))]
        if i == 0:
            rel, grade = "origin", "origin"
        elif len(ex):
            rel, grade = "explicit", ex.grade.iloc[0]
        elif len(ns):
            rel, grade = "nonspecific", "nonspecific"
        else:
            rel, grade = "temporal", "temporal"
        timeline.append(dict(
            order=i + 1, assembly=a, assembly_name=ASSEMBLY_NAME.get(a, a), first_date=f.date,
            minutes_name=f.minutes_name, committee=f.committee, speaker=f.speaker, snippet=f.snippet,
            lag_days=int((f.date - origin.date).days), relation=rel,
            earlier=[x for x in firsts.assembly[:i]],
            evidence=grade,
            explicit_refs=ex.drop_duplicates("source").head(3).to_dict("records") if len(ex) else [],
            post_refs=post.drop_duplicates("source").head(2).to_dict("records") if len(post) else [],
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


def _topic(row):
    words = [w for w in re.split(r"\s+", row["label"]) if len(w) >= 2 and w not in ("및", "지원", "활성화", "운영", "설치", "관리")]
    return list(row["surfaces"]), words or [row["label"].replace(" ", "")]


def analyze_all(mentions, issues=None):
    topics = {int(r["issue_id"]): _topic(r) for r in issues.to_dict("records")} if issues is not None else {}
    return {int(iid): analyze_issue(g, topics.get(int(iid))) for iid, g in mentions.groupby("issue_id")}
