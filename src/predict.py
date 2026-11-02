"""향후 확산 가능성 예측 (이슈 × 미관측 의회).

- 기준 시점 T까지의 정보만으로 특징을 만들고(분석 기준일 이후 정보 사용 금지 조건 준수),
  'T 이후 H일 이내에 해당 의회에서 처음 관측되는가'를 라벨로 한다.
- 검증: 시점 이동(rolling-origin) 백테스트. 검증 시점 tf의 모델은 '라벨 기간(T~T+H)이 tf 이전에 끝난'
  표본만으로 학습해 미래 정보 누수를 막는다.
- 최종: 전체 표본으로 재학습 후 데이터 마지막 날짜(=분석 기준일)를 T로 놓고 예측.
- 모델: 표준화 + 로지스틱 회귀(계수로 예측 근거를 설명할 수 있어 서술형 결과에 적합).
  같은 조건에서 그래디언트 부스팅(HistGradientBoosting)과 비교했을 때 성능이 비슷하거나 낮아 해석 가능한 쪽을 택함.
"""
import math

import numpy as np
import pandas as pd

from .regions import neighbors

EXT_COLS = {"log_pop": "인구(로그)", "fin_indep": "재정자립도", "aging": "고령인구비율", "log_inc": "1인당 지역총소득(로그)"}
FEATS = ["log_n_obs", "frac_obs", "log_n90", "nbr_frac", "nbr_recent", "momentum", "log_recent",
         "sim", "sim_max", "age_years", "asm_new", "asm_vol", "is_ord"]
FEAT_KO = {
    "log_n_obs": "기관측 의회 수", "frac_obs": "기관측 의회 비율", "log_n90": "최근 90일 신규 관측 의회 수",
    "nbr_frac": "인접 광역 관측 비율", "nbr_recent": "최근 180일 인접 광역 신규 관측", "momentum": "언급량 증가율",
    "log_recent": "최근 180일 언급량", "sim": "기관측 의회와의 평균 의제 유사도", "sim_max": "최대 의제 유사도",
    "age_years": "최초 관측 후 경과 기간", "asm_new": "대상 의회의 최근 신규 이슈 수용 수",
    "asm_vol": "대상 의회의 최근 회의 수", "is_ord": "조례(제도화) 이슈 여부",
}
REASON = {
    "log_n_obs": "이미 {n_obs}개 광역의회에서 관측된 이슈",
    "frac_obs": "전체 광역의회의 {frac:.0%}에서 이미 관측",
    "log_n90": "최근 90일 사이 {n90}개 의회에서 새로 논의 시작(확산 가속)",
    "nbr_frac": "인접 광역({nbrs})에서 이미 논의",
    "nbr_recent": "인접 광역({nbrs_recent})에서 최근 6개월 내 논의 시작",
    "momentum": "최근 6개월 전국 언급량이 직전 6개월 대비 {mom:.1f}배",
    "log_recent": "최근 6개월 전국 언급 {recent}건",
    "sim": "의제 구성이 유사한 의회({sims})에서 관측",
    "sim_max": "의제 구성이 가장 유사한 의회({sims})에서 관측",
    "age_years": "최초 관측 후 {age}일 경과",
    "asm_new": "해당 의회가 최근 6개월간 새 의제 {asm_new}건을 다뤄 신규 의제 수용이 활발",
    "asm_vol": "해당 의회의 최근 6개월 회의 {asm_vol}건으로 논의 기회가 많음",
    "is_ord": "조례 제정으로 제도화가 진행 중인 정책 이슈",
}
HEURISTIC_W = dict(log_n_obs=0.6, frac_obs=0.2, log_n90=0.6, nbr_frac=0.8, nbr_recent=0.6, momentum=0.3,
                   log_recent=0.4, sim=0.5, sim_max=0.5, age_years=-0.2, asm_new=0.5, asm_vol=0.2, is_ord=0.1)


def load_external(path):
    """외부 보조 데이터(시도별 통계, 분석 기준일 이전 공표값)를 읽어 의회 코드 -> 특징 dict 로 만든다.
    CSV 열: 의회코드(서울, 부산, ...), 인구, 재정자립도, 고령인구비율, 1인당지역총소득"""
    import os
    if not path or not os.path.exists(path):
        return None
    df = pd.read_csv(path, encoding="utf-8-sig", comment="#")
    out = {}
    for d in df.to_dict("records"):
        out[str(d["의회코드"]).strip()] = dict(
            log_pop=math.log(float(d["인구"])), fin_indep=float(d["재정자립도"]),
            aging=float(d["고령인구비율"]), log_inc=math.log(float(d["1인당지역총소득"])))
    return out


def make_rows(mentions, docs, assemblies, T, horizon=None, active=None, is_ord=None, ext=None):
    D = pd.Timedelta
    first_all = mentions.groupby(["issue_id", "assembly"]).date.min().reset_index()
    f = first_all[first_all.date <= T]
    past = mentions[mentions.date <= T]
    rec = past[past.date > T - D(days=180)].groupby("issue_id").size()
    prev = past[(past.date > T - D(days=360)) & (past.date <= T - D(days=180))].groupby("issue_id").size()
    newly = f[f.date > T - D(days=180)].groupby("assembly").size()
    vol = docs[(docs.date <= T) & (docs.date > T - D(days=180))].groupby("assembly").size()
    asm_issues = f.groupby("assembly").issue_id.agg(set).to_dict()
    if horizon is not None:
        fut = first_all[(first_all.date > T) & (first_all.date <= T + D(days=horizon))]
        pos = set(zip(fut.issue_id, fut.assembly))
    is_ord = is_ord or {}
    rows = []
    for iid, g in f.groupby("issue_id"):
        ad = dict(zip(g.assembly, g.date))
        n_obs, first_date = len(ad), min(ad.values())
        recent_adopters = {a for a, d in ad.items() if d > T - D(days=180)}
        n90 = sum(d > T - D(days=90) for d in ad.values())
        r, p = int(rec.get(iid, 0)), int(prev.get(iid, 0))
        for a in assemblies:
            if a in ad or (active is not None and a not in active):
                continue  # 이미 관측됐거나, 라벨 기간에 회의록이 없어 라벨이 불확실한 의회 제외
            nb = neighbors(a)
            nb_obs = [x for x in nb if x in ad]
            nb_rec = [x for x in nb_obs if x in recent_adopters]
            own = asm_issues.get(a, set()) - {iid}
            sims = []
            for b in ad:
                ob = asm_issues.get(b, set()) - {iid}
                sims.append((len(own & ob) / len(own | ob) if own and ob else 0.0, b))
            sims.sort(reverse=True)
            row = dict(issue_id=iid, assembly=a, cutoff=T,
                       log_n_obs=math.log1p(n_obs), frac_obs=n_obs / len(assemblies), log_n90=math.log1p(n90),
                       nbr_frac=len(nb_obs) / len(nb) if nb else 0.0, nbr_recent=len(nb_rec),
                       momentum=(r + 1) / (p + 1), log_recent=math.log1p(r),
                       sim=float(np.mean([s for s, _ in sims])) if sims else 0.0,
                       sim_max=sims[0][0] if sims else 0.0, age_years=(T - first_date).days / 365,
                       asm_new=math.log1p(newly.get(a, 0)), asm_vol=math.log1p(vol.get(a, 0)),
                       is_ord=int(is_ord.get(iid, 0)),
                       _n_obs=n_obs, _n90=n90, _nbrs=nb_obs, _nbrs_recent=nb_rec, _recent=r,
                       _sims=[b for s, b in sims[:2] if s > 0], _age=(T - first_date).days,
                       _asm_new=int(newly.get(a, 0)), _asm_vol=int(vol.get(a, 0)))
            if ext:
                row.update(ext.get(a, {}))
            if horizon is not None:
                row["y"] = int((iid, a) in pos)
            rows.append(row)
    return pd.DataFrame(rows)


def _new_model():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=3000))


def _score(y, p):
    from sklearn.metrics import average_precision_score, roc_auc_score
    k = max(1, int(len(y) * 0.1))
    top = np.argsort(-p)[:k]
    return dict(roc_auc=float(roc_auc_score(y, p)), avg_precision=float(average_precision_score(y, p)),
                precision_at_top10pct=float(np.asarray(y)[top].mean()), pos_rate=float(np.mean(y)), n=int(len(y)))


def backtest_and_predict(mentions, docs, issues=None, horizon=180, step=60, warmup=180, ext=None):
    feats = FEATS + (list(EXT_COLS) if ext else [])
    assemblies = sorted(docs.assembly.dropna().unique())
    is_ord = {} if issues is None else dict(zip(issues.issue_id, issues.source.map(lambda s: int("조례" in s))))
    d0, d1 = docs.date.min(), docs.date.max()
    H = pd.Timedelta(days=horizon)
    cutoffs = list(pd.date_range(d0 + pd.Timedelta(days=warmup), d1 - H, freq=f"{step}D"))
    frames = []
    for T in cutoffs:
        win = docs[(docs.date > T) & (docs.date <= T + H)]
        frames.append(make_rows(mentions, docs, assemblies, T, horizon, set(win.assembly), is_ord, ext))
    train = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    metrics, model, weights = {}, None, None
    if len(train) and train.y.nunique() == 2 and train.y.sum() >= 10:
        folds = []
        for tf in cutoffs:
            tr, te = train[train.cutoff + H <= tf], train[train.cutoff == tf]  # 누수 방지
            if len(tr) < 500 or tr.y.nunique() < 2 or te.y.nunique() < 2:
                continue
            m = _new_model().fit(tr[feats], tr.y)
            p = m.predict_proba(te[feats])[:, 1]
            sc = _score(te.y.values, p)
            o = te.is_ord.values == 1
            if o.sum() and len(set(te.y.values[o])) == 2:
                sc["ord"] = _score(te.y.values[o], p[o])
            folds.append(dict(cutoff=str(pd.Timestamp(tf).date()), **sc))
        if folds:
            avg = lambda k: round(float(np.mean([f[k] for f in folds])), 4)  # noqa: E731
            metrics = dict(validation="rolling-origin (학습 라벨 기간이 검증 시점 이전에 끝난 표본만 학습)",
                           n_folds=len(folds), roc_auc=avg("roc_auc"), avg_precision=avg("avg_precision"),
                           precision_at_top10pct=avg("precision_at_top10pct"), pos_rate=avg("pos_rate"),
                           folds=folds)
            of = [f["ord"] for f in folds if "ord" in f]
            if of:
                metrics["ordinance_issues"] = {k: round(float(np.mean([f[k] for f in of])), 4)
                                               for k in ("roc_auc", "avg_precision", "precision_at_top10pct", "pos_rate")}
        model = _new_model().fit(train[feats], train.y)
        weights = {{**FEAT_KO, **EXT_COLS}[f]: round(float(c), 3) for f, c in zip(feats, model[-1].coef_[0])}
        metrics["mode"] = "logistic_regression"
        metrics["n_train"] = int(len(train))
    else:
        metrics["mode"] = "heuristic (백테스트용 양성 사례 부족 또는 데이터 기간이 짧음)"

    final = make_rows(mentions, docs, assemblies, d1, is_ord=is_ord, ext=ext)
    if not len(final):
        return final, metrics, weights
    if model is not None:
        final["p"] = model.predict_proba(final[feats])[:, 1]
        contrib = model[0].transform(final[feats]) * model[-1].coef_[0]
    else:
        X = final[feats].values
        z = (X - X.mean(0)) / (X.std(0) + 1e-9)
        contrib = z * np.array([HEURISTIC_W.get(f, 0.0) for f in feats])
        final["p"] = 1 / (1 + np.exp(-contrib.sum(1)))
    final["reasons"] = [_reasons(r, c, feats) for r, c in zip(final.to_dict("records"), contrib)]
    # 등급은 같은 기준일 예측 전체에서의 상대 순위(상위 10% 높음, 다음 20% 보통)
    rank = final.p.rank(pct=True)
    final["tier"] = np.where(rank >= 0.9, "높음", np.where(rank >= 0.7, "보통", "낮음"))
    return final, metrics, weights


def _reasons(r, contrib, feats=FEATS, k=3):
    out = []
    for j in np.argsort(-contrib):
        if len(out) >= k or contrib[j] <= 0:
            break
        f = feats[j]
        if f not in REASON:
            continue  # 외부 통계 특징은 의회 고유 속성이라 이슈별 근거 문장에서는 생략
        if (f == "nbr_frac" and not r["_nbrs"]) or (f == "nbr_recent" and not r["_nbrs_recent"]) \
                or (f in ("sim", "sim_max") and not r["_sims"]) or (f == "is_ord" and not r["is_ord"]) \
                or (f == "log_n90" and not r["_n90"]):
            continue
        txt = REASON[f].format(n_obs=r["_n_obs"], frac=r["frac_obs"], n90=r["_n90"], nbrs=", ".join(r["_nbrs"]),
                               nbrs_recent=", ".join(r["_nbrs_recent"]), mom=r["momentum"], recent=r["_recent"],
                               sims=", ".join(r["_sims"]), age=r["_age"], asm_new=r["_asm_new"],
                               asm_vol=r["_asm_vol"])
        if txt not in out:
            out.append(txt)
    return out
