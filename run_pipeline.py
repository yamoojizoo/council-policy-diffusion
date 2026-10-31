"""전체 파이프라인 실행.

예) python run_pipeline.py --data_dir ./data --out_dir ./output
"""
import argparse
import json
import os
import time

import pandas as pd

from src import issues as I
from src.predict import backtest_and_predict
from src.preprocess import build_tables
from src.dashboard import build_payload, write_dashboard
from src.report import is_novel, rank_issues, write_report
from src.spread import analyze_all


def save(df, path):
    try:
        df.to_parquet(path + ".parquet")
    except ImportError:
        df.to_pickle(path + ".pkl")


def load(path):
    return pd.read_parquet(path + ".parquet") if os.path.exists(path + ".parquet") else pd.read_pickle(path + ".pkl")


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:7.1f}s] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", default="data")
    ap.add_argument("--out_dir", default="output")
    ap.add_argument("--embed_model", default="jhgan/ko-sroberta-multitask",
                    help="로컬 실행 문장임베딩 모델. 빈 문자열이면 문자 n-gram TF-IDF 사용")
    ap.add_argument("--kiwi_full", action="store_true", help="모든 발언을 Kiwi로 분석(정확하지만 느림)")
    ap.add_argument("--no_kiwi", action="store_true", help="Kiwi 형태소 분석 대신 규칙 기반 명사구 추출")
    ap.add_argument("--min_df", type=int, default=8)
    ap.add_argument("--min_asm", type=int, default=3)
    ap.add_argument("--horizon_days", type=int, default=180)
    ap.add_argument("--top_n", type=int, default=15)
    ap.add_argument("--exclude", default="config/exclude_issues.txt",
                    help="분석자가 검토 후 제외할 이슈 대표 명칭 목록(한 줄에 하나)")
    ap.add_argument("--reuse", action="store_true", help="work/ 에 저장된 전처리 결과 재사용")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    work = os.path.join(a.out_dir, "work")
    os.makedirs(work, exist_ok=True)

    if a.reuse and any(os.path.exists(f"{work}/utterances{e}") for e in (".parquet", ".pkl")):
        docs, utts = load(f"{work}/docs"), load(f"{work}/utterances")
        log("전처리 결과 재사용")
    else:
        docs, utts = build_tables(a.data_dir)
        save(docs, f"{work}/docs")
        save(utts, f"{work}/utterances")
    log(f"회의록 {len(docs):,}건 / 발언 {len(utts):,}개 / 의회 {docs.assembly.nunique()}곳 "
        f"({docs.date.min():%Y-%m-%d}~{docs.date.max():%Y-%m-%d})")

    ords = I.extract_ordinances(utts)
    log(f"조례안 기반 후보 {len(ords):,}개")
    if a.reuse and os.path.exists(f"{work}/emerging.pkl"):
        emer = pd.read_pickle(f"{work}/emerging.pkl")
        log(f"신규 키워드 후보 재사용 {len(emer):,}개")
    else:
        emer = I.extract_emerging_terms(utts, use_kiwi=not a.no_kiwi, kiwi_full=a.kiwi_full, min_df=a.min_df,
                                        min_asm=a.min_asm)
        emer.to_pickle(f"{work}/emerging.pkl")
        log(f"신규 키워드 후보 {len(emer):,}개")
    emer = I.filter_keywords(emer)
    cands = pd.concat([ords[ords.n_asm >= 2] if len(ords) else ords, emer], ignore_index=True)
    issues = I.merge_candidates(cands, model_name=a.embed_model or None)
    if a.exclude and os.path.exists(a.exclude):
        ex = {l.strip() for l in open(a.exclude, encoding="utf-8") if l.strip() and not l.startswith("#")}
        before = len(issues)
        issues = issues[~issues.label.isin(ex)].reset_index(drop=True)
        log(f"제외 목록({a.exclude}) 적용: {before - len(issues)}개 제외")
    log(f"병합 후 이슈 {len(issues):,}개")

    mentions = I.index_mentions(utts, issues)
    save(mentions, f"{work}/mentions")
    log(f"이슈 언급 {len(mentions):,}건 색인")

    spread = analyze_all(mentions)
    pd.to_pickle(spread, f"{work}/spread.pkl")
    log("최초 관측·후속 흐름 분석 완료")

    preds, metrics, weights = backtest_and_predict(mentions, docs, issues, horizon=a.horizon_days)
    log("확산 예측 완료: " + str({k: v for k, v in metrics.items() if k != "folds"}))
    pd.to_pickle((preds, metrics, weights), f"{work}/forecast.pkl")
    if len(preds):
        preds.drop(columns=[c for c in preds.columns if c.startswith("_")]).to_csv(
            f"{a.out_dir}/forecast_all.csv", index=False, encoding="utf-8-sig")

    issues.to_json(f"{a.out_dir}/issue_dictionary.json", orient="records", force_ascii=False, indent=1)
    order = write_report(f"{a.out_dir}/report.md", f"{a.out_dir}/results.json", docs, utts, issues, mentions,
                         spread, preds, metrics, weights, top_n=a.top_n)
    log(f"보고서 작성: {a.out_dir}/report.md (이슈 {len(order)}개)")
    d0 = docs.date.min()
    novel = [i for i in rank_issues(issues, spread, d0=d0) if is_novel(spread[i], d0)]
    write_dashboard(f"{a.out_dir}/dashboard.html",
                    build_payload(docs, issues, spread, preds, metrics, weights, novel, len(utts)))
    log(f"대시보드 작성: {a.out_dir}/dashboard.html (이슈 {len(novel)}개)")


if __name__ == "__main__":
    main()
