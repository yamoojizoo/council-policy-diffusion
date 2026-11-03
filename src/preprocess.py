"""회의록 JSON -> 발언(utterance) 단위 테이블.

입력 스키마(주최 측 데이터 설명 기준):
  RASMBLY_NM(의회명), MTGNM(회의명), MINTS_NM(회의록명), MTG_DE(회의일자 YYYYMMDD), MINTS_HTML(본문 HTML)
"""
import glob
import hashlib
import gzip
import json
import os
import re

import numpy as np
import pandas as pd

from .regions import canon_assembly

from html import unescape

FIELD = {"RASMBLY_NM": "assembly_raw", "MTGNM": "committee", "MINTS_NM": "minutes_name",
         "MTG_DE": "date", "MINTS_HTML": "html"}

SPEAKER_MARK = re.compile(r"^[○◯〇◎]\s*")
TITLE = re.compile(r"(위원장|부위원장|위원|의원|의장|부의장|교육감|도지사|지사|시장|부시장|부지사|실장|국장|과장|"
                   r"본부장|청장|원장|대표|사장|단장|팀장|처장|소장|교육장|이사장|전문위원|감사관|대변인|비서실장)$")
NAME = re.compile(r"^[가-힣]{2,4}$")
WS = re.compile(r"\s+")


# ---------------------------------------------------------------- loading
def _to_dict(r):
    if isinstance(r, dict):
        return r
    if isinstance(r, list) and len(r) % 2 == 0:  # ["KEY", "VAL", "KEY", "VAL", ...] 형태 방어
        return dict(zip(r[::2], r[1::2]))
    return None


def load_records(path):
    opener = gzip.open if path.endswith(".gz") else open
    try:   # 파일 전체를 문자열로 한 번 더 들고 있지 않도록 바로 파싱한다(메모리 절약)
        with opener(path, "rt", encoding="utf-8-sig") as f:
            obj = json.load(f)
    except json.JSONDecodeError:   # JSON Lines
        with opener(path, "rt", encoding="utf-8-sig") as f:
            obj = [json.loads(line) for line in f if line.strip()]
    if isinstance(obj, dict):
        lists = [v for v in obj.values() if isinstance(v, list)]
        obj = lists[0] if lists else [obj]
    for r in obj:
        r = _to_dict(r)
        if r:
            yield {FIELD.get(str(k).upper(), k): v for k, v in r.items()}


# ---------------------------------------------------------------- html
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_SURR = re.compile("[\ud800-\udfff]")


def html_to_lines(html):
    """태그 경계마다 줄을 나눈다(BeautifulSoup get_text('\\n')와 같은 결과, 약 7배 빠름)."""
    h = _COMMENT.sub("", _SCRIPT.sub("", html or ""))
    h = unescape(_TAG.sub("\n", h))
    lines = (WS.sub(" ", l).strip() for l in h.split("\n"))
    return [l for l in lines if l]


TITLES = (r"(?:위원장직무대리|의장직무대리|위원장|부위원장|위원|의원|의장|부의장|교육감|부교육감|도지사|지사|시장|부시장|부지사|"
          r"[가-힣·]*(?:실장|국장|과장|본부장|청장|원장|대표|사장|단장|팀장|처장|소장|교육장|이사장|전문위원|감사관|대변인|"
          r"담당관|위원장|관장|총장|센터장|부장|차장|원|관))")
NAME_SP = r"[가-힣](?:\s?[가-힣]){1,3}"
LABEL_RES = [
    re.compile(rf"^({TITLES})\s*\(?({NAME_SP})\)?(?:\s*\S{{0,6}})?$"),       # 위원장 이용창 / 위원장 윤 명 희 / 위원장(김정호) 인사
    re.compile(rf"^({NAME_SP})(?:\([가-힣]+\))?\s*(위원장|위원|의원|교육감|도지사|시장)$"),  # 김용임 위원 / 장연국의원
    re.compile(rf"^({TITLES})$"),                                                  # (○)위원장
]
MARKS = re.compile(r"^[○◯〇◎↘]\s*")


def _label(line):
    """줄 전체가 발언자 표시이면 발언자 문자열, 아니면 None."""
    core = MARKS.sub("", line).strip()
    if not core or len(core) > 30 or re.search(r"[.?!,:;「」\d]", core) or "회의록" in core:
        return None
    for i, rx in enumerate(LABEL_RES):
        if i == 2 and not MARKS.match(line):
            continue  # 표식 없는 직함 단독 줄은 오탐 위험이 커서 제외
        m = rx.match(core)
        if m:
            toks = core.split()
            k = len(toks)
            while k > 0 and len(toks[k - 1]) == 1:   # '윤 명 희' -> '윤명희'
                k -= 1
            if len(toks) - k >= 2:
                toks = toks[:k] + ["".join(toks[k:])]
            return " ".join(toks)
    return None


def split_speaker(rest):
    toks = rest.split(" ")
    if len(toks) >= 2:
        a, b = toks[0], toks[1]
        if TITLE.search(a) and NAME.match(b):
            return f"{a} {b}", " ".join(toks[2:])
        if NAME.match(a) and TITLE.search(b):
            return f"{a} {b}", " ".join(toks[2:])
    if toks and TITLE.search(toks[0]) and len(toks[0]) <= 12:
        return toks[0], " ".join(toks[1:])
    return "(미상)", rest


def _merge_split_labels(lines):
    """'○' / '이용욱' / '의원' 처럼 여러 줄로 쪼개진 발언자 표시를 한 줄로 합친다."""
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if MARKS.match(l) and len(MARKS.sub("", l)) <= 12:
            j = i + 1
            while j < len(lines) and j <= i + 2 and re.fullmatch(r"[가-힣]{1,6}", lines[j]):
                l = l + " " + lines[j]
                j += 1
            out.append(l)
            i = j
        else:
            out.append(l)
            i += 1
    return out


def segment(lines):
    """발언자 표시 줄(여러 의회 양식 대응) 또는 '○발언자 내용' 줄로 발언을 나눈다."""
    utts, spk, buf = [], "(회의록 머리말)", []
    for line in _merge_split_labels(lines):
        lab = _label(line)
        if lab is None and SPEAKER_MARK.match(line) and len(line) > 30:
            lab, first = split_speaker(SPEAKER_MARK.sub("", line))
        else:
            first = None
        if lab is not None:
            if buf:
                utts.append((spk, " ".join(buf)))
            spk, buf = lab, ([first] if first else [])
        else:
            buf.append(line)
    if buf:
        utts.append((spk, " ".join(buf)))
    return [(s, t) for s, t in utts if t.strip()]


# ---------------------------------------------------------------- main
def _parse_file(args):
    fp, min_len = args
    out = []
    for r in load_records(fp):
        utts = [(i, spk, text) for i, (spk, text) in enumerate(segment(html_to_lines(r.get("html"))))
                if len(text) >= min_len]  # '예.', '감사합니다.' 같은 짧은 발언 제외
        h = hashlib.md5((r.get("html") or "").encode("utf-8")).hexdigest()
        out.append((r.get("assembly_raw"), r.get("committee"), r.get("minutes_name"), str(r.get("date", "")), utts, h))
    return fp, out


def _avail_gb():
    """사용 가능한 메모리(GB). 알 수 없으면 None."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullAvailPhys / 2**30
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
    except Exception:
        return None


def _n_workers():
    """회의록 파일 하나(최대 약 200MB)를 읽는 데 프로세스당 1.5GB 안팎이 들어, 남은 메모리에 맞춰 병렬 수를 정한다."""
    cpu = os.cpu_count() or 2
    gb = _avail_gb()
    by_mem = 2 if gb is None else int((gb - 3) // 1.5)   # 본 프로세스가 쓸 3GB는 남겨 둔다
    return max(1, min(cpu, 4, by_mem))


def build_tables(data_dir, min_len=15, workers=None):
    files = sorted(sum((glob.glob(os.path.join(data_dir, "**", p), recursive=True)
                        for p in ("*.json", "*.json.gz", "*.jsonl")), []))
    if not files:
        raise FileNotFoundError(f"{data_dir} 아래에 JSON 파일이 없습니다.")
    from multiprocessing import Pool
    workers = workers or _n_workers()
    print(f"  회의록 읽기: 병렬 {workers}개 (사용 가능 메모리 {(_avail_gb() or 0):.1f}GB 기준)", flush=True)
    docs, seen = [], set()
    U = dict(doc_id=[], utt_idx=[], speaker=[], text=[])   # 열별 리스트(행별 dict·tuple보다 메모리가 훨씬 적다)
    with Pool(workers) as pool:
        for fp, recs in pool.imap(_parse_file, [(f, min_len) for f in files]):
            for asm_raw, com, mname, date_s, us, h in recs:
                # 회의록명·일자가 같아도 본문이 다른 별개 회의록(위원회별·차수별)이 많으므로 본문 해시까지 포함해 중복 판정
                key = (asm_raw, mname, date_s, h)
                if key in seen:
                    continue
                seen.add(key)
                doc_id = len(docs)
                docs.append(dict(doc_id=doc_id, assembly=canon_assembly(asm_raw or ""), assembly_raw=asm_raw,
                                 committee=com, minutes_name=mname,
                                 date=pd.to_datetime(date_s[:8], format="%Y%m%d", errors="coerce"),
                                 source_file=_SURR.sub("\ufffd", os.path.basename(fp))))   # 한글 파일명이 깨진 환경 대비
                for i, spk, t in us:
                    U["doc_id"].append(doc_id); U["utt_idx"].append(i); U["speaker"].append(spk); U["text"].append(t)
            print(f"  {os.path.basename(fp)}: 누적 회의록 {len(docs):,}건 / 발언 {len(U["text"]):,}개", flush=True)
    docs = pd.DataFrame(docs)
    # 메모리 절약: 300만 행 표를 merge·정렬로 여러 번 복사하지 않고, 회의록 정보는 doc_id 위치로 붙인 뒤 한 번만 재배열한다.
    # (결과는 merge → dropna → sort_values(date, doc_id, utt_idx)와 같다)
    ids = np.asarray(U.pop("doc_id"), dtype="int64")
    uidx = np.asarray(U.pop("utt_idx"), dtype="int64")
    ddate = docs["date"].to_numpy()
    keep = np.flatnonzero(~pd.isna(ddate[ids]))
    order = keep[np.lexsort((uidx[keep], ids[keep], ddate[ids[keep]].astype("int64")))]
    # 문자열은 정렬된 순서로 한 번만 변환한다(큰 문자열 열을 다시 복사하지 않음)
    cols = {"doc_id": ids[order], "utt_idx": uidx[order]}
    for c in ("speaker", "text"):
        L = U.pop(c)
        cols[c] = pd.Series([L[k] for k in order], dtype="str")
        del L
    u = pd.DataFrame(cols)
    for c in ("assembly", "committee", "minutes_name", "date"):
        u[c] = docs[c].to_numpy()[u["doc_id"].to_numpy()]
    u["date"] = u["date"].astype(docs["date"].dtype)
    u["utt_id"] = u.index
    return docs, u
