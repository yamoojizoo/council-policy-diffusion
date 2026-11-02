"""분석 결과 -> 항목별 서술형 보고서(Markdown) + 기계가독 JSON."""
import json
import math
from .spread import GRADE_KO, REF_WINDOW

import pandas as pd

from .regions import ASSEMBLY_NAME

REL_KO = {
    "origin": "최초 관측",
    "explicit": "명시적 참조",
    "nonspecific": "비특정 참조",
    "temporal": "시간적 후행(참조 없음)",
}


def _d(x):
    return pd.Timestamp(x).strftime("%Y.%m.%d")


def _q(s, n=260):
    s = str(s).replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def _cite(asm, date, minutes, speaker=None):
    sp = f", {speaker}" if speaker and speaker not in ("(미상)", "(회의록 머리말)") and "회의록" not in speaker else ""
    return f"{ASSEMBLY_NAME.get(asm, asm)} 「{minutes}」({_d(date)}{sp})"


def rank_issues(issues, spread, d0=None, novelty_days=90):
    """우선순위: 여러 의회로 퍼졌고, 조례(제도화)로 이어졌으며, 명시적 참조가 있고, 현안성(집중도)이 높은 이슈."""
    rows = []
    for r in issues.itertuples(index=False):
        s = spread.get(int(r.issue_id))
        if not s or s["n_assemblies"] < 3 or s.get("seasonal"):
            continue
        if r.source == ["신규키워드"] and s.get("rep2", 1) < 0.08:
            continue  # 한 회의록 안에서 거의 반복되지 않는 표현은 지나가는 말로 보고 제외
        score = (1.5 * min(s["n_assemblies"], 12) + 2.0 * s["n_explicit"] + 1.5 * math.log1p(s.get("burstiness", 0))
                 + 0.5 * math.log1p(s["n_docs"]) + (3.0 if "조례" in r.source else 0)
                 + (2.0 if "신규키워드" in r.source and "조례" in r.source else 0))
        rows.append((score, int(r.issue_id)))
    return [iid for _, iid in sorted(rows, reverse=True)]


def issue_section(rank, iss, s, preds, n_pred=5, brief=False):
    o = s["origin"]
    L = [f"## {rank}. {iss['label']}", ""]
    var = [v for v in iss["variants"] if v != iss["label"]][:4]
    L.append(f"- 이슈 유형: {'/'.join(iss['source'])} | 관측 의회 {s['n_assemblies']}곳 | 관련 회의록 {s['n_docs']}건 | "
             f"언급 {s['n_mentions']}건" + (f" | 유사 표현: {', '.join(var)}" if var else ""))
    L.append("")

    L.append("### ① 핵심 이슈")
    order = " → ".join(t["assembly"] for t in s["timeline"])
    L.append(f"'{iss['label']}'은(는) 제공 데이터 범위 안에서 {s['n_assemblies']}개 광역의회에서 논의가 관측되었다. "
             f"관측 순서는 {order}" + ("이다. 다수 의회가 짧은 기간에 동시에 논의를 시작한 동시다발형 이슈이다." if brief else
                                      f"이며, 이 중 타 의회를 명시적으로 참조한 의회는 {s['n_explicit']}곳이다."))
    L.append("")

    L.append("### ② 최초 관측 (제공 데이터 범위 내)")
    L.append(f"- 근거: {_cite(o['assembly'], o['first_date'], o['minutes_name'], o['speaker'])}")
    L.append(f"  > {_q(o['snippet'])}")
    L.append("")

    L.append("### ③ 타 지방의회 후속 논의 흐름")
    L.append("| 순서 | 의회 | 최초 관측일 | 최초 관측 대비 | 증거 등급 |")
    L.append("|---|---|---|---|---|")
    for t in s["timeline"]:
        rel = _grade(t) if not brief or t["relation"] == "origin" else "동시 대응(경로 추정 안 함)"
        L.append(f"| {t['order']} | {t['assembly_name']} | {_d(t['first_date'])} | +{t['lag_days']}일 | {rel} |")
    L.append("")
    if brief:  # 동시다발형: 의회 간 경로를 해석하지 않으므로 의회별 근거 원문만 간단히 제시
        for t in s["timeline"][1:6]:
            L.append(f"- {t['assembly_name']} 첫 논의: {_cite(t['assembly'], t['first_date'], t['minutes_name'], t['speaker'])}")
            L.append(f"  > {_q(t['snippet'], 200)}")
        L.append("- 해석: 다수 의회가 짧은 기간에 동시에 논의를 시작해 의회 간 전파 경로는 추정하지 않는다.")
        L.append("")
    for t in ([] if brief else s["timeline"][1:]):
        L.append(f"**{t['order']}. {t['assembly_name']}** ({_d(t['first_date'])}, +{t['lag_days']}일, {_grade(t)})")
        L.append(f"- 첫 논의 근거: {_cite(t['assembly'], t['first_date'], t['minutes_name'], t['speaker'])}")
        L.append(f"  > {_q(t['snippet'])}")
        if t["relation"] == "explicit":
            for ref in t["explicit_refs"][:2]:
                g = ref.get("grade", "medium")
                note = {"strong": " (도입 시점의 공식 입법 논리에서 선례로 제시)",
                        "medium": "",
                        "predata": " ※ 언급된 의회의 논의는 데이터 기간 안에서는 더 늦게 관측되지만, 발언이 이미 시행 중임을 진술하므로 데이터 기간 이전 선행으로 본다."}.get(g, "")
                L.append(f"- {GRADE_KO.get(g, '명시적 참조')}: {ASSEMBLY_NAME.get(ref['source'], ref['source'])} 언급 — "
                         f"{_cite(t['assembly'], ref['date'], ref['minutes_name'], ref['speaker'])}{note}")
                L.append(f"  > {_q(ref['snippet'], 320)}")
        elif t["relation"] == "nonspecific":
            ns = t["nonspec_ref"]
            L.append(f"- 비특정 참조('타 시·도' 등): {_cite(t['assembly'], ns['date'], ns['minutes_name'], ns['speaker'])}")
            L.append(f"  > {_q(ns['snippet'], 320)}")
            L.append("- 해석: 타 지역 사례를 의식한 논의로 보이나 출처 의회가 특정되지 않아 경로는 확정하지 않는다.")
        else:
            for ref in t.get("post_refs", [])[:1]:
                L.append(f"- 사후 참조(도입 {REF_WINDOW}일 이후, 경로 근거 아님): {ASSEMBLY_NAME.get(ref['source'], ref['source'])} 언급 — "
                         f"{_cite(t['assembly'], ref['date'], ref['minutes_name'], ref['speaker'])}")
            prior = ", ".join(t["earlier"])
            L.append(f"- 해석: 선행 관측 의회({prior})보다 늦게 등장했으나 도입 시점 회의록에 참조 표현이 없어 "
                     f"시간적 선후(고리 검증)만 확인되며, 의회 간 인과관계는 단정하지 않는다.")
        L.append("")

    L.append("### ④ 향후 확산 가능성")
    p = preds[preds.issue_id == iss["issue_id"]].sort_values("p", ascending=False).head(n_pred) if len(preds) else preds
    if p is None or not len(p):
        L.append("- 미관측 의회가 없거나 예측 대상이 없다.")
    else:
        for r in p.itertuples(index=False):
            why = "; ".join(r.reasons) if r.reasons else "뚜렷한 근거 신호 없음"
            L.append(f"- **{ASSEMBLY_NAME.get(r.assembly, r.assembly)}**: 확산 가능성 {r.tier} (모델 점수 {r.p:.2f}) — {why}")
        L.append("- 등급은 분석 기준일 전체 예측 중 상대 순위(상위 10% 높음, 다음 20% 보통)이다. 점수는 분석 기준일까지의 "
                 "회의록 패턴에 기반한 추정치이며, 특정 의회의 정책 결정을 예단하지 않는다.")
    L.append("")

    if s["upstream_flag"] and s["upstream_example"]:
        u = s["upstream_example"]
        L.append("### 해석 유의사항")
        L.append(f"- 다수 의회에서 단기간(90일 이내)에 동시 관측되었고 언급의 {s['upstream_share']:.0%}가 법령 개정·중앙정부 "
                 f"관련 표현을 포함한다. 의회 간 전파보다 상위법령·정부 정책이라는 공통 계기에 따른 동시 대응일 가능성이 있다.")
        L.append(f"  - 근거: {_cite(u['assembly'], u['date'], u['minutes_name'])}")
        L.append(f"    > {_q(u['snippet'])}")
        L.append("")
    return "\n".join(L)


def assembly_keywords(mentions, issues, top=5):
    lab = dict(zip(issues.issue_id, issues.label))
    cnt = mentions.groupby(["assembly", "issue_id"]).doc_id.nunique().reset_index(name="n")
    tot = cnt.groupby("issue_id").n.sum()
    n_asm = cnt.assembly.nunique()
    # 해당 의회 비중이 전국 평균보다 높은 이슈 = 그 의회의 특징적 이슈
    cnt["lift"] = cnt.apply(lambda r: r.n / (tot[r.issue_id] / n_asm), axis=1)
    cnt["score"] = cnt.n * cnt.lift.clip(upper=5)
    out = {}
    for a, g in cnt.groupby("assembly"):
        out[a] = [(lab[i], int(n)) for i, n in g.nlargest(top, "score")[["issue_id", "n"]].values]
    return out


def is_novel(s, d0, novelty_days=90):
    return (pd.Timestamp(s["origin"]["first_date"]) - d0).days > novelty_days


def _grade(t):
    return GRADE_KO.get(t.get("evidence") or t["relation"], REL_KO.get(t["relation"], t["relation"]))


def _summary(novel, order, simul, spread, iss_map, metrics, hres, mentions):
    """보고서 맨 앞 '핵심 요약': 분석 결과에서 자동으로 문장을 만든다(실행할 때마다 갱신)."""
    L = ["## 핵심 요약", ""]
    nA = sum(not spread[i]["simultaneous"] for i in novel)
    L.append(f"1. **새로 떠오른 정책 의제 {len(novel)}개**: 데이터 기간 중 처음 등장해 3개 이상 광역의회로 이어진 의제다. "
             f"{nA}개는 시차를 두고 번진 점진 확산형, {len(novel) - nA}개는 정부 정책·사회적 사건에 여러 의회가 동시에 반응한 동시다발형이다.")
    if order:
        best = max(order[:top_k(order)], key=lambda i: (("조례" in iss_map[i]["source"]), spread[i]["n_assemblies"]))
        s0, tl = spread[best], spread[best]["timeline"]
        months = max(1, round(tl[-1]["lag_days"] / 30))
        L.append(f"2. **대표 확산 사례**: 「{iss_map[best]['label']}」은 {_d(tl[0]['first_date'])} {tl[0]['assembly_name']}에서 처음 관측된 뒤 "
                 f"약 {months}개월 동안 {s0['n_assemblies']}개 광역의회로 이어졌다({' → '.join(t['assembly'] for t in tl)}).")
    fol = [t for i in novel if not spread[i]["simultaneous"] for t in spread[i]["timeline"][1:]]
    gc = {}
    for t in fol:
        gc[t.get("evidence", t["relation"])] = gc.get(t.get("evidence", t["relation"]), 0) + 1
    k = gc.get("strong", 0) + gc.get("medium", 0) + gc.get("predata", 0)
    line = (f"3. **확산 경로는 확인된 만큼만 주장했다**: 점진 확산형의 후속 의회 {len(fol):,}곳 가운데 도입 시점에 먼저 시작한 지역을 같은 정책의 선례로 언급한 곳은 "
            f"{k}곳(결정적 증거 {gc.get('strong', 0)}, 명시적 참조 {gc.get('medium', 0)})이다. 나머지는 시간 선후만 확인돼 인과를 단정하지 않았다.")
    ex = [(i, t, r) for i in novel if not spread[i]["simultaneous"] for t in spread[i]["timeline"][1:]
          for r in t.get("explicit_refs", [])[:1] if r.get("grade") == "strong"]
    if ex:
        i, t, r = ex[0]
        line += (f" 예를 들어 {t['assembly_name']}는 「{iss_map[i]['label']}」 의제를 다룬 조례안 제안설명에서 "
                 f"{ASSEMBLY_NAME.get(r['source'], r['source'])} 등 먼저 시작한 지역의 사례를 도입 근거로 들었다({_cite(t['assembly'], r['date'], r['minutes_name'])}).")
    L.append(line)
    if simul:
        h4 = (hres or {}).get("H4")
        extra = (f" 이 유형은 첫 석 달 언급에서 법령 개정·중앙부처 표현 비율이 {h4['upstream']['mean_B']:.1%}로 점진형({h4['upstream']['mean_A']:.1%})보다 높아, "
                 f"지방발 확산이 아니라 상위 정부 계기형임을 뒷받침한다." if h4 else "")
        L.append(f"4. **동시다발형은 중앙 대응 과제**: {', '.join(iss_map[i]['label'] for i in simul[:4])} 등은 여러 의회가 짧은 기간에 함께 논의를 시작했다.{extra}")
    h = (hres or {}).get("H1_H2")
    if h:
        tb = {t["feat"]: t for t in h["table"]}
        h3 = (hres or {}).get("H3")
        L.append(f"5. **무엇이 확산을 이끄나 (정책확산 이론 검증)**: 이미 다룬 의회의 비율이 1표준편차 높을수록 다음 6개월 안에 논의를 시작할 오즈가 "
                 f"{tb['frac_obs']['odds_per_sd']}배, 새 의제를 잘 받아들이는 의회일수록 {tb['asm_new']['odds_per_sd']}배 높았다. "
                 f"지리적으로 인접한 의회의 영향은 {tb['nbr_frac']['odds_per_sd']}배로 작았다(Berry & Berry의 전국 상호작용·내부결정요인 모형 지지)."
                 + (f" 새 의제를 먼저 다루는 의회는 해마다 일관됐다(연도 간 순위 상관 {h3['rho']:+.2f})." if h3 else ""))
    if metrics and "roc_auc" in metrics:
        L.append(f"6. **다음 확산 의회 예측**: 과거 시점으로 돌아가 검증한 결과, 확산 가능성 상위 10%로 고른 의회 중 {metrics['precision_at_top10pct']:.1%}가 "
                 f"실제로 6개월 안에 논의를 시작했다. 무작위({metrics['pos_rate']:.1%})의 약 {metrics['precision_at_top10pct'] / max(metrics['pos_rate'], 1e-9):.1f}배다.")
    L.append("")
    L.append("모든 판단에는 회의록명, 회의일자, 발언자, 원문 구간을 붙였다. 이론 가설 검증의 전체 결과는 `hypotheses.md`에 있다.")
    L.append("")
    return L


def top_k(order):
    return min(len(order), 5)


def write_report(path_md, path_json, docs, utts, issues, mentions, spread, preds, metrics, weights, top_n=15,
                 n_persistent=10, n_simul=5, hres=None):
    d0 = docs.date.min()
    ranked = rank_issues(issues, spread, d0=d0)
    # 본문 서술: 데이터 기간 중 새로 등장한 이슈(최초 관측 시점을 의미 있게 특정할 수 있는 이슈)
    novel = [i for i in ranked if is_novel(spread[i], d0)]
    # 본문 A: 점진 확산형(의회 간 전파·확산 분석 대상)  /  본문 B: 동시다발형(공통 외부 사건에 대한 동시 대응)
    order = [i for i in novel if not spread[i]["simultaneous"]][:top_n]
    simul = [i for i in novel if spread[i]["simultaneous"]][:n_simul]
    # 데이터 시작 시점부터 이미 논의되던 상시 이슈는 최초 등장 시점 판단이 불가하므로 부록 표로만 제시
    persistent = [i for i in ranked if not is_novel(spread[i], d0)][:n_persistent]
    iss_map = {int(r["issue_id"]): r for r in issues.to_dict("records")}
    kw = assembly_keywords(mentions, issues)
    L = ["# 광역 지방의회 회의록 기반 지방정책 이슈 트렌드 분석 및 확산 흐름 예측", ""]
    L += _summary(novel, order, simul, spread, iss_map, metrics, hres, mentions)
    L.append("## 0. 분석 개요")
    L.append(f"- 데이터 범위(= 분석 기준일): {_d(docs.date.min())} ~ {_d(docs.date.max())}")
    L.append(f"- 회의록 {len(docs):,}건, 발언 {len(utts):,}개, 광역의회 {docs.assembly.nunique()}곳")
    L.append(f"- 이슈 후보 {len(issues):,}개 중 3개 이상 의회에서 관측되고 계절성·지나가는 말이 아닌 이슈 {len(ranked):,}개를 점수화했다. "
             f"그중 데이터 기간 중 새로 등장한 이슈 {len(novel):,}개에서 점진 확산형 상위 {len(order)}개와 동시다발형 {len(simul)}개를 서술하고, "
             f"처음부터 논의되던 상시 이슈는 부록으로 둔다.")
    L.append("- '최초 관측'은 제공 데이터 범위 내 최초 등장을 뜻하며, 데이터 이전 시점의 논의 여부는 판단하지 않는다.")
    L.append("- 후속 의회마다 인과 추론 조건(시간적 선행·대상 일치·도입 시점 근접성)에 따라 증거 등급을 표기한다: "
             "결정적 증거(도입 시점 제안설명·검토보고에서 타 광역을 선례로 제시) > 명시적 참조 > 데이터 이전 선행 > 비특정 참조 > 시간적 후행. "
             "시간적 후행은 선후관계만 확인된 것으로 인과로 해석하지 않는다.")
    if metrics:
        L.append(f"- 확산 예측 모델: {metrics.get('mode')} (특징 13개: 기관측 의회 수·확산 속도·인접 광역 관측·언급 추세·"
                 f"의제 유사도·대상 의회의 신규 의제 수용 성향 등)")
        if "roc_auc" in metrics:
            L.append(f"- 예측 검증: 시점 이동 백테스트 {metrics['n_folds']}회 평균(학습 라벨 기간이 검증 시점 이전에 끝난 표본만 사용) — "
                     f"ROC-AUC {metrics['roc_auc']}, 상위 10% 정밀도 {metrics['precision_at_top10pct']} "
                     f"(기저 확산률 {metrics['pos_rate']}, 약 {metrics['precision_at_top10pct'] / max(metrics['pos_rate'], 1e-9):.1f}배)")
            o = metrics.get("ordinance_issues")
            if o:
                L.append(f"  - 조례 이슈 한정: ROC-AUC {o['roc_auc']}, 상위 10% 정밀도 {o['precision_at_top10pct']} "
                         f"(기저 {o['pos_rate']}, 약 {o['precision_at_top10pct'] / max(o['pos_rate'], 1e-9):.1f}배)")
    L.append("")
    L.append("## 의회별 주요 이슈 키워드 (관련 회의록 수)")
    for a in sorted(kw):
        L.append(f"- **{ASSEMBLY_NAME.get(a, a)}**: " + ", ".join(f"{k}({n})" for k, n in kw[a]))
    L.append("")
    L.append("# A. 점진 확산형 이슈")
    L.append("최초 관측 이후 시차를 두고 다른 의회로 논의가 이어진 이슈. 의회 간 전파·확산 흐름 분석의 핵심 대상이다.")
    L.append("")
    for i, iid in enumerate(order, 1):
        L.append(issue_section(i, iss_map[iid], spread[iid], preds))
    L.append("# B. 동시다발형 이슈")
    L.append("관측 의회의 절반 이상이 최초 관측 후 60일 안에 논의를 시작한 이슈. 의회 간 전파라기보다 정부 정책 발표나 "
             "사회적 사건 같은 공통 외부 계기에 각 의회가 동시에 반응한 것으로 해석하는 것이 타당하므로, "
             "의회 간 경로를 추정하지 않는다.")
    L.append("")
    for i, iid in enumerate(simul, 1):
        L.append(issue_section(f"B{i}", iss_map[iid], spread[iid], preds, brief=True))
    L.append("## 부록. 데이터 시작 시점부터 논의되던 상시 이슈")
    L.append("데이터 첫 90일 안에 이미 관측된 이슈는 '최초 등장'과 '전파 경로'를 데이터 범위 안에서 특정할 수 없으므로 "
             "본문 분석에서 제외하고 규모만 제시한다.")
    L.append("")
    L.append("| 이슈 | 관측 의회 수 | 관련 회의록 | 최초 관측 |")
    L.append("|---|---|---|---|")
    for iid in persistent:
        s_ = spread[iid]
        L.append(f"| {iss_map[iid]['label']} | {s_['n_assemblies']} | {s_['n_docs']} | "
                 f"{ASSEMBLY_NAME.get(s_['origin']['assembly'])} {_d(s_['origin']['first_date'])} |")
    L.append("")
    with open(path_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    def conv(o):
        if isinstance(o, (pd.Timestamp,)):
            return o.strftime("%Y-%m-%d")
        if hasattr(o, "item"):
            return o.item()
        return str(o)

    out = []
    for iid in order + simul:
        p = preds[preds.issue_id == iid].sort_values("p", ascending=False) if len(preds) else preds
        out.append(dict(issue=iss_map[iid], analysis=spread[iid],
                        forecast=[dict(assembly=r.assembly, p=round(float(r.p), 4), tier=r.tier, reasons=r.reasons)
                                  for r in p.itertuples(index=False)]))
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(dict(metrics=metrics, weights=weights, assembly_keywords=kw, issues=out), f,
                  ensure_ascii=False, indent=1, default=conv)
    return order
