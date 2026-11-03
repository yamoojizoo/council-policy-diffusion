"""분석 결과 -> 오프라인 인터랙티브 대시보드(단일 HTML, 외부 라이브러리·인터넷 불필요).

화면 구성 (템플릿: dashboard_template.html)
  1) 개요: 대표 이슈의 확산 과정을 월 단위로 재생하는 지도, 주요 확산 사례, 동시다발 이슈, 의회 혁신성
  2) 이슈: 이슈 목록 + 선택 이슈의 확산 지도(타일 카토그램), 누적 채택 곡선(S-curve),
     월별 언급량, 의회별 근거 원문 타임라인, 향후 확산 예측
  3) 의회: 의회 선택 지도, 의회별 처음 꺼낸 이슈·특징적 이슈, 혁신성 순위(Walker, 1969)
  4) 예측 모델: 시점 이동 백테스트 결과, 특징별 계수
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .regions import ALIAS_RE, ASSEMBLY_NAME, REGIONS
from .spread import CUE, REF_WINDOW

# 4열 x 5행 타일 카토그램 (대략적인 지리 배치)
TILE = {"인천": (0, 0), "서울": (1, 0), "경기": (2, 0), "강원": (3, 0),
        "충남": (0, 1), "세종": (1, 1), "충북": (2, 1), "경북": (3, 1),
        "전북": (0, 2), "대전": (1, 2), "대구": (2, 2), "울산": (3, 2),
        "광주": (0, 3), "전남": (1, 3), "경남": (2, 3), "부산": (3, 3),
        "제주": (0, 4)}


def _d(x):
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def _clip(s, n=240):
    s = str(s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


FIELDS = [("교육", r"교육"), ("복지·보건", r"복지|보건|여성|가족"), ("환경·기후", r"환경|기후|탄소|수자원"),
          ("경제·산업", r"경제|산업|노동|과학|미래|일자리"), ("농림·해양", r"농|수산|해양|축산"),
          ("건설·교통·도시", r"건설|교통|도시|주택|공간|균형"), ("안전·소방", r"안전|소방"),
          ("문화·관광·체육", r"문화|관광|체육"), ("행정·자치", r"행정|자치|기획|운영|정책")]
_FIELD_RE = [(f, re.compile(rx)) for f, rx in FIELDS]
_NONTOPIC = re.compile(r"본회의|예산결산|^기타$|^상임위원회$|^특별위원회$|행정사무감사$|^$")
# 그 의제를 언급한 같은 문장에서 법률 차원의 대응을 요구하는 표현
# '법적 근거', '입법 취지'처럼 조례 심사에서 상투적으로 쓰는 표현은 지방 차원이라 뺐다
LAWREQ = re.compile(r"법\s?개정|법률\s?개정|개정\s?법률|상위\s?법|법제화|입법(?!\s?(?:예고|취지|목적|배경|과정|정책관|조사관))|"
                                  r"국회에\s?(?:건의|요청|촉구|계류)|시행령\s?개정|법령\s?(?:정비|개정)|법\s?제정|특별법")
# 법 개정을 '요구'하는 문장만 남긴다(이미 바뀐 상위법을 조례에 반영하는 문장은 하향식 정비라서 제외)
DEMAND = re.compile(r"필요|촉구|건의|요청|요구|시급|해야|돼야|되어야|마련돼|마련해|개선해|바랍니다|부탁")
COMPLY = re.compile(r"반영|따라|따른|현행화|정비하|정비를|개정됨|제정되면서|분리됨|인용\s?조항|준용")
ORD = re.compile(r"조례안|조례\s?(?:일부|전부)?\s?개정|조례를?\s?(?:제정|발의)")
_SENT = re.compile(r"(?<=[다요까죠])[.?!]\s+|(?<=[.?!])\s+")


def _sentence(ctx, matched):
    for s in _SENT.split(str(ctx)):
        if matched and matched in s:
            return s
    return ""


def issue_extras(mentions, ids):
    """의제별 소관 분야(언급된 상임위원회 기준), 조례안으로 다룬 의회, 법 개정·국회 대응 요구 발언을 정리한다."""
    out = {}
    if mentions is None or not len(mentions):
        return out
    m = mentions[mentions.issue_id.isin(ids)]
    for iid, g in m.groupby("issue_id"):
        score = {}
        for com, n in g.committee.fillna("").value_counts().items():
            if _NONTOPIC.search(com):
                continue
            hit = [f for f, rx in _FIELD_RE if rx.search(com)]
            for f in hit:
                score[f] = score.get(f, 0) + n / len(hit)
        tot = sum(score.values())
        field = max(score, key=score.get) if score and score[max(score, key=score.get)] / tot >= 0.3 else "복합"
        sents = [(_sentence(c, mt), r) for c, mt, r in zip(g.context, g.matched, g.itertuples(index=False))]
        ord_asm = sorted({r.assembly for s, r in sents if ORD.search(s)})
        law = [(s, r) for s, r in sents if len(s) <= 300 and LAWREQ.search(s) and DEMAND.search(s) and not COMPLY.search(s)]
        quotes, seen = [], set()
        for s, r in sorted(law, key=lambda x: x[1].date):
            if r.assembly in seen:
                continue
            seen.add(r.assembly)
            quotes.append(dict(a=r.assembly, date=_d(r.date), m=r.minutes_name, sp=r.speaker, q=_clip(s, 260)))
        out[int(iid)] = dict(field=field, ord_asm=ord_asm,
                             law=dict(n_asm=len({r.assembly for _, r in law}), n=len(law), quotes=quotes[:3]))
    return out


_SEARCH_EXTRA = re.compile(r"사례|벤치마킹|처럼|타\s?시[·ㆍ]?도|다른\s?(?:시[·ㆍ]?도|지자체|지역)|전국\s?최초|특별법|법\s?개정|건의|촉구")


def search_corpus(mentions, ids, per_asm=3, per_issue=40):
    """대시보드 '회의록 원문 검색'용 발언 표본. 의제마다 의회별로 처음·중간·마지막 언급을 고르게 뽑는다(파일 크기 제한)."""
    if mentions is None or not len(mentions):
        return []
    m = mentions[mentions.issue_id.isin(ids)].sort_values("date").drop_duplicates(["issue_id", "doc_id"])
    out = []
    for iid, g in m.groupby("issue_id"):
        rows = []
        for _, h in g.groupby("assembly"):
            k = len(h)
            pick = sorted({0, k // 2, k - 1})[:per_asm]
            rows += [h.iloc[j] for j in pick]
        rows = sorted(rows, key=lambda r: r.date)[:per_issue]
        # 타 지역 사례·법률 대응을 말한 발언은 검색 수요가 커서 따로 더 담는다(의제당 최대 30건)
        seen = {r.doc_id for r in rows}
        extra = g[g.context.str.contains(_SEARCH_EXTRA) & ~g.doc_id.isin(seen)].head(30)
        out += [[int(iid), r.assembly, _d(r.date), str(r.minutes_name), str(r.speaker or ""), _clip(r.snippet, 230)] for r in rows]
        out += [[int(iid), r.assembly, _d(r.date), str(r.minutes_name), str(r.speaker or ""), _clip(r.context, 420)]
                for _, r in extra.iterrows()]
    return out


def build_payload(docs, issues, spread, preds, metrics, weights, ranked_novel, n_utts, asm_keywords=None, mentions=None, upd=None):
    iss_map = {int(r["issue_id"]): r for r in issues.to_dict("records")}
    pred_by = {}
    if len(preds):
        for iid, g in preds.sort_values("p", ascending=False).groupby("issue_id"):
            pred_by[int(iid)] = [dict(a=r.assembly, p=round(float(r.p), 3), tier=r.tier, why=list(r.reasons))
                                 for r in g.itertuples(index=False)]   # 미관측 의회 전체(정책 공백 분석에 사용)
    extras = issue_extras(mentions, list(ranked_novel))
    out = []
    for iid in ranked_novel:
        s, it = spread[iid], iss_map[iid]
        tl = []
        for t in s["timeline"]:
            refs = [dict(src=r["source"], date=_d(r["date"]), m=r["minutes_name"], sp=r["speaker"],
                         q=_clip(r["snippet"], 300), ok=bool(r["consistent"]), g=r.get("grade", "medium"),
                         formal=bool(r.get("formal", False))) for r in t["explicit_refs"][:2]]
            ns = t.get("nonspec_ref")
            tl.append(dict(a=t["assembly"], date=_d(t["first_date"]), lag=t["lag_days"], rel=t["relation"], ev=t.get("evidence", t["relation"]),
                           m=t["minutes_name"], sp=t["speaker"], q=_clip(t["snippet"]), refs=refs,
                           ns=(dict(date=_d(ns["date"]), m=ns["minutes_name"], q=_clip(ns["snippet"], 300))
                               if ns else None)))
        out.append(dict(id=iid, label=it["label"], variants=[v for v in it["variants"] if v != it["label"]][:4],
                        src=it["source"], type="B" if s["simultaneous"] else "A",
                        n_asm=s["n_assemblies"], n_docs=s["n_docs"], n_m=s["n_mentions"],
                        n_exp=s["n_explicit"], upstream=s["upstream_flag"], tl=tl,
                        monthly=s["monthly"], pred=pred_by.get(iid, []),
                        field=extras.get(iid, {}).get("field", "복합"), ord_asm=extras.get(iid, {}).get("ord_asm", []),
                        law=extras.get(iid, {}).get("law", dict(n_asm=0, n=0, quotes=[]))))

    # 의회별 혁신성: A형 이슈에서의 채택 순위 백분위 평균 (먼저 다룰수록 1에 가까움)
    inno = {a: [] for a in REGIONS}
    origin_cnt = {a: 0 for a in REGIONS}
    for it in out:
        if it["type"] != "A":
            continue
        n = len(it["tl"])
        for i, t in enumerate(it["tl"]):
            if t["a"] in inno:
                inno[t["a"]].append(1 - i / max(n - 1, 1))
        if it["tl"] and it["tl"][0]["a"] in origin_cnt:
            origin_cnt[it["tl"][0]["a"]] += 1
    innovation = sorted(
        [dict(a=a, name=ASSEMBLY_NAME[a], score=round(float(np.mean(v)), 3) if v else 0, n=len(v),
              origin=origin_cnt[a]) for a, v in inno.items()], key=lambda x: -x["score"])

    # 의회별 프로필: 처음 관측한 이슈, 참여 이슈, 특징적 이슈
    profiles = {}
    for a in REGIONS:
        led = [dict(id=it["id"], label=it["label"], n=it["n_asm"]) for it in out
               if it["type"] == "A" and it["tl"] and it["tl"][0]["a"] == a][:8]
        joined = sum(1 for it in out if any(t["a"] == a for t in it["tl"]))
        docs_a = docs[docs.assembly == a]
        profiles[a] = dict(led=led, joined=joined, n_docs=int(len(docs_a)),
                           keywords=[dict(label=k, n=int(n)) for k, n in (asm_keywords or {}).get(a, [])][:6])
    # 의회 간 선행 빈도: 점진 확산형 이슈에서 x가 y보다 30일 이상 먼저 관측된 이슈 수 (인과가 아닌 시간 순서 통계)
    codes = list(REGIONS)
    lead = {x: {y: 0 for y in codes} for x in codes}
    both = {x: {y: 0 for y in codes} for x in codes}
    explicit = {x: {y: 0 for y in codes} for x in codes}
    for it in out:
        if it["type"] != "A":
            continue
        dates = {t["a"]: pd.Timestamp(t["date"]) for t in it["tl"]}
        for x, dx in dates.items():
            for y, dy in dates.items():
                if x == y or x not in lead or y not in lead:
                    continue
                both[x][y] += 1
                if (dy - dx).days >= 30:
                    lead[x][y] += 1
        for t in it["tl"]:
            for r in t["refs"]:
                if r["src"] in explicit and t["a"] in explicit:
                    explicit[r["src"]][t["a"]] += 1
    # 의회별 특화 이슈: 관련 회의록의 절반 이상이 한 의회에 몰린 이슈 (지나가는 말·일반 표현 제외)
    special = {a: [] for a in REGIONS}
    if mentions is not None and len(mentions):
        lab = dict(zip(issues.issue_id, issues.label))
        src = dict(zip(issues.issue_id, issues.source))
        g = mentions.groupby(["issue_id", "assembly"]).doc_id.nunique().rename("n").reset_index()
        tot = g.groupby("issue_id").n.sum()
        g["tot"] = g.issue_id.map(tot)
        g["share"] = g.n / g.tot
        g = g[(g.n >= 10) & (g.share > 0.5) & g.issue_id.isin(lab)]
        in_dash = {it["id"] for it in out}
        for r in g.sort_values("n", ascending=False).itertuples(index=False):
            sp_ = spread.get(int(r.issue_id), {})
            if src.get(r.issue_id) == ["신규키워드"] and sp_.get("rep2", 1) < 0.1:
                continue
            if r.assembly in special and len(special[r.assembly]) < 8:
                special[r.assembly].append(dict(label=lab[r.issue_id], n=int(r.n), share=round(float(r.share), 2),
                                                tot=int(r.tot), id=int(r.issue_id) if int(r.issue_id) in in_dash else None,
                                                n_asm=int(sp_.get("n_assemblies", 1))))
    for a in profiles:
        profiles[a]["special"] = special.get(a, [])
    m = {k: v for k, v in (metrics or {}).items()}
    return dict(
        meta=dict(d0=_d(docs.date.min()), d1=_d(docs.date.max()), n_docs=int(len(docs)), n_utts=int(n_utts),
                  n_asm=int(docs.assembly.nunique()), n_issues=int(len(issues)),
                  n_A=sum(i["type"] == "A" for i in out), n_B=sum(i["type"] == "B" for i in out),
                  n_ranked=_n_ranked(issues, spread, docs.date.min()),
                  n_ev=sum(t["ev"] in ("strong", "medium") for i in out for t in i["tl"])),
        names=ASSEMBLY_NAME, tiles=TILE, geo=GEO, issues=out, innovation=innovation, profiles=profiles, nbr={a: v["nbr"] for a, v in REGIONS.items()},
        lead=lead, both=both, explicit=explicit, metrics=m, weights=weights or {}, fields=[f for f, _ in FIELDS] + ["복합"], texts=search_corpus(mentions, list(ranked_novel)),
        upd=_upd_summary(upd),
        rx=dict(alias={a: rx.pattern for a, rx in ALIAS_RE.items()}, cue=CUE.pattern, window=REF_WINDOW))


def _upd_summary(u):
    """갱신 보고서(update.py) 중 대시보드에 보일 부분만 추린다."""
    if not u:
        return None
    c = u.get("check") or {}
    return dict(sim=u.get("simulated", False), n_ji=u.get("n_joined_issues", len(u["joined"])), prev_d1=u["prev_d1"], d1=u["d1"], days=u["days"], new_docs=u["new_docs"],
                check=dict(n=c.get("n", 0), n_hit=c.get("n_hit", 0), base=c.get("base"), auc=c.get("auc"),
                           p10=c.get("p_at_10"), tiers=c.get("tiers", {}), ex=c.get("examples", [])[:6]),
                joined=[dict(id=x["id"], label=x["label"], before=x["before"], after=x["after"],
                             new=[[t["a"], t["tier"]] for t in x["new"]]) for x in u["joined"][:12]],
                n_join=u["n_join"], n_join_pred=u["n_join_predicted"],
                emerged=[dict(id=e["id"], label=e["label"], a=e["origin"], date=e["date"], n=e["n"]) for e in u["emerged"][:8]],
                stage_up=[dict(id=x["id"], label=x["label"], frm=x["frm"], to=x["to"]) for x in u["stage_up"][:8]])


def _n_ranked(issues, spread, d0):
    """3개 이상 의회에서 관측되고 계절성·지나가는 말이 아닌 이슈 수(분석 깔때기 표시용)."""
    from .report import rank_issues   # 순환 import 방지
    try:
        return int(len(rank_issues(issues, spread, d0=d0)))
    except Exception:
        return None


def _font_css():
    """대시보드에 Pretendard(SIL OFL 1.1) 부분 글꼴을 내장한다. 어느 PC에서 열어도 같은 서체로 보이게 하려는 것."""
    import base64
    f = Path(__file__).with_name("assets") / "PretendardSubset.woff2"
    if not f.exists():
        return ""
    b64 = base64.b64encode(f.read_bytes()).decode()
    return ("@font-face{font-family:'Pretendard Embed';font-weight:45 920;font-style:normal;font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def write_dashboard(path, payload):
    data = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("/*__FONT__*/", _font_css()).replace("__DATA__", data)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


GEO = json.loads((Path(__file__).with_name("korea_geo.json")).read_text(encoding="utf-8"))
TEMPLATE = (Path(__file__).with_name("dashboard_template.html")).read_text(encoding="utf-8")
