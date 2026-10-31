"""분석 결과 -> 오프라인 인터랙티브 대시보드(단일 HTML, 외부 라이브러리·인터넷 불필요).

화면 구성 (템플릿: dashboard_template.html)
  1) 개요: 대표 이슈의 확산 과정을 월 단위로 재생하는 지도, 주요 확산 사례, 동시다발 이슈, 의회 혁신성
  2) 이슈: 이슈 목록 + 선택 이슈의 확산 지도(타일 카토그램), 누적 채택 곡선(S-curve),
     월별 언급량, 의회별 근거 원문 타임라인, 향후 확산 예측
  3) 의회: 의회 선택 지도, 의회별 처음 꺼낸 이슈·특징적 이슈, 혁신성 순위(Walker, 1969)
  4) 예측 모델: 시점 이동 백테스트 결과, 특징별 계수
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .regions import ASSEMBLY_NAME, REGIONS

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


def build_payload(docs, issues, spread, preds, metrics, weights, ranked_novel, n_utts, asm_keywords=None, mentions=None):
    iss_map = {int(r["issue_id"]): r for r in issues.to_dict("records")}
    pred_by = {}
    if len(preds):
        for iid, g in preds.sort_values("p", ascending=False).groupby("issue_id"):
            pred_by[int(iid)] = [dict(a=r.assembly, p=round(float(r.p), 3), tier=r.tier, why=list(r.reasons))
                                 for r in g.itertuples(index=False)]   # 미관측 의회 전체(정책 공백 분석에 사용)
    out = []
    for iid in ranked_novel:
        s, it = spread[iid], iss_map[iid]
        tl = []
        for t in s["timeline"]:
            refs = [dict(src=r["source"], date=_d(r["date"]), m=r["minutes_name"], sp=r["speaker"],
                         q=_clip(r["snippet"], 300), ok=bool(r["consistent"])) for r in t["explicit_refs"][:2]]
            ns = t.get("nonspec_ref")
            tl.append(dict(a=t["assembly"], date=_d(t["first_date"]), lag=t["lag_days"], rel=t["relation"],
                           m=t["minutes_name"], sp=t["speaker"], q=_clip(t["snippet"]), refs=refs,
                           ns=(dict(date=_d(ns["date"]), m=ns["minutes_name"], q=_clip(ns["snippet"], 300))
                               if ns else None)))
        out.append(dict(id=iid, label=it["label"], variants=[v for v in it["variants"] if v != it["label"]][:4],
                        src=it["source"], type="B" if s["simultaneous"] else "A",
                        n_asm=s["n_assemblies"], n_docs=s["n_docs"], n_m=s["n_mentions"],
                        n_exp=s["n_explicit"], upstream=s["upstream_flag"], tl=tl,
                        monthly=s["monthly"], pred=pred_by.get(iid, [])))

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
                  n_A=sum(i["type"] == "A" for i in out), n_B=sum(i["type"] == "B" for i in out)),
        names=ASSEMBLY_NAME, tiles=TILE, geo=GEO, issues=out, innovation=innovation, profiles=profiles, nbr={a: v["nbr"] for a, v in REGIONS.items()},
        lead=lead, both=both, explicit=explicit, metrics=m, weights=weights or {})


def write_dashboard(path, payload):
    data = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


GEO = json.loads((Path(__file__).with_name("korea_geo.json")).read_text(encoding="utf-8"))
TEMPLATE = (Path(__file__).with_name("dashboard_template.html")).read_text(encoding="utf-8")
