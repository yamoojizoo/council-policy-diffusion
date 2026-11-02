"""정책확산 이론에서 도출한 가설을 회의록 데이터로 검증한다.

각 가설은 '이론 -> 가설 -> 조작화 -> 검정'의 순서로 계산하며, 결과는 output/hypotheses.md / .json 으로 저장한다.
  H1 지역확산(이웃 효과, Berry & Berry 1990)       : 인접 광역이 먼저 다뤘으면 채택 가능성이 높아진다
  H2 유사 지역 학습(Volden 2006)                    : 지리적 이웃보다 의제가 비슷한 의회를 따라간다
  H3 혁신성의 일관성(Walker 1969)                   : 새 의제를 먼저 다루는 의회는 해마다 일관된다
  H4 초점사건·상위정부 계기(Kingdon 1984; Birkland 1997): 동시다발형 이슈는 사건·중앙정책 언급으로 시작된다
  H5 이슈관심주기(Downs 1972)                       : 관심은 정점 뒤 줄어들며, 사건형 이슈일수록 빨리 식는다
  H6 Bass 확산모형(Bass 1969; Rogers 2003)          : 점진형은 모방(q), 동시다발형은 외부 영향(p)이 주도한다
H1·H2는 예측 모델과 같은 학습 표본(이슈 x 미관측 의회 x 기준 시점)에서, 이론 구성개념마다 변수 하나만 넣은
'이론 검증 모델'로 추정한다(변수 간 다중공선성으로 계수가 왜곡되는 것을 막기 위해). 신뢰구간은 이슈 단위 군집 부트스트랩.
"""
import json
import re

import numpy as np
import pandas as pd
from scipy import stats

THEORY_FEATS = {
    "frac_obs": "전국 상호작용: 기관측 의회 비율",
    "nbr_frac": "지역확산: 인접 광역 관측 비율",
    "sim_max": "유사 지역 학습: 최대 의제 유사도",
    "asm_new": "내부결정요인: 대상 의회 혁신 성향(최근 신규 의제 수용)",
    "age_years": "통제: 최초 관측 후 경과 기간",
    "log_recent": "통제: 최근 언급량",
    "asm_vol": "통제: 대상 의회 회의 수",
    "is_ord": "통제: 조례 이슈 여부",
}
EVENT = re.compile(r"참사|사고|화재|폭우|폭설|산불|재난|지진|태풍|사태|계엄|탄핵|희생|피해")
UPSTREAM = re.compile(r"법\s?개정|법률\s?개정|개정\s?법률|시행령|상위법|중앙정부|정부\s?지침|정부\s?발표|정부가|국정과제|"
                      r"행정안전부|보건복지부|교육부|국토교통부|기획재정부|국회에서|법이\s?시행|법\s?시행")


def _vif(X):
    from sklearn.linear_model import LinearRegression
    out = {}
    for j, c in enumerate(X.columns):
        others = X.drop(columns=c)
        r2 = LinearRegression().fit(others, X[c]).score(others, X[c])
        out[c] = round(1 / max(1 - r2, 1e-9), 2)
    return out


def _fit(X, y):
    from sklearn.linear_model import LogisticRegression
    Z = (X - X.mean()) / X.std(ddof=0).replace(0, 1)
    m = LogisticRegression(max_iter=2000, C=1e4).fit(Z.values, y)
    return m.coef_[0]


def h1_h2(train, n_boot=200, seed=2026):
    feats = list(THEORY_FEATS)
    X, y = train[feats].astype(float), train.y.values
    coef = _fit(X, y)
    rng = np.random.default_rng(seed)
    ids = train.issue_id.unique()
    pos = train.groupby("issue_id").indices
    boots = []
    for _ in range(n_boot):
        pick = rng.choice(ids, len(ids), replace=True)
        idx = np.concatenate([pos[i] for i in pick])
        boots.append(_fit(X.iloc[idx], y[idx]))
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
    table = [dict(feat=f, name=THEORY_FEATS[f], coef=round(float(c), 3), ci=[round(float(a), 3), round(float(b), 3)],
                  odds_per_sd=round(float(np.exp(c)), 2)) for f, c, a, b in zip(feats, coef, lo, hi)]
    k = {f: i for i, f in enumerate(feats)}
    diff = boots[:, k["sim_max"]] - boots[:, k["nbr_frac"]]
    # 같은 '전국 관측 비율' 구간 안에서 인접 광역 관측 유무에 따른 실제 채택률 (모형 가정 없는 기술 통계)
    t = train.assign(nb=np.where(train.nbr_frac > 0, "인접 관측 있음", "인접 관측 없음"),
                     band=pd.cut(train._n_obs, [0, 2, 5, 9, 17], labels=["1~2곳", "3~5곳", "6~9곳", "10곳 이상"]))
    strat = t.groupby(["band", "nb"], observed=True).y.mean().unstack()
    strat_rows = [dict(band=str(b), no=round(float(r.get("인접 관측 없음", np.nan)), 3),
                       yes=round(float(r.get("인접 관측 있음", np.nan)), 3)) for b, r in strat.iterrows()]
    sim_band = t.assign(sb=pd.qcut(t.sim_max.rank(method="first"), 4, labels=["하위 25%", "25~50%", "50~75%", "상위 25%"]))
    sim_rows = [dict(band=str(b), rate=round(float(v), 3)) for b, v in sim_band.groupby("sb", observed=True).y.mean().items()]
    full_corr = train[["sim", "sim_max", "log_n_obs", "frac_obs"]].corr()
    return dict(
        n=int(len(train)), n_issues=int(len(ids)), table=table, vif=_vif(X),
        corr_original=dict(sim_vs_sim_max=round(float(full_corr.loc["sim", "sim_max"]), 3),
                           log_n_obs_vs_frac_obs=round(float(full_corr.loc["log_n_obs", "frac_obs"]), 3)),
        sim_minus_nbr=dict(mean=round(float(diff.mean()), 3), ci=[round(float(np.percentile(diff, 2.5)), 3),
                                                                   round(float(np.percentile(diff, 97.5)), 3)]),
        nbr_strat=strat_rows, sim_strat=sim_rows)


def _earliness(spread, ids, assemblies):
    """이슈마다 의회의 관측 순서를 0~1 점수로 바꾼다(가장 먼저 1, 관측 안 됨 0)."""
    n = len(assemblies)
    rows = []
    for i in ids:
        tl = spread[i]["timeline"]
        seen = {t["assembly"]: t["order"] for t in tl}
        yr = pd.Timestamp(tl[0]["first_date"]).year
        for a in assemblies:
            rows.append(dict(issue_id=i, year=yr, assembly=a, score=1 - (seen[a] - 1) / (n - 1) if a in seen else 0.0))
    return pd.DataFrame(rows)


def h3(spread, novel, docs, n_perm=5000, seed=2026):
    assemblies = sorted(docs.assembly.dropna().unique())
    e = _earliness(spread, novel, assemblies)
    by = e.groupby(["year", "assembly"]).score.mean().unstack(0)
    years = sorted(by.columns)
    if len(years) < 2:
        return None
    a, b = by[years[0]], by[years[-1]]
    rho, p = stats.spearmanr(a, b)
    # 회의록 분량이 많은 의회가 기계적으로 먼저 잡히는지(측정 도구 요인) 확인
    vol = docs.groupby("assembly").size().reindex(by.index)
    rho_vol, p_vol = stats.spearmanr(by.mean(1), vol)
    # 분량을 통제한 순위 상관: 연도별 점수에서 분량 순위의 영향을 회귀로 제거한 잔차끼리 상관
    rv = stats.rankdata(vol)
    res = lambda s: stats.rankdata(s) - np.polyval(np.polyfit(rv, stats.rankdata(s), 1), rv)  # noqa: E731
    rho_p, p_p = stats.pearsonr(res(a), res(b))
    n_iss = e.groupby("year").issue_id.nunique().to_dict()
    top = (a.rank(ascending=False) + b.rank(ascending=False)).sort_values().index[:5].tolist()
    return dict(years=[int(years[0]), int(years[-1])], n_issues={int(k): int(v) for k, v in n_iss.items()},
                rho=round(float(rho), 3), p=round(float(p), 4), rho_volume=round(float(rho_vol), 3),
                p_volume=round(float(p_vol), 4), rho_partial=round(float(rho_p), 3), p_partial=round(float(p_p), 4),
                consistent_leaders=top,
                scores={k: [round(float(a[k]), 3), round(float(b[k]), 3)] for k in by.index})


def h4(spread, novel, mentions, window=90):
    rows = []
    m = mentions[mentions.issue_id.isin(novel)]
    for i, g in m.groupby("issue_id"):
        early = g[g.date <= g.date.min() + pd.Timedelta(days=window)]
        ctx = early.context.astype(str)
        rows.append(dict(issue_id=i, B=bool(spread[i]["simultaneous"]),
                         event=float(ctx.str.contains(EVENT).mean()), upstream=float(ctx.str.contains(UPSTREAM).mean())))
    d = pd.DataFrame(rows)
    out = {"n_A": int((~d.B).sum()), "n_B": int(d.B.sum())}
    for k in ("event", "upstream"):
        a, b = d.loc[~d.B, k], d.loc[d.B, k]
        u, p = stats.mannwhitneyu(b, a, alternative="greater")
        out[k] = dict(median_A=round(float(a.median()), 3), median_B=round(float(b.median()), 3),
                      mean_A=round(float(a.mean()), 3), mean_B=round(float(b.mean()), 3), p=round(float(p), 4))
    d["either"] = (d.event + d.upstream) / 2
    a, b = d.loc[~d.B, "either"], d.loc[d.B, "either"]
    out["combined_p"] = round(float(stats.mannwhitneyu(b, a, alternative="greater")[1]), 4)
    return out


def _post_ratio(v, follow):
    """정점(최댓값) 다음 3~follow개월 평균을 정점으로 나눈 값. 정점 뒤 관찰 기간이 부족하면 None."""
    k = int(np.argmax(v))
    if len(v) - 1 - k < follow or v[k] <= 0:
        return None
    return float(v[k + 3:k + follow + 1].mean() / v[k])


def h5(spread, novel, docs, follow=6, n_perm=200, seed=2026):
    """월별 언급량(그 달 전체 회의록 1천 건당, 3개월 이동평균)의 정점 이후 감소를 본다.
    정점은 정의상 최댓값이라 그 뒤 값이 낮아지는 것은 어느 정도 기계적이다. 그래서 같은 이슈의 월별 값을
    무작위로 섞은 경우(시간 순서가 없는 경우)와 비교해, 관심이 실제로 '몰렸다가 식는' 시간 구조가 있는지 검정한다."""
    rng = np.random.default_rng(seed)
    vol = docs.set_index("date").resample("MS").size()
    rows = []
    for i in novel:
        s = pd.Series(spread[i]["monthly"], dtype=float)
        s.index = pd.to_datetime(s.index)
        s = (s.reindex(vol.index, fill_value=0) / vol * 1000).fillna(0)
        s = s[s.index >= s[s > 0].index.min()]
        v = s.rolling(3, min_periods=1).mean().values
        r = _post_ratio(v, follow)
        if r is None:
            continue
        perm = []
        raw = s.values
        for _ in range(n_perm):
            pv = pd.Series(rng.permutation(raw)).rolling(3, min_periods=1).mean().values
            pr = _post_ratio(pv, follow)
            if pr is not None:
                perm.append(pr)
        k = int(np.argmax(v))
        after = v[k + 1:]
        below = np.where(after <= v[k] / 2)[0]
        rows.append(dict(issue_id=i, B=bool(spread[i]["simultaneous"]), ratio=r,
                         perm=float(np.mean(perm)) if perm else np.nan, half=int(below[0] + 1) if len(below) else None))
    d = pd.DataFrame(rows).dropna(subset=["ratio", "perm"])
    a, b = d.loc[~d.B, "ratio"], d.loc[d.B, "ratio"]
    p = float(stats.mannwhitneyu(b, a, alternative="less")[1]) if len(a) and len(b) else np.nan
    w = stats.wilcoxon(d.ratio - d.perm, alternative="less") if len(d) > 5 else None
    return dict(n=int(len(d)), n_A=int(len(a)), n_B=int(len(b)),
                median_ratio=round(float(d.ratio.median()), 3), median_perm=round(float(d.perm.median()), 3),
                share_below_perm=round(float((d.ratio < d.perm).mean()), 3),
                p_vs_perm=round(float(w.pvalue), 6) if w else None,
                median_ratio_A=round(float(a.median()), 3), median_ratio_B=round(float(b.median()), 3), p_B_faster=round(p, 4),
                median_half_A=float(d.loc[~d.B, "half"].dropna().median()) if len(a) else None,
                median_half_B=float(d.loc[d.B, "half"].dropna().median()) if len(b) else None)


def _bass_segments(spread, i, end, M):
    """이슈 하나의 채택 과정을 '구간마다 (이미 채택한 의회 수 n, 구간 길이 dt개월, 구간 끝 신규 채택 수 c)'로 바꾼다.
    첫 관측 의회를 시작점(t=0)으로 하고, 데이터 마지막 날에 관찰을 끝낸다(우측 절단)."""
    ds = sorted(pd.Timestamp(t["first_date"]) for t in spread[i]["timeline"])
    t0 = ds[0]
    ts = [(d - t0).days / 30.44 for d in ds]
    out, n, prev, k = [], 1, 0.0, 1
    while k < len(ts):
        t, c = ts[k], 0
        while k < len(ts) and ts[k] == t:
            c += 1
            k += 1
        out.append((n, t - prev, c))
        n, prev = n + c, t
    out.append((n, (end - t0).days / 30.44 - prev, 0))
    return out


def _bass_fit(segs, M):
    """Bass 위험률 h(n) = p + q*n/M 을 최대우도로 추정한다(아직 채택하지 않은 의회마다 같은 위험률)."""
    from scipy.optimize import minimize
    a = np.array([x for s in segs for x in s], dtype=float)
    n, dt, c = a[:, 0], a[:, 1], a[:, 2]

    def nll(th):
        p, q = np.exp(th)
        h = p + q * n / M
        return -(np.sum(c * np.log(h)) - np.sum((M - n) * h * dt))
    r = minimize(nll, [np.log(0.02), np.log(0.3)], method="Nelder-Mead",
                 options=dict(xatol=1e-6, fatol=1e-9, maxiter=4000))
    return np.exp(r.x)


def h6(spread, novel, docs, n_boot=300, seed=2026, min_adopt=6):
    """Bass 확산모형. 의회가 17곳뿐이라 이슈 하나로는 p·q를 따로 식별하기 어렵다(경계해가 나옴).
    그래서 유형별로 이슈를 모아 추정하고, 이슈 단위 부트스트랩으로 신뢰구간을 구한다."""
    M = docs.assembly.nunique()
    end = docs.date.max()
    rng = np.random.default_rng(seed)
    groups = {"전체 신규 이슈": list(novel), "점진형": [i for i in novel if not spread[i]["simultaneous"]],
              "동시다발형": [i for i in novel if spread[i]["simultaneous"]]}
    segs = {i: _bass_segments(spread, i, end, M) for i in novel}
    res = {}
    for g, ids in groups.items():
        p, q = _bass_fit([segs[i] for i in ids], M)
        bs = np.array([_bass_fit([segs[i] for i in rng.choice(ids, len(ids))], M) for _ in range(n_boot)])
        ratio = bs[:, 1] / bs[:, 0]
        ci = lambda x: [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]  # noqa: E731
        res[g] = dict(n=len(ids), p=round(float(p), 4), q=round(float(q), 4), p_ci=ci(bs[:, 0]), q_ci=ci(bs[:, 1]),
                      q_over_p=round(float(q / p), 2), q_over_p_ci=[round(float(np.percentile(ratio, 2.5)), 2), round(float(np.percentile(ratio, 97.5)), 2)],
                      hazard_1=round(float(p + q / M), 4), hazard_10=round(float(p + q * 10 / M), 4))
    # 이슈 하나씩 추정했을 때 p나 q가 0으로 붙는(식별 불가) 비율
    single = [_bass_fit([segs[i]], M) for i in novel if len(spread[i]["timeline"]) >= min_adopt]
    boundary = float(np.mean([min(p, q) < 1e-6 for p, q in single])) if single else None
    res["single_issue"] = dict(n=len(single), share_boundary=round(boundary, 3) if boundary is not None else None)
    return res


def run_all(train, spread, novel, docs, mentions):
    """가설마다 따로 계산한다. 표본이 너무 작아 계산할 수 없는 가설은 건너뛴다(예: 합성 시연 데이터)."""
    jobs = {"H1_H2": (lambda: h1_h2(train)) if train is not None and len(train) else None,
            "H3": lambda: h3(spread, novel, docs), "H4": lambda: h4(spread, novel, mentions),
            "H5": lambda: h5(spread, novel, docs), "H6": lambda: h6(spread, novel, docs)}
    res = {}
    for k, f in jobs.items():
        if f is None:
            continue
        try:
            res[k] = f()
        except Exception as e:  # noqa: BLE001
            res[k] = None
            res.setdefault("skipped", {})[k] = f"{type(e).__name__}: {e}"
    return res


def _p(p):
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "검정 불가(표본 부족)"
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def write(res, path_md, path_json):
    json.dump(res, open(path_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = ["# 정책확산 이론 가설 검증", ""]
    try:
        if res.get("H1_H2"):
            r = res["H1_H2"]
            L += [f"## H1·H2 이웃 효과와 유사 지역 학습 (표본 {r['n']:,}건, 이슈 {r['n_issues']:,}개)", "",
                  "| 구성개념 | 표준화 계수 | 95% 신뢰구간 | 1 표준편차당 오즈비 | VIF |", "|---|---|---|---|---|"]
            for t in r["table"]:
                L.append(f"| {t['name']} | {t['coef']:+.3f} | [{t['ci'][0]:+.3f}, {t['ci'][1]:+.3f}] | {t['odds_per_sd']} | {r['vif'][t['feat']]} |")
            L += ["", f"- 유사도 계수 - 이웃 계수 = {r['sim_minus_nbr']['mean']:+.3f} (95% 구간 {r['sim_minus_nbr']['ci']})",
                  "", "| 전국 관측 의회 수 | 인접 관측 없음 채택률 | 인접 관측 있음 채택률 |", "|---|---|---|"]
            L += [f"| {s['band']} | {s['no']:.1%} | {s['yes']:.1%} |" for s in r["nbr_strat"]]
            L += ["", "| 최대 의제 유사도 구간 | 채택률 |", "|---|---|"] + [f"| {s['band']} | {s['rate']:.1%} |" for s in r["sim_strat"]]
    except Exception as e:  # noqa: BLE001
        L += ["", f"(표본이 부족해 이 가설 결과를 쓰지 못함: {type(e).__name__})"]
    try:
        r = res.get("H3")
        if r:
            L += ["", f"## H3 혁신성의 일관성 ({r['years'][0]}년 이슈 {r['n_issues'].get(r['years'][0])}개 vs {r['years'][1]}년 이슈 {r['n_issues'].get(r['years'][1])}개)", "",
                  f"- 연도 간 선행 점수 순위 상관 ρ = {r['rho']:+.3f} ({_p(r['p'])})",
                  f"- 회의록 분량과의 상관 ρ = {r['rho_volume']:+.3f} ({_p(r['p_volume'])}), 분량 통제 후 상관 = {r['rho_partial']:+.3f} ({_p(r['p_partial'])})",
                  f"- 두 해 모두 앞선 의회: {', '.join(r['consistent_leaders'])}"]
    except Exception as e:  # noqa: BLE001
        L += ["", f"(표본이 부족해 이 가설 결과를 쓰지 못함: {type(e).__name__})"]
    try:
        r = res.get("H4")
        if r:
          L += ["", f"## H4 초점사건·상위정부 계기 (점진형 {r['n_A']}개 vs 동시다발형 {r['n_B']}개, 첫 90일 언급)", "",
              "| 지표 | 점진형 평균 | 동시다발형 평균 | 단측 검정 |", "|---|---|---|---|",
              f"| 사건·재난 표현 비율 | {r['event']['mean_A']:.1%} | {r['event']['mean_B']:.1%} | {_p(r['event']['p'])} |",
              f"| 법령·중앙부처 표현 비율 | {r['upstream']['mean_A']:.1%} | {r['upstream']['mean_B']:.1%} | {_p(r['upstream']['p'])} |"]
    except Exception as e:  # noqa: BLE001
        L += ["", f"(표본이 부족해 이 가설 결과를 쓰지 못함: {type(e).__name__})"]
    try:
        r = res.get("H5")
        if r:
          L += ["", f"## H5 이슈관심주기 (정점 뒤 6개월 이상 관찰된 이슈 {r['n']}개, 3개월 이동평균)", "",
              f"- 정점 후 3~6개월 관심 수준(정점 대비) 중앙값: 실제 {r['median_ratio']:.0%} vs 월 순서를 무작위로 섞은 경우 {r['median_perm']:.0%}",
              f"- 실제가 무작위보다 낮은 이슈 {r['share_below_perm']:.0%} (부호순위 단측 검정 {_p(r['p_vs_perm'])})",
              f"- 점진형 중앙값 {r['median_ratio_A']:.0%} vs 동시다발형 {r['median_ratio_B']:.0%} (동시다발형이 더 빨리 식는지 단측 검정 {_p(r['p_B_faster'])})",
              f"- 정점 대비 절반까지 걸린 기간 중앙값: 점진형 {r['median_half_A']}개월, 동시다발형 {r['median_half_B']}개월"]
    except Exception as e:  # noqa: BLE001
        L += ["", f"(표본이 부족해 이 가설 결과를 쓰지 못함: {type(e).__name__})"]
    try:
        r = res.get("H6")
        if r:
            L += ["", "## H6 Bass 확산모형 (위험률 = p + q × 채택 의회 비율, 월 단위, 유형별 통합 추정)", "",
                  "| 유형 | 이슈 수 | p (외부 영향) | q (모방) | q/p | 위험률: 1곳 채택 시 → 10곳 채택 시 |", "|---|---|---|---|---|---|"]
            for g in ("전체 신규 이슈", "점진형", "동시다발형"):
                x = r[g]
                L.append(f"| {g} | {x['n']} | {x['p']:.4f} [{x['p_ci'][0]:.4f}, {x['p_ci'][1]:.4f}] | {x['q']:.4f} [{x['q_ci'][0]:.4f}, {x['q_ci'][1]:.4f}] "
                         f"| {x['q_over_p']} [{x['q_over_p_ci'][0]}, {x['q_over_p_ci'][1]}] | {x['hazard_1']:.3f} → {x['hazard_10']:.3f} |")
            si = r["single_issue"]
            L += ["", f"- 이슈 하나씩 추정하면 {si['n']}개 중 {si['share_boundary']:.0%}에서 p나 q가 0으로 붙어(경계해) 따로 식별되지 않는다. 그래서 유형 분류에는 쓰지 않는다."]
    except Exception as e:  # noqa: BLE001
        L += ["", f"(표본이 부족해 이 가설 결과를 쓰지 못함: {type(e).__name__})"]
    if res.get("skipped"):
        L += ["", "계산하지 못한 가설: " + ", ".join(f"{k} ({v})" for k, v in res["skipped"].items())]
    open(path_md, "w", encoding="utf-8").write("\n".join(L) + "\n")
