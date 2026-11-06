"""notebooks/01_전체_분석_과정.ipynb 를 만든다(셀 내용은 이 파일이 원본). 실행: python scripts/make_notebook.py"""
import nbformat as nbf

md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell
C = []

C.append(md("""# 광역 지방의회 회의록 기반 지방정책 이슈 트렌드 분석 및 확산 흐름 예측 — 전체 분석 과정

팀 ripple · 2026 DATA·AI 분석 경진대회 문제해결 부문 (국회도서관 정책지정 문제)

이 노트북은 `run_pipeline.py`가 한 번에 수행하는 과정을 **단계별로 풀어서** 실행하고, 각 단계의 결과를 확인·시각화한다. 계산은 모두 `src/`의 같은 함수를 호출하므로 결과는 `run_pipeline.py` 실행 결과와 같다.

| 단계 | 내용 |
|---|---|
| 1 | 데이터 불러오기·전처리 (회의록 → 발언) |
| 2 | 정책 이슈 후보 추출 (조례안 + 신규 키워드) |
| 3 | 이슈 병합·분석자 검토 규칙 적용·원문 색인 |
| 4 | 의회별 최초 관측과 증거 등급, 유형 분류 |
| 5 | 확산 예측 모델 **학습**과 시점 이동 **평가** |
| 6 | 모델 저장·불러오기와 **추론** |
| 7 | 정책확산 이론 가설 검증 |
| 8 | 사후 검증 (지난 시점 예측 vs 이후 실제) |
| 9 | 보고서·대시보드 생성 |

**실행 방법**: 저장소 최상위의 `data/`에 회의록 JSON을 넣고, `notebooks/` 폴더에서 이 노트북을 위에서부터 차례로 실행한다. 전체 데이터 기준 약 20분, 메모리 약 6GB가 필요하다. 경로는 아래 셀의 환경변수로 바꿀 수 있다.

> 인과 표현 원칙: 이 분석의 모든 결과는 **조건부 연관**이며, 의회 간 '확산 경로'는 증거 등급이 허용하는 만큼만 주장한다."""))

C.append(code("""import os, sys, time, json
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)                      # config/ 경로를 저장소 기준으로 맞춘다

DATA_DIR  = os.environ.get("DATA_DIR", "data")                 # 회의록 JSON 폴더
CACHE_DIR = os.environ.get("CACHE_DIR", "cache")               # 회의록 읽기 결과 보관(두 번째 실행부터 빠름)
OUT_DIR   = os.environ.get("OUT_DIR", "output_notebook")       # 이 노트북의 산출물
PREV_DIR  = os.environ.get("PREV_DIR", "output_prev")          # 사후 검증용 지난 시점 결과(8단계, 없으면 건너뜀)
os.makedirs(OUT_DIR, exist_ok=True)

import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager
for f in ["Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "Noto Sans CJK TC", "NanumGothic"]:
    if any(f in x.name for x in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f; break
plt.rcParams["axes.unicode_minus"] = False
pd.set_option("display.max_colwidth", 80)

from run_pipeline import cached_tables
from src import issues as I, predict as PR, hypotheses as HY, update as UP
from src.spread import analyze_all
from src.report import rank_issues, is_novel, write_report, assembly_keywords
from src.dashboard import build_payload, write_dashboard
T0 = time.time()
print("저장소:", ROOT, "| 데이터:", DATA_DIR)"""))

C.append(md("""## 1. 데이터 불러오기·전처리

- 본문 해시로 중복 회의록을 제거한다(제목이 같아도 위원회·차수가 다른 회의록이 약 29%라 제목 기준으로 지우면 안 된다).
- 의회별 발언자 표기 규칙으로 발언을 나누고, 15자 미만 발언은 뺀다."""))
C.append(code("""docs, utts = cached_tables(DATA_DIR, CACHE_DIR)
print(f"회의록 {len(docs):,}건 / 발언 {len(utts):,}개 / 의회 {docs.assembly.nunique()}곳 "
      f"({docs.date.min():%Y-%m-%d} ~ {docs.date.max():%Y-%m-%d})")
summary = (docs.groupby("assembly").agg(회의록=("doc_id", "size"))
           .join(utts.groupby("assembly").agg(발언=("utt_id", "size"))).sort_values("발언", ascending=False))
summary"""))
C.append(code("""fig, ax = plt.subplots(figsize=(10, 3.2))
docs.set_index("date").resample("MS").size().plot(ax=ax, color="#1F3864")
ax.set_title("월별 회의록 수 (17개 광역의회)"); ax.set_xlabel(""); ax.set_ylabel("회의록 수"); plt.tight_layout()"""))

C.append(md("""## 2. 정책 이슈 후보 추출

두 경로를 결합한다.
- **조례안 기반(정밀도)**: 의안명에서 지역명·법령 형식어·개정 형식어를 지워 정책 단위로 정규화한다.
- **신규 키워드(재현율)**: Kiwi 형태소 분석으로 명사구를 확인한 뒤, 3개 이상 의회·8건 이상, 통계적 신규성 검정 $(1-q)^{df} < 5\\%$, 화제성 조건을 통과한 표현만 남긴다."""))
C.append(code("""ords = I.extract_ordinances(utts)
print(f"조례안 기반 후보 {len(ords):,}개")
ords.sort_values("n_asm", ascending=False).head(8)"""))
C.append(code("""t = time.time()
emer = I.extract_emerging_terms(utts, use_kiwi=True, min_df=8, min_asm=3)   # 전체 데이터 약 4~5분
print(f"신규 키워드 후보 {len(emer):,}개 ({time.time()-t:.0f}초)")
emer = I.filter_keywords(emer)
emer.head(8)"""))

C.append(md("""## 3. 이슈 병합·분석자 검토 규칙·원문 색인

같은 의제의 다른 표현을 핵심어·포함 관계·문자 n-gram TF-IDF로 묶는다. 자동 결과는 분석자가 검토한 세 파일(`config/`)로 보정한다: 제외 목록, 병합 규칙, 사건 의제의 시작일."""))
C.append(code("""cands = pd.concat([ords[ords.n_asm >= 2], emer], ignore_index=True)
issues = I.merge_candidates(cands, model_name=None)                 # 제출 결과와 같은 기본 설정(TF-IDF)
issues, n_merged = I.apply_manual_merges(issues, "config/merge_issues.txt")
issues, n_frag = I.drop_fragment_surfaces(issues)
ex = {l.strip() for l in open("config/exclude_issues.txt", encoding="utf-8") if l.strip() and not l.startswith("#")}
before = len(issues); issues = issues[~issues.label.isin(ex)].reset_index(drop=True)
print(f"병합 규칙 {n_merged}개 · 조각 표현 제거 {n_frag}개 · 제외 {before-len(issues)}개 → 이슈 {len(issues):,}개")

mentions = I.index_mentions(utts, issues)
mentions, n_drop = I.apply_issue_start(mentions, issues, "config/issue_start.txt")
print(f"이슈 언급 {len(mentions):,}건 색인 (사건 시작일 이전 언급 {n_drop}건 제외)")
issues[["issue_id", "label", "source"]].head(8)"""))

C.append(md("""## 4. 의회별 최초 관측·증거 등급·유형 분류

후속 의회마다 Campbell의 인과 조건(시간적 선행, 대상 일치, 선례 단서어, 참조 방향, 도입 시점 180일 이내)과 과정추적 검정(공식 입법 맥락)에 따라 증거 등급을 매긴다. 관측 의회 절반 이상이 60일 안에 시작한 의제는 **동시다발형**으로 분류해 의회 간 경로를 추정하지 않는다."""))
C.append(code("""spread = analyze_all(mentions, issues)
d0 = docs.date.min()
ranked = rank_issues(issues, spread, d0=d0)
novel = [i for i in ranked if is_novel(spread[i], d0)]
n_simul = sum(spread[i]["simultaneous"] for i in novel)
print(f"3개 이상 의회 이슈 {len(ranked)}개 → 기간 중 새로 등장한 의제 {len(novel)}개 "
      f"(점진 확산형 {len(novel)-n_simul}, 동시다발형 {n_simul})")

grade_ko = {"strong": "결정적 증거", "medium": "명시적 참조", "predata": "데이터 이전 선행",
            "nonspecific": "비특정 참조", "temporal": "시간적 후행"}
g = pd.Series([t.get("evidence") or "temporal" for i in novel for t in spread[i]["timeline"] if t["relation"] != "origin"])
grades = g.map(grade_ko).value_counts().reindex(list(grade_ko.values())).fillna(0).astype(int)
display(grades.to_frame("신규 의제 후속 의회 수"))
fig, ax = plt.subplots(figsize=(8, 2.6))
ax.barh(grades.index[::-1], np.log10(grades.values[::-1] + 1), color=["#c3cad5", "#4a78c2", "#9aa5b1", "#e07b39", "#c55a11"])
for y, v in enumerate(grades.values[::-1]): ax.text(np.log10(v + 1) + .02, y, f"{v:,}", va="center")
ax.set_xlabel("log10(곳 + 1)"); ax.set_title("증거 등급 분포: 인과를 말할 수 있는 곳은 일부뿐"); plt.tight_layout()"""))
C.append(code("""# 사례: 결정적 증거가 확인된 의제
case = next(i for i in novel if any(t.get("evidence") == "strong" for t in spread[i]["timeline"]))
lab = dict(zip(issues.issue_id, issues.label))
print("의제:", lab[case])
pd.DataFrame([dict(순서=t["order"], 의회=t["assembly_name"], 최초관측=pd.Timestamp(t["first_date"]).date(),
                   판정=grade_ko.get(t.get("evidence"), "최초 관측" if t["relation"] == "origin" else "시간적 후행"),
                   회의록=t["minutes_name"]) for t in spread[case]["timeline"]])"""))
C.append(code("""t = next(t for t in spread[case]["timeline"] if t.get("evidence") == "strong")
r = t["explicit_refs"][0]
print(f"{t['assembly_name']} ← {r['source']} 사례 언급 ({r.get('date')})\\n원문: {r['snippet'][:300]}")"""))

C.append(md("""## 5. 확산 예측 모델 학습과 평가

- **예측 단위**: (이슈, 아직 관측되지 않은 의회) 쌍. **라벨**: 기준 시점 T 이후 180일 안에 처음 관측되는지.
- **특징 13개**(모두 T 이전 정보): 확산 규모·속도, 인접 광역, 관심도 추세, 의제 유사도, 의회 성향, 조례 여부.
- **모형**: 표준화 + 로지스틱 회귀(class_weight='balanced').
- **평가(시점 이동 검증)**: 기준 시점마다, 라벨 기간이 그 시점 이전에 끝난 표본으로만 학습해 미래 정보를 차단한다."""))
C.append(code("""t = time.time()
preds, metrics, weights = PR.backtest_and_predict(mentions, docs, issues, horizon=180)
print(f"학습 표본 {metrics['n_train']:,}건 ({time.time()-t:.0f}초)")
folds = pd.DataFrame(metrics["folds"])[["cutoff", "n", "roc_auc", "precision_at_top10pct", "pos_rate"]]
folds["상위10%/기저"] = (folds.precision_at_top10pct / folds.pos_rate).round(2)
display(folds)
print({k: metrics[k] for k in ["roc_auc", "avg_precision", "precision_at_top10pct", "pos_rate"]}, "| 조례 의제:", metrics.get("ordinance_issues"))"""))
C.append(code("""fig, ax = plt.subplots(1, 2, figsize=(11, 3.4))
x = np.arange(len(folds))
ax[0].bar(x - .2, folds.precision_at_top10pct, .4, label="상위 10% 적중률", color="#c55a11")
ax[0].bar(x + .2, folds.pos_rate, .4, label="기저 확산률", color="#9aa5b1")
ax[0].set_xticks(x, folds.cutoff); ax[0].legend(); ax[0].set_title("기준 시점별 평가")
w = pd.Series(weights).sort_values()
ax[1].barh(w.index, w.values, color=["#2e5c99" if v > 0 else "#9aa5b1" for v in w.values])
ax[1].set_title("표준화 계수(최종 모델)"); plt.tight_layout()"""))

C.append(md("""## 6. 모델 저장·불러오기와 추론

학습된 모델은 `model/forecast_model.joblib`(scikit-learn 파이프라인)과 `model/forecast_model.json`(특징·표준화 값·계수)으로 저장한다. 아래에서 저장한 모델을 다시 불러와 데이터 마지막 날 기준의 예측을 재현한다."""))
C.append(code("""import joblib
model, feats = PR.LAST_MODEL
PR.save_model(model, feats, os.path.join(OUT_DIR, "model"), metrics)
loaded = joblib.load(os.path.join(OUT_DIR, "model", "forecast_model.joblib"))
p2 = loaded["model"].predict_proba(preds[loaded["features"]])[:, 1]
print("불러온 모델로 다시 계산한 점수와 저장된 점수의 최대 차이:", float(np.abs(p2 - preds.p.values).max()))
out = preds.assign(의제=preds.issue_id.map(lab)).sort_values("p", ascending=False)
out.loc[out.issue_id.isin(novel), ["의제", "assembly", "p", "tier", "reasons"]].head(10)"""))

C.append(md("""## 7. 정책확산 이론 가설 검증 (H1~H6)

예측 모델과 같은 표본으로 이론 모형을 따로 적합하고, 이슈 단위 군집 부트스트랩·순열 검정·Bass 위험률 모형으로 검정한다."""))
C.append(code("""hres = HY.run_all(PR.LAST_TRAIN, spread, novel, docs, mentions)
HY.write(hres, os.path.join(OUT_DIR, "hypotheses.md"), os.path.join(OUT_DIR, "hypotheses.json"))
print(open(os.path.join(OUT_DIR, "hypotheses.md"), encoding="utf-8").read()[:2500])"""))

C.append(md("""## 8. 사후 검증: 지난 시점 예측 vs 이후 실제

`PREV_DIR`에 2025-09-30 시점 분석 결과(`python run_pipeline.py --until 2025-09-30 --out_dir output_prev`)가 있으면, 그 시점의 이슈 사전과 예측을 **모델이 보지 않은 이후 기간**의 발언과 대조한다. 없으면 이 단계는 건너뛴다."""))
C.append(code("""upd = None
if os.path.exists(os.path.join(PREV_DIR, "work")):
    upd = UP.compare(UP.load_prev(PREV_DIR), docs, utts, issues, spread, ranked, set(novel))
    UP.write(upd, os.path.join(OUT_DIR, "update.md"), os.path.join(OUT_DIR, "update.json"))
    c = upd["check"]
    tiers = pd.DataFrame(c["tiers"]).T[["n", "hit", "rate", "lift"]]
    display(tiers)
    print(f"지난 기준일 {upd['prev_d1']} → 이후 {upd['days']}일, 새 회의록 {upd['new_docs']:,}건 | 평균 {c['base']:.1%} | ROC-AUC {c['auc']}")
    fig, ax = plt.subplots(figsize=(7, 2.4))
    ax.barh(tiers.index[::-1], tiers.rate[::-1] * 100, color=["#aab3c0", "#2e5c99", "#c55a11"])
    ax.axvline(c["base"] * 100, color="k", lw=1); ax.set_xlabel("이후 92일 안에 실제로 논의한 비율(%)")
    ax.set_title("사후 검증: 예측 등급별 실제 논의 비율 (검은 선: 평균)"); plt.tight_layout()
else:
    print("지난 시점 결과가 없어 사후 검증을 건너뜀:", PREV_DIR)"""))

C.append(md("""## 9. 보고서·대시보드 생성"""))
C.append(code("""order = write_report(os.path.join(OUT_DIR, "report.md"), os.path.join(OUT_DIR, "results.json"), docs, utts, issues,
                     mentions, spread, preds, metrics, weights, top_n=15, hres=hres, upd=upd)
write_dashboard(os.path.join(OUT_DIR, "dashboard.html"),
                build_payload(docs, issues, spread, preds, metrics, weights, novel, len(utts),
                              assembly_keywords(mentions, issues), mentions, upd=upd))
print(f"보고서 의제 {len(order)}개, 대시보드 의제 {len(novel)}개 → {OUT_DIR}/ | 전체 {(time.time()-T0)/60:.1f}분")"""))

nb = nbf.v4.new_notebook(cells=C, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                                            "language_info": {"name": "python"}})
nbf.write(nb, "notebooks/01_전체_분석_과정.ipynb")
print("ok")
