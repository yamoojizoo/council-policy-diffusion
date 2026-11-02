"""이슈 후보 추출 -> 동의 표현 병합 -> 회의록 내 언급(mention) 색인.

이슈 후보는 두 경로로 만든다.
  (A) 조례안 명칭: '서울특별시 고립·은둔청년 지원 조례안' -> '고립·은둔청년 지원'
      지역명을 떼어내 의회 간 동일 정책을 맞대어 볼 수 있게 한다. (정밀도 높음)
  (B) 신규 등장 키워드: 형태소 분석(Kiwi)으로 명사구를 뽑고, 데이터 초기 구간에는 없다가
      이후 여러 의회에서 나타나는 표현을 '신규 이슈'로 본다. (재현율 보완)
"""
import math
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .regions import REGION_FULL_ALT, PREFIX_RE, REGIONS

SEP = re.compile(r"[\s·ㆍ‧\-・,]")
# 의안 형식(…조례안 / …조례 일부개정조례안 / 전부개정조례안 / 폐지조례안)만 인정한다. 발언 중 '조례'라는 단어는 제외.
BILL_SUFFIX = r"조례\s*(?:안|일부\s*개정\s*조례안|전부\s*개정\s*조례안|폐지\s*조례안)"
ORD_RE = re.compile(r"(?:%s)(?:교육청)?\s*([가-힣A-Za-z0-9·ㆍ‧\-\s]{2,50}?)\s*(%s)" % (REGION_FULL_ALT, BILL_SUFFIX))
QUOTED_ORD_RE = re.compile(r"「([^」]{2,70}?)\s*(%s)」" % BILL_SUFFIX)
# 조례 명칭 안에 나오면 발언 문장을 잘못 잡은 것으로 보는 표현
SPEECH_IN_CORE = re.compile(r"(?:^|\s)(?:이|그|저|이런|그런|저런|같은|경우|차원|저희|우리|지금|여기|거기|말씀|부분|"
                            r"하는|있는|되는|했던|하고|해서|에서는|에서|으로|에는|이라는|라는|이번|관련해서|대해서)(?:\s|$)|"
                            r"(?:습니다|합니다|입니다|는데|지요|어요|에서는|으로는)")
PARTICLE_TAIL = re.compile(r"\s*(에\s*관한|에\s*대한|을\s*위한|를\s*위한|의)\s*$")
GENERIC_TAIL = re.compile(r"\s*(설치\s*및\s*운영|지원|육성|진흥|활성화|보호|관리|운영|조성|증진|예방|촉진|기본|및|등|"
                          r"에\s*관한|에\s*대한|을\s*위한|를\s*위한)\s*$")
ADMIN_STOP = ["정원", "행정기구", "수수료", "사용료", "보수", "수당", "여비", "실비", "회의규칙", "사무처", "직제",
              "공유재산", "세입", "세출", "예산", "결산", "기금운용", "시행규칙", "사무위탁", "의정활동비",
              "지방공무원", "복무", "징계", "포상", "표창", "출자", "출연", "위원회 구성", "조직", "감사", "인사"]
GENERIC_WORDS = {"관련", "관한", "대한", "도입", "운영", "지원", "예방", "추진", "사업", "계획", "문제", "상황", "경우", "부분",
                 "말씀", "생각", "의원", "위원", "위원장", "다음", "지금", "우리", "내용", "부분", "필요", "검토", "현황",
                 "보고", "후속", "질의", "특정", "중심", "보도", "부담", "손실", "연령", "효과", "상태", "수준", "방식", "과정",
                 "실제", "일부", "전체", "의향", "연도", "그때", "여건", "흐름", "진전", "어르신들", "시작", "이후", "이전",
                 "당시", "최근", "기존", "향후", "각종", "여러", "모든", "다른", "자체적", "전반", "부족", "증가", "감소", "답변", "관리", "시행", "확대", "마련", "방안", "대책", "정도", "이번", "해당"}
# 회의 진행·예산 심사 등 매년 반복되는 절차어 (계절성 때문에 '신규'로 오인되기 쉬움)
PROC_WORDS = {"예산", "예산안", "추가경정", "추경", "결산", "감사", "행정사무감사", "위원회", "회의", "자료", "제출", "요구",
              "요청", "선서", "선서문", "의결", "안건", "안건보기", "심사", "소관", "정례회", "임시회", "상반기", "하반기",
              "내년", "올해", "작년", "오늘", "금년", "조정", "집행", "규모", "기간", "범위", "차이", "선임", "선출",
              "업무보고", "주요업무보고", "의안검토보고서", "검토보고", "진행순서", "종료", "실시", "전달", "만일", "거짓",
              "조금", "후반기", "전반기", "서류제출", "지방채", "발행", "답변", "질문", "시정질문", "도정질문", "교육행정질문",
              "회의록", "속기", "의사일정", "개의", "산회", "정회", "부의", "상정", "가결", "원안", "수정안", "동의",
              "말씀", "부분", "정도", "생각", "사항", "내용", "관련", "문제", "그런", "이런", "저희", "우리"}
PROC_SUBSTR = ["예산", "회계", "세입", "세출", "기금", "승인", "채택", "보고서", "회의록", "부록", "위원회", "결산", "감사",
               "의석", "심사", "수정내역", "계획서", "현안업무", "주요업무", "핵심사항", "당해", "의회", "조례", "의안",
               "질의", "답변", "업무보고", "추진상황", "추진실적", "교부", "이전수입", "보조금", "출연금", "본회의",
               "집행", "불용", "잔액", "징수", "설명서", "사업별", "주요", "자체", "객관적", "효과성", "구체적",
               "전반적", "지적사항", "처리결과", "시정요구", "건의사항", "명시이월", "사고이월", "세출", "이월",
               "쪽", "페이지", "교정", "임시회의록", "페이퍼", "자료", "번째", "각종", "전년", "대비", "증감", "편성"]
TITLE_TOKEN = re.compile(r"(님|국장|과장|실장|본부장|위원장|위원|의원|의장|청장|원장|단장|팀장|처장|소장|사장|관|감)$")
REGION_WORDS = {a for v in REGIONS.values() for a in v["alias"] + v["full"]} | set(REGIONS)


def nospace(s: str) -> str:
    return SEP.sub("", s or "")


def normalize_core(s):
    s = PREFIX_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ·,")
    for _ in range(3):
        s = PARTICLE_TAIL.sub("", s)
    return s.strip()


def key_term(core):
    k = core
    for _ in range(4):
        new = GENERIC_TAIL.sub("", k).strip()
        if new == k:
            break
        k = new
    k = k.strip(" ·ㆍ‧,-")
    return k if len(nospace(k)) >= 3 else core


# ------------------------------------------------------------ (A) 조례안
def extract_ordinances(utts):
    stat = defaultdict(lambda: dict(n=0, asm=set(), first=None, kinds=Counter()))
    for text, asm, date in zip(utts.text.values, utts.assembly.values, utts.date.values):
        if "조례" not in text:
            continue
        for rx in (ORD_RE, QUOTED_ORD_RE):
            for m in rx.finditer(text):
                core = normalize_core(m.group(1))
                if len(nospace(core)) < 3 or any(w in core for w in ADMIN_STOP) or core.startswith("의회"):
                    continue
                if SPEECH_IN_CORE.search(core) or len(core) > 40:
                    continue
                suf = re.sub(r"\s", "", m.group(2))
                kind = "개정" if "개정" in suf else ("폐지" if "폐지" in suf else "제정")
                st = stat[core]
                st["n"] += 1
                st["asm"].add(asm)
                st["kinds"][kind] += 1
                st["first"] = date if st["first"] is None or date < st["first"] else st["first"]
    rows = [dict(label=c, key=key_term(c), source="조례", n=v["n"], n_asm=len(v["asm"]),
                 first=v["first"], kind=v["kinds"].most_common(1)[0][0]) for c, v in stat.items()]
    return pd.DataFrame(rows)


# ------------------------------------------------------------ (B) 신규 키워드
def _ngrams(run, out):
    for n in (2, 3):
        for i in range(len(run) - n + 1):
            out.add(" ".join(run[i:i + n]))


def _noun_phrases_kiwi(texts, kiwi):
    """연속 명사(공백 1칸까지 허용) 덩어리에서 2~3어절 n-gram을 뽑는다. 접미사(XSN, 예: 정기+권)는 앞 명사에 붙인다."""
    for toks in kiwi.tokenize(texts):
        out, run, prev_end = set(), [], -2
        for t in toks:
            if t.tag == "XSN" and run and t.start == prev_end:
                run[-1] += t.form
                prev_end = t.start + t.len
            elif t.tag in ("NNG", "NNP", "SL"):
                if run and t.start == prev_end:          # 붙어 있는 명사는 한 단어로 (성+범죄)
                    run[-1] += t.form
                elif run and t.start - prev_end <= 1:     # 공백 하나 -> 같은 명사구의 다음 어절
                    run.append(t.form)
                else:
                    _ngrams(run, out)
                    run = [t.form]
                prev_end = t.start + t.len
            else:
                _ngrams(run, out)
                run, prev_end = [], -2
        _ngrams(run, out)
        yield {p for p in out if len(nospace(p)) >= 4}


_JOSA = re.compile(r"(으로서|으로는|에서는|에게는|으로|에서|에게|까지|부터|이라는|이라|라는|라고|처럼|보다|이나|에는|"
                   r"의|은|는|이|가|을|를|에|와|과|도|로|만)$")
_VERBISH = re.compile(r"(하는|하고|하여|해서|했|합니|입니|습니|됩니|있는|없는|되는|된|한|할|함|하며|하게|하지|드리|겠)")


def _noun_phrases_fallback(texts):
    for text in texts:
        raw = re.findall(r"[가-힣A-Za-z0-9]+|[^가-힣A-Za-z0-9\s]", text)
        words = [None if (len(w) < 2 or _VERBISH.search(w)) else _JOSA.sub("", w) for w in raw]
        out = set()
        for (a, ra), (b, _) in zip(zip(words, raw), zip(words[1:], raw[1:])):
            # 앞 어절에 조사가 붙어 있으면 명사구가 끊긴 것으로 본다
            if a and b and a == ra and len(a) >= 2 and len(b) >= 2:
                out.add(f"{a} {b}")
        yield out


def _kiwi_validate(phrases, kiwi):
    """후보 구가 실제로 명사(구)인지 형태소 분석으로 검증하고, 조사 등이 붙었으면 명사 부분만 남긴다."""
    ok = {}
    for p, toks in zip(phrases, kiwi.tokenize(phrases)):
        if toks and all(t.tag in ("NNG", "NNP", "SL", "XSN", "SN") for t in toks) and toks[0].tag != "XSN":
            ok[p] = p
    return ok


def extract_emerging_terms(utts, use_kiwi=True, kiwi_full=False, min_df=8, min_asm=3, early_frac=0.1, novelty_p=0.05,
                           max_terms=1500, prune_every=3000):
    """데이터 초기 구간(early_frac)에는 없다가 이후 여러 의회에서 등장한 명사구.

    기본(fast): 규칙 기반으로 2어절 후보를 빠르게 모은 뒤, 살아남은 후보만 Kiwi로 명사구 검증.
    kiwi_full : 모든 발언을 Kiwi로 분석(정확하지만 대용량에서 느림).
    메모리 절약을 위해 문서 빈도 1인 후보는 주기적으로 버린다(lossy counting).
    """
    kiwi = None
    if use_kiwi:
        try:
            from kiwipiepy import Kiwi
            kiwi = Kiwi(num_workers=-1)
        except Exception as e:  # pragma: no cover
            print(f"[issues] Kiwi 사용 불가({e}) -> 규칙 기반 추출만 사용")
    texts = utts.text.tolist()
    gen = _noun_phrases_kiwi(texts, kiwi) if (kiwi is not None and kiwi_full) else _noun_phrases_fallback(texts)

    asm_codes = {a: i for i, a in enumerate(sorted(utts.assembly.unique()))}
    stat = {}                        # phrase -> [df, asm_bitmask, first_date, 4분기 문서 수]
    cur_doc, cur_set, cur_asm, cur_date, n_docs = None, set(), 0, None, 0

    def flush():
        bit = 1 << cur_asm
        q4 = int(pd.Timestamp(cur_date).month >= 10)   # 행정사무감사·예산 심사 시즌
        for p in cur_set:
            st = stat.get(p)
            if st is None:
                stat[p] = [1, bit, cur_date, q4]
            else:
                st[0] += 1
                st[1] |= bit
                st[3] += q4
                if cur_date < st[2]:
                    st[2] = cur_date

    for phrases, doc, asm, date in zip(gen, utts.doc_id.values, utts.assembly.values, utts.date.values):
        if doc != cur_doc:
            if cur_doc is not None:
                flush()
                n_docs += 1
                if n_docs % prune_every == 0:
                    for p in [p for p, st in stat.items() if st[0] < 2]:
                        del stat[p]
            cur_doc, cur_set, cur_asm, cur_date = doc, set(), asm_codes[asm], date
        cur_set |= phrases
    if cur_doc is not None:
        flush()

    # 발언자 표시에서 사람 이름을 모아 키워드 후보에서 제외
    names = {t for spk in utts.speaker.unique() for t in str(spk).split()
             if re.fullmatch(r"[가-힣]{2,4}", t) and not TITLE_TOKEN.search(t)}
    # 초기 구간은 '기간'이 아니라 '회의록 양' 기준으로 잡는다. 연초·선거철처럼 회의가 적은 시기를 초기 구간으로 잡으면
    # 그 뒤 회의가 몰리는 달에 일반 표현이 대거 '신규'로 잡히기 때문이다.
    early_cut = utts.date.quantile(early_frac).to_datetime64()
    # 통계적 신규성 검정: 어떤 표현이 기간 내내 고르게 쓰였다면, 처음 관측 전 회의록(비율 q)에서 한 번도 안 나올 확률은
    # (1-q)^df 이다. 이 확률이 5% 미만일 때만 '새로 등장'으로 인정한다(우연히 늦게 처음 잡힌 일반 표현 제거).
    doc_dates = np.sort(utts.drop_duplicates("doc_id").date.values)
    rows = []
    for p, (df, bits, first, q4) in stat.items():
        n_asm = bin(bits).count("1")
        if df < min_df or n_asm < min_asm or first <= early_cut:
            continue
        q = np.searchsorted(doc_dates, first) / len(doc_dates)
        if (1 - q) ** df >= novelty_p:
            continue
        if q4 / df >= 0.6:   # 연말 감사·예산 시즌에 몰린 절차어는 계절성으로 보고 제외
            continue
        if any(w in p for w in PROC_SUBSTR) or any(r in p for r in REGION_WORDS if len(r) >= 3):
            continue
        toks = p.split()
        if any(w in toks for w in REGION_WORDS) or toks[0] in GENERIC_WORDS or toks[-1] in GENERIC_WORDS:
            continue
        if any(t in PROC_WORDS or t in names or TITLE_TOKEN.search(t) or t.endswith("다") or t.endswith("니까")
               for t in toks):
            continue
        rows.append(dict(label=p, key=p, source="신규키워드", n=df, n_asm=n_asm, first=pd.Timestamp(first), kind="키워드"))
    del stat
    out = pd.DataFrame(rows)
    if len(out) and kiwi is not None and not kiwi_full:
        ok = _kiwi_validate(out.label.tolist(), kiwi)
        out = out[out.label.isin(ok)]
    if len(out):
        out = out.assign(score=out.n * out.n_asm).nlargest(max_terms, "score").drop(columns="score")
    return out


# ------------------------------------------------------------ 병합
def embed(labels, model_name=None):
    if model_name:
        try:
            from sentence_transformers import SentenceTransformer
            m = SentenceTransformer(model_name)
            return m.encode(labels, normalize_embeddings=True, show_progress_bar=False), "sbert"
        except Exception as e:
            print(f"[issues] 임베딩 모델 로드 실패({e}) -> 문자 n-gram TF-IDF로 대체")
    from sklearn.feature_extraction.text import TfidfVectorizer
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3)).fit_transform([nospace(l) for l in labels])
    return X.toarray(), "tfidf"


def filter_keywords(emer):
    """캐시된 신규 키워드 후보에도 최신 일반어 필터를 다시 적용한다."""
    if not len(emer):
        return emer
    keep = [not (set(l.split()) & GENERIC_WORDS) and not any(w in l for w in PROC_SUBSTR) for l in emer.label]
    return emer[keep]


def merge_candidates(cands, model_name=None, thr_sbert=0.15, thr_tfidf=0.30, max_n=3000):
    """핵심어(key) 일치로 1차 병합 후, 임베딩 거리가 아주 가까운 것만 2차 병합(보수적)."""
    cands = cands.copy()
    cands["k"] = cands.key.map(nospace)
    # 신규 키워드가 조례 명칭의 일부이고(예: '딥페이크 성범죄' ⊂ '딥페이크 성범죄 예방 및 피해자 지원'),
    # 일반어를 포함하지 않으면 같은 이슈로 본다. 조례 쪽 핵심어를 키워드로 맞춰 1차 병합에 태운다.
    # 신규 키워드끼리도 짧은 쪽이 긴 쪽에 포함되면 병합 (예: '영유아 학교' ⊂ '영유아학교 시범사업')
    kw_idx = [i for i, src in enumerate(cands.source) if src != "조례"]
    for i in sorted(kw_idx, key=lambda i: len(cands.k.iloc[i])):
        for j in kw_idx:
            ki, kj = cands.k.iloc[i], cands.k.iloc[j]
            if i != j and len(ki) >= 5 and len(kj) > len(ki) and ki in kj:
                cands.iloc[j, cands.columns.get_loc("k")] = ki
    ord_full = [(nospace(l), k) for l, k, src in zip(cands.label, cands.k, cands.source) if src == "조례"]
    for i, (lab, src) in enumerate(zip(cands.label, cands.source)):
        kk = nospace(lab)
        if src != "조례" and len(kk) >= 5 and not (set(lab.split()) & GENERIC_WORDS):
            hosts = [ok for full, ok in ord_full if kk in full]
            if len(set(hosts)) == 1:
                cands.iloc[i, cands.columns.get_loc("k")] = hosts[0]
    g = (cands.sort_values("n", ascending=False)
         .groupby("k").agg(label=("label", "first"), labels=("label", list), source=("source", lambda s: sorted(set(s))),
                           kind=("kind", "first"), n=("n", "sum"), n_asm=("n_asm", "max"), first=("first", "min"))
         .reset_index())
    g = g.nlargest(max_n, "n").reset_index(drop=True)
    if len(g) > 1:
        from sklearn.cluster import AgglomerativeClustering
        X, kind = embed(g.label.tolist(), model_name)
        thr = thr_sbert if kind == "sbert" else thr_tfidf
        cl = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=thr).fit_predict(X)
    else:
        cl = np.zeros(len(g), dtype=int)
    g["cluster"] = cl
    issues = []
    for cid, grp in g.sort_values("n", ascending=False).groupby("cluster", sort=False):
        # 조례 핵심어(예: '도시계획', '동물보호')가 너무 짧으면 일반 문장까지 잡히므로 5자 이상일 때만 매칭에 쓴다
        surfaces = sorted({k for k in grp.k if len(k) >= 5} | {nospace(l) for ls in grp.labels for l in ls},
                          key=len, reverse=True)
        surfaces = [s for s in surfaces if len(s) >= 4]
        issues.append(dict(label=grp.label.iloc[0], variants=sorted({l for ls in grp.labels for l in ls}),
                           surfaces=surfaces, source=sorted({s for ss in grp.source for s in ss}),
                           kind=grp.kind.iloc[0]))
    out = pd.DataFrame(issues)
    out.insert(0, "issue_id", range(len(out)))
    return out


# ------------------------------------------------------------ 언급 색인
def _orig_span(text, ns_start, ns_end):
    """nospace 인덱스 -> 원문 인덱스."""
    idx = [i for i, ch in enumerate(text) if not SEP.match(ch)]
    if not idx:
        return 0, 0
    return idx[min(ns_start, len(idx) - 1)], idx[min(ns_end - 1, len(idx) - 1)] + 1


def _window(text, a, b, w):
    s, e = max(0, a - w), min(len(text), b + w)
    return ("…" if s > 0 else "") + text[s:e].strip() + ("…" if e < len(text) else "")


def index_mentions(utts, issues, snippet_w=110, context_w=320, per_doc_cap=3):
    surf2ids = defaultdict(list)
    for iid, surfs in zip(issues.issue_id, issues.surfaces):
        for s in surfs:
            surf2ids[s].append(iid)
    if not surf2ids:
        return pd.DataFrame()
    try:  # Aho-Corasick: 수천 개 표면형을 한 번에 탐색 (정규식 대비 수십 배 빠름)
        import ahocorasick
        A = ahocorasick.Automaton()
        for sf in surf2ids:
            A.add_word(sf, sf)
        A.make_automaton()

        def find(ns):
            for end, sf in A.iter(ns):
                yield end - len(sf) + 1, end + 1, sf
    except ImportError:
        rx = re.compile("|".join(map(re.escape, sorted(surf2ids, key=len, reverse=True))))

        def find(ns):
            for m in rx.finditer(ns):
                yield m.start(), m.end(), m.group(0)
    rows, per_doc = [], Counter()
    for r in utts.itertuples(index=False):
        ns = nospace(r.text)
        hit = {}
        for a, b, sf in find(ns):
            for iid in surf2ids[sf]:
                hit.setdefault(iid, (a, b))
        for iid, (a, b) in hit.items():
            if per_doc[(iid, r.doc_id)] >= per_doc_cap:
                continue
            per_doc[(iid, r.doc_id)] += 1
            oa, ob = _orig_span(r.text, a, b)
            mname = r.minutes_name if (not r.committee or r.committee in str(r.minutes_name)) \
                else f"{r.minutes_name} - {r.committee}"   # '기타 회의록 제334회'처럼 회의명이 빠진 경우 보완
            rows.append(dict(issue_id=iid, utt_id=r.utt_id, doc_id=r.doc_id, assembly=r.assembly, date=r.date,
                             minutes_name=mname, committee=r.committee, speaker=r.speaker,
                             matched=r.text[oa:ob], snippet=_window(r.text, oa, ob, snippet_w),
                             context=_window(r.text, oa, ob, context_w)))
    return pd.DataFrame(rows).sort_values(["issue_id", "date", "doc_id", "utt_id"]).reset_index(drop=True)


def drop_fragment_surfaces(issues):
    """대표 명칭의 단어 중간에서 시작하는 조각 표현을 매칭 표현에서 뺀다.
    예: '산업위기 선제대응지역'의 '위기선제'는 '기후위기 선제적 대응'에도 걸리므로 제거한다.
    대표 명칭의 단어 경계에서 시작하는 표현(예: '현수막사용')은 유지한다."""
    issues = issues.copy()
    n = 0
    for k in issues.index:
        label = issues.at[k, "label"]
        flat = label.replace(" ", "")
        starts, pos = set(), 0
        for w in label.split():
            starts.add(pos); pos += len(w)
        keep = []
        for sf in issues.at[k, "surfaces"]:
            i = flat.find(sf)
            if i > 0 and i not in starts:
                n += 1
                continue
            keep.append(sf)
        if keep:
            issues.at[k, "surfaces"] = keep
    return issues, n


def apply_manual_merges(issues, path):
    """config/merge_issues.txt 의 '대표명: 표현, 표현' 규칙으로 이슈를 합친다."""
    import os
    if not path or not os.path.exists(path):
        return issues, 0
    rules = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        head, rest = line.split(":", 1)
        rules.append((head.strip(), [head.strip()] + [x.strip() for x in rest.split(",") if x.strip()]))
    issues = issues.copy()
    drop, n = set(), 0
    for head, names in rules:
        idx = issues.index[issues.label.isin(names)].tolist()
        if len(idx) < 1:
            continue
        keep, others = idx[0], idx[1:]
        issues.at[keep, "label"] = head
        issues.at[keep, "variants"] = sorted({v for i in idx for v in issues.at[i, "variants"]} | set(names) - {head})
        issues.at[keep, "surfaces"] = sorted({sf for i in idx for sf in issues.at[i, "surfaces"]}, key=len, reverse=True)
        issues.at[keep, "source"] = sorted({x for i in idx for x in issues.at[i, "source"]})
        drop.update(others)
        n += len(others)
    issues = issues.drop(index=list(drop)).reset_index(drop=True)
    issues["issue_id"] = range(len(issues))
    return issues, n
