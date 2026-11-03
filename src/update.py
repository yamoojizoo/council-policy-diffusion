"""갱신 보고서: 새 회의록이 들어온 뒤 무엇이 바뀌었는지, 지난번 예측이 맞았는지 정리한다.

운영 시나리오
  1) 지난 분석 결과 폴더(output_prev)를 보관해 둔다.
  2) 새 회의록 파일을 data/ 에 추가하고 전체 파이프라인을 다시 돌린다.
       python run_pipeline.py --data_dir data --out_dir output --prev_out output_prev
  3) output/update.md(사람용)와 update.json(대시보드용)이 생긴다.

지난번 예측 점검은 '지난번 이슈 사전'을 그대로 새 기간 발언에 다시 적용해 판정한다.
이슈 병합 결과는 기간이 바뀌면 조금씩 달라질 수 있으므로, 이번 실행의 이슈 번호에 기대지 않기 위해서다.
"""
import json
import os

import numpy as np
import pandas as pd

from .issues import index_mentions

STAGES = ["도입 초기", "확산기", "확산 후반", "포화"]
N_ASM = 17


def stage_of(n, total=N_ASM):
    s = n / total
    return 0 if s <= 0.16 else 1 if s <= 0.5 else 2 if s <= 0.84 else 3


def _load(path):
    for ext in (".parquet", ".pkl"):
        if os.path.exists(path + ext):
            return pd.read_parquet(path + ext) if ext == ".parquet" else pd.read_pickle(path + ext)
    return None


def _auc(y, s):
    y, s = np.asarray(y), np.asarray(s)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return None
    r = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def load_prev(prev_dir):
    """지난 실행 결과 폴더에서 비교에 필요한 것만 읽는다."""
    w = os.path.join(prev_dir, "work")
    docs = _load(os.path.join(w, "docs"))
    spread = pd.read_pickle(os.path.join(w, "spread.pkl"))
    issues = pd.read_json(os.path.join(prev_dir, "issue_dictionary.json"))
    fc = os.path.join(prev_dir, "forecast_all.csv")
    preds = pd.read_csv(fc) if os.path.exists(fc) else pd.DataFrame()
    cut = os.path.join(w, "until.txt")
    return dict(docs=docs, spread=spread, issues=issues, preds=preds, simulated=os.path.exists(cut))


def compare(prev, docs, utts, issues, spread, ranked, novel):
    """prev: load_prev() 결과. 나머지는 이번 실행의 결과."""
    p_d1 = pd.Timestamp(prev["docs"].date.max())
    d1 = pd.Timestamp(docs.date.max())
    new_docs = docs[docs.date > p_d1]
    out = dict(simulated=bool(prev.get("simulated")), n_joined_issues=0, prev_d1=f"{p_d1:%Y-%m-%d}", d1=f"{d1:%Y-%m-%d}", days=int((d1 - p_d1).days),
               new_docs=int(len(new_docs)), new_docs_by_asm=new_docs.assembly.value_counts().to_dict())

    # ---- 1. 지난번 예측 점검: 지난 이슈 사전을 새 기간 발언에 그대로 적용 ----
    P = prev["preds"]
    check = dict(n=0)
    if len(P) and len(new_docs):
        pi = prev["issues"]
        pi = pi[pi.issue_id.isin(P.issue_id.unique())]
        nu = utts[utts.doc_id.isin(set(new_docs.doc_id))]
        try:
            m = index_mentions(nu, pi)
        except KeyError:          # 새 기간에 한 건도 안 걸리면 빈 표가 돌아온다
            m = pd.DataFrame()
        seen = set(zip(m.issue_id.astype(int), m.assembly)) if len(m) else set()
        P = P.assign(hit=[int((int(i), a) in seen) for i, a in zip(P.issue_id, P.assembly)])
        base = float(P.hit.mean())
        tiers = {}
        for t in ("높음", "보통", "낮음"):
            g = P[P.tier == t]
            if len(g):
                tiers[t] = dict(n=int(len(g)), hit=int(g.hit.sum()), rate=round(float(g.hit.mean()), 4),
                                lift=round(float(g.hit.mean()) / base, 2) if base else None)
        top = P.sort_values("p", ascending=False).head(max(1, len(P) // 10))
        lab = dict(zip(pi.issue_id.astype(int), pi.label))
        ordc = None
        if "is_ord" in P.columns:   # 조례안으로 다뤄진 의제만 따로 (본 보고서의 예측 검증과 같은 기준)
            O = P[P.is_ord == 1]
            if len(O):
                ot = O.sort_values("p", ascending=False).head(max(1, len(O) // 10))
                ordc = dict(n=int(len(O)), n_hit=int(O.hit.sum()), base=round(float(O.hit.mean()), 4),
                            auc=None if _auc(O.hit, O.p) is None else round(_auc(O.hit, O.p), 4),
                            p_at_10=round(float(ot.hit.mean()), 4))
        hits = (P[(P.hit == 1) & (P.tier != "낮음") & ((P.is_ord == 1) if "is_ord" in P.columns else True)]
                .sort_values("p", ascending=False)
                .assign(label=lambda d: d.issue_id.map(lab)))
        check = dict(n=int(len(P)), n_hit=int(P.hit.sum()), base=round(base, 4), auc=_auc(P.hit, P.p),
                     p_at_10=round(float(top.hit.mean()), 4), tiers=tiers, ordinance=ordc,
                     examples=[dict(label=r.label, a=r.assembly, p=round(float(r.p), 3))
                               for r in hits.head(12).itertuples(index=False)])
        if check["auc"] is not None:
            check["auc"] = round(check["auc"], 4)
    out["check"] = check

    # ---- 2. 이번 실행 기준의 변화 ----
    lab = dict(zip(issues.issue_id.astype(int), issues.label))
    # 이슈 번호는 실행마다 달라질 수 있어, 표면형(띄어쓰기 없앤 표현)이 가장 많이 겹치는 지난번 이슈와 짝짓는다
    from collections import Counter
    surf_prev = {}
    for i, sf in zip(prev["issues"].issue_id.astype(int), prev["issues"].surfaces):
        for x in sf:
            surf_prev.setdefault(x, i)
    to_prev = {}
    for i, sf in zip(issues.issue_id.astype(int), issues.surfaces):
        c = Counter(surf_prev[x] for x in sf if x in surf_prev)
        if c:
            to_prev[i] = c.most_common(1)[0][0]
    prev_tier = {}
    if len(prev["preds"]):
        for r in prev["preds"].itertuples(index=False):
            prev_tier[(int(r.issue_id), r.assembly)] = r.tier
    ps = prev["spread"]

    joined, stage_up, emerged, refs = [], [], [], []
    for iid in ranked:
        if novel is not None and iid not in novel:
            continue   # 대시보드·보고서가 추적하는 '기간 중 새로 등장한 이슈'만
        s, L = spread[iid], lab[iid]
        tl = s["timeline"]
        new_t = [t for t in tl if pd.Timestamp(t["first_date"]) > p_d1]
        if not new_t:
            continue
        before = len(tl) - len(new_t)
        if before == 0:
            emerged.append(dict(id=iid, label=L, origin=tl[0]["assembly"], date=f"{pd.Timestamp(tl[0]['first_date']):%Y-%m-%d}",
                                n=len(tl), novel=iid in novel))
            continue
        joined.append(dict(id=iid, label=L, before=before, after=len(tl),
                           new=[dict(a=t["assembly"], date=f"{pd.Timestamp(t['first_date']):%Y-%m-%d}",
                                     tier=prev_tier.get((to_prev.get(iid), t["assembly"])), ev=t.get("evidence", "temporal"))
                                for t in new_t]))
        if stage_of(len(tl)) > stage_of(before):
            stage_up.append(dict(id=iid, label=L, frm=STAGES[stage_of(before)], to=STAGES[stage_of(len(tl))],
                                 before=before, after=len(tl)))
        for t in new_t:
            if t.get("evidence") in ("strong", "medium"):
                r0 = (t.get("explicit_refs") or [{}])[0]
                refs.append(dict(id=iid, label=L, a=t["assembly"], src=r0.get("source"), grade=t["evidence"],
                                 date=f"{pd.Timestamp(t['first_date']):%Y-%m-%d}", q=(r0.get("snippet") or "")[:200]))
    joined.sort(key=lambda x: -len(x["new"]))
    # 지난번엔 3곳 미만이라 분석 대상이 아니었다가 이번에 기준을 넘은 이슈
    crossed = [x for x in joined if x["before"] < 3 <= x["after"]]
    out.update(n_joined_issues=len(joined), joined=joined, stage_up=stage_up, emerged=emerged, crossed=crossed, refs=refs,
               n_join=int(sum(len(x["new"]) for x in joined)),
               n_join_predicted=int(sum(1 for x in joined for t in x["new"] if t["tier"] in ("높음", "보통"))),
               matched=int(sum(1 for x in joined if x["id"] in to_prev)))
    return out


def write(u, md_path, json_path):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(u, f, ensure_ascii=False, indent=1, default=str)
    L = ["# 갱신 보고서", ""]
    if u.get("simulated"):
        L += ["> 시연: 같은 제공 데이터를 지난 분석 기준일에서 잘라 분석한 결과를 '지난 분석'으로 두고, 전체 데이터 분석과 비교했다. "
              "지난 분석의 예측 모델은 그 이후 회의록을 전혀 보지 않았다.", ""]
    L += [
          f"지난 분석 기준일 **{u['prev_d1']}** → 이번 분석 기준일 **{u['d1']}** ({u['days']}일, 새 회의록 {u['new_docs']:,}건)", ""]
    if u["new_docs_by_asm"]:
        L.append("새 회의록이 들어온 의회: " + ", ".join(f"{a} {n}건" for a, n in
                                                  sorted(u["new_docs_by_asm"].items(), key=lambda x: -x[1])))
        L.append("")
    c = u["check"]
    L += ["## 1. 지난번 예측은 맞았나", ""]
    if c.get("n"):
        L.append(f"지난번에 '아직 다루지 않은 의회'로 남아 있던 {c['n']:,}개 (이슈, 의회) 조합 중 {c['n_hit']:,}개({c['base']:.1%})가 "
                 f"새 기간에 해당 이슈를 처음 다뤘다. 지난번 이슈 사전을 새 기간 발언에 그대로 적용해 판정했다.")
        L.append("")
        L += ["| 지난번 예측 등급 | 조합 수 | 새 기간에 실제로 다룸 | 비율 | 평균 대비 |", "|---|---|---|---|---|"]
        for t, g in c["tiers"].items():
            L.append(f"| {t} | {g['n']:,} | {g['hit']:,} | {g['rate']:.1%} | {g['lift'] or '-'}배 |")
        L.append("")
        if c.get("auc") is not None:
            L.append(f"- 순위 정확도(ROC-AUC) {c['auc']:.3f}, 점수 상위 10%의 적중률 {c['p_at_10']:.1%} (평균 {c['base']:.1%})")
        if c.get("ordinance"):
            o = c["ordinance"]
            L.append(f"- 조례안으로 다뤄진 의제만 보면 {o['n']:,}개 조합 중 {o['n_hit']:,}개({o['base']:.1%}), "
                     + (f"ROC-AUC {o['auc']:.3f}, " if o['auc'] is not None else "") + f"점수 상위 10% 적중률 {o['p_at_10']:.1%}")
        L.append(f"- 예측 기간은 {180}일인데 새 기간은 {u['days']}일이라, 적중률 자체는 낮게 나오는 것이 정상이다. 등급 간 차이(순위가 맞는지)를 본다.")
        if c["examples"]:
            L.append("- '높음'·'보통'으로 예측했고 실제로 다룬 조례 의제 사례: " + ", ".join(f"{e['label']}({e['a']})" for e in c["examples"][:8]))
    else:
        L.append("지난번 예측 결과(forecast_all.csv)가 없거나 새 회의록이 없어 점검하지 않았다.")
    L += ["", "## 2. 새로 등장한 이슈", ""]
    if u["emerged"]:
        L += ["| 이슈 | 처음 관측 | 지금까지 관측 의회 |", "|---|---|---|"]
        L += [f"| {e['label']} | {e['origin']} {e['date']} | {e['n']}곳 |" for e in u["emerged"][:20]]
    else:
        L.append("새 기간에 처음 등장해 3개 이상 의회로 이어진 이슈는 없다.")
    if u["crossed"]:
        L += ["", "지난번에는 3곳 미만이었다가 이번에 분석 기준(3곳 이상)을 넘은 이슈: "
              + ", ".join(f"{x['label']}({x['before']}→{x['after']}곳)" for x in u["crossed"][:15])]
    L += ["", "## 3. 확산이 이어진 이슈", "",
          f"기간 중 새로 등장한 이슈(대시보드 추적 대상) 가운데 {len(u['joined'])}개가 새 기간에 의회 {u['n_join']}곳으로 더 퍼졌다. 그중 {u['n_join_predicted']}곳은 지난번 예측에서 '높음' 또는 '보통'이었다.", "",
          "| 이슈 | 관측 의회 | 새로 다룬 의회 (지난번 예측 등급. -는 지난번 이슈 사전에서 짝을 찾지 못해 비교하지 않음) |", "|---|---|---|"]
    for x in u["joined"][:25]:
        L.append(f"| {x['label']} | {x['before']}→{x['after']}곳 | " +
                 ", ".join(f"{t['a']}({t['tier'] or '-'})" for t in x["new"]) + " |")
    if u["stage_up"]:
        L += ["", "## 4. 확산 단계가 바뀐 이슈", "", "| 이슈 | 이전 | 이번 |", "|---|---|---|"]
        L += [f"| {s['label']} | {s['frm']} ({s['before']}곳) | {s['to']} ({s['after']}곳) |" for s in u["stage_up"][:20]]
    if u["refs"]:
        L += ["", "## 5. 새로 확인된 명시적 참조", ""]
        for r in u["refs"][:10]:
            L.append(f"- **{r['label']}**: {r['a']}가 {r['src']} 사례를 언급({r['date']}) — \"{r['q']}\"")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
