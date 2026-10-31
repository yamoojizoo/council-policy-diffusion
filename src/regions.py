"""광역 지방의회 메타데이터: 정규화 코드, 지명 별칭, 인접 관계.

인접 관계는 행정구역 경계 기준으로 작성자가 직접 구성한 보조 정보(외부 지식)이며,
기술문서에 '외부 자료'로 명시한다.
"""
import re

REGIONS = {
    "서울": dict(full=["서울특별시"], alias=["서울특별시", "서울시"], nbr=["경기", "인천"]),
    "부산": dict(full=["부산광역시"], alias=["부산광역시", "부산시"], nbr=["경남", "울산"]),
    "대구": dict(full=["대구광역시"], alias=["대구광역시", "대구시"], nbr=["경북", "경남"]),
    "인천": dict(full=["인천광역시"], alias=["인천광역시", "인천시"], nbr=["서울", "경기"]),
    "광주": dict(full=["광주광역시"], alias=["광주광역시", "광주시"], nbr=["전남"]),
    "대전": dict(full=["대전광역시"], alias=["대전광역시", "대전시"], nbr=["세종", "충북", "충남"]),
    "울산": dict(full=["울산광역시"], alias=["울산광역시", "울산시"], nbr=["부산", "경북", "경남"]),
    "세종": dict(full=["세종특별자치시"], alias=["세종특별자치시", "세종시"], nbr=["대전", "충북", "충남"]),
    "경기": dict(full=["경기도"], alias=["경기도"], nbr=["서울", "인천", "강원", "충북", "충남"]),
    "강원": dict(full=["강원특별자치도", "강원도"], alias=["강원특별자치도", "강원도"], nbr=["경기", "충북", "경북"]),
    "충북": dict(full=["충청북도"], alias=["충청북도", "충북"], nbr=["경기", "강원", "경북", "대전", "세종", "충남", "전북"]),
    "충남": dict(full=["충청남도"], alias=["충청남도", "충남"], nbr=["경기", "충북", "세종", "대전", "전북"]),
    "전북": dict(full=["전북특별자치도", "전라북도"], alias=["전북특별자치도", "전라북도", "전북"], nbr=["충남", "충북", "경북", "경남", "전남"]),
    "전남": dict(full=["전라남도"], alias=["전라남도", "전남"], nbr=["전북", "광주", "경남"]),
    "경북": dict(full=["경상북도"], alias=["경상북도", "경북"], nbr=["강원", "충북", "전북", "경남", "대구", "울산"]),
    "경남": dict(full=["경상남도"], alias=["경상남도", "경남"], nbr=["부산", "울산", "대구", "경북", "전북", "전남"]),
    "제주": dict(full=["제주특별자치도"], alias=["제주특별자치도", "제주도"], nbr=[]),
}

ASSEMBLY_NAME = {k: v["full"][0] + "의회" for k, v in REGIONS.items()}

_ALL_FULL = sorted({n for v in REGIONS.values() for n in v["full"]}, key=len, reverse=True)
REGION_FULL_ALT = "|".join(map(re.escape, _ALL_FULL))
PREFIX_RE = re.compile(r"^\s*(?:%s)(?:교육청)?\s*" % REGION_FULL_ALT)

ALIAS_RE = {k: re.compile("|".join(map(re.escape, sorted(v["alias"], key=len, reverse=True))))
            for k, v in REGIONS.items()}


def canon_assembly(raw: str) -> str:
    """RASMBLY_NM(예: '경기도의회', '강원도의회') -> 정규화 코드('경기')."""
    raw = (raw or "").replace(" ", "")
    best, best_len = None, 0
    for code, v in REGIONS.items():
        for n in v["full"] + v["alias"] + [code]:
            if n in raw and len(n) > best_len:
                best, best_len = code, len(n)
    return best or raw


def neighbors(code: str):
    return REGIONS.get(code, {}).get("nbr", [])
