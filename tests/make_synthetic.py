"""스모크 테스트용 가짜 회의록 생성기 (실제 데이터 아님).

주최 측 스키마(RASMBLY_NM/MTGNM/MINTS_NM/MTG_DE/MINTS_HTML)를 흉내 내고,
확산 패턴이 알려진 이슈를 심어 파이프라인이 이를 복원하는지 확인한다.
"""
import json
import os
import random
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.regions import REGIONS, ASSEMBLY_NAME  # noqa: E402

random.seed(7)
OUT = sys.argv[1] if len(sys.argv) > 1 else "data_synth"
os.makedirs(OUT, exist_ok=True)

FILLER = [
    "성원이 되었으므로 회의를 개의하겠습니다.", "다음은 소관 부서의 업무보고를 듣도록 하겠습니다.",
    "도로 정비 사업의 추진 현황에 대해 질의하겠습니다.", "예산 집행률이 저조한 사유가 무엇입니까.",
    "관련 부서와 협의하여 조속히 검토하겠습니다.", "주민 불편이 없도록 철저히 관리해 주시기 바랍니다.",
    "하천 정비와 관련하여 추가 자료를 요청드립니다.", "공공청사 리모델링 계획을 보고드리겠습니다.",
    "버스 노선 개편에 따른 민원이 증가하고 있습니다.", "학교 시설 개선 예산을 확보하겠습니다.",
]
COMMITTEES = ["본회의", "기획경제위원회", "보건복지위원회", "교육위원회", "도시환경위원회"]

# (이슈 핵심어, 조례명 core, [(의회, 'YYYY-MM', 발언 템플릿)])
PLANTED = [
    ("고립·은둔청년", "고립·은둔청년 지원에 관한", [
        ("서울", "2023-03", "고립·은둔청년 지원 조례안은 사회적 관계가 단절된 청년을 발굴하기 위한 것입니다."),
        ("경기", "2023-08", "서울특별시 사례를 참고하여 우리 도에서도 고립·은둔청년 지원 조례를 제정할 필요가 있습니다."),
        ("인천", "2023-11", "타 시도에서 이미 고립·은둔청년 지원 사업을 시행하고 있는데 우리 시는 계획이 있습니까."),
        ("부산", "2024-03", "고립·은둔청년 실태조사 결과를 보고드리겠습니다."),
        ("대전", "2024-06", "경기도에서 이미 고립·은둔청년 지원 조례를 시행하고 있어 벤치마킹이 필요합니다."),
        ("충남", "2024-09", "고립·은둔청년 문제에 대해 도의 대책을 묻겠습니다."),
    ]),
    ("딥페이크 성범죄", "딥페이크 성범죄 예방 및 피해자 지원에 관한", [
        ("서울", "2024-09", "성폭력처벌법 개정 이후 딥페이크 성범죄 예방 교육을 확대해야 합니다."),
        ("경기", "2024-09", "교육부 지침에 따라 딥페이크 성범죄 대응 매뉴얼을 마련하고 있습니다."),
        ("부산", "2024-10", "딥페이크 성범죄 피해 학생 지원 방안을 묻겠습니다. 법 개정에 맞춰 대응하겠습니다."),
        ("대구", "2024-10", "딥페이크 성범죄 예방을 위한 조례 제정이 시급합니다."),
        ("광주", "2024-11", "딥페이크 성범죄 피해 지원 예산을 확보하겠습니다. 상위법 취지를 반영하겠습니다."),
    ]),
    ("통합 정기권", "대중교통 통합 정기권 도입 및 운영에 관한", [
        ("서울", "2024-01", "통합 정기권 시범사업으로 시민 교통비 부담이 줄었습니다."),
        ("경기", "2024-05", "서울시처럼 통합 정기권을 도입해 도민 교통비를 줄여야 합니다."),
        ("인천", "2024-06", "인천광역시도 통합 정기권 참여 여부를 결정해야 합니다. 경기도 사례를 보면 참여가 필요합니다."),
    ]),
    ("반려식물", "반려식물 보급 및 지원에 관한", [
        ("제주", "2023-05", "반려식물 보급 사업이 정서 지원에 효과가 있습니다."),
        ("전남", "2024-02", "반려식물 지원 조례를 통해 어르신 우울감을 낮출 수 있습니다."),
        ("경남", "2024-11", "반려식물 보급 사업 예산을 확대해야 합니다."),
    ]),
]

months = pd.period_range("2023-01", "2025-12", freq="M")
plant = {}
for key, core, evs in PLANTED:
    for asm, ym, sent in evs:
        plant.setdefault((asm, ym), []).append((key, core, sent))

for code in REGIONS:
    full = REGIONS[code]["full"][0]
    recs, session = [], 300
    for ym in months:
        session += 1
        events = plant.get((code, str(ym)), [])
        # 최초 관측 이후에도 후속 언급이 이어지도록
        for key, core, evs in PLANTED:
            first = next((e for e in evs if e[0] == code), None)
            if first and str(ym) > first[1] and random.random() < 0.35:
                events = events + [(key, core, f"{key} 관련 후속 추진 상황을 점검하겠습니다.")]
        for c_i, com in enumerate(random.sample(COMMITTEES, 3)):
            day = random.randint(2, 27)
            body = [f"<div id='anH'><p>제{session}회 {ASSEMBLY_NAME[code]} {com}</p></div>"]
            body.append(f"<p>○위원장 김철수 의사일정 제1항 {full} 행정기구 설치 조례 일부개정조례안을 상정합니다.</p>")
            for _ in range(random.randint(4, 8)):
                body.append(f"<p>○{random.choice(['이영희 위원', '박민수 위원', '기획조정실장 최정훈'])} "
                            f"{random.choice(FILLER)} {random.choice(FILLER)}</p>")
            if c_i == 0:
                for key, core, sent in events:
                    body.append(f"<p>○위원장 김철수 다음은 {full} {core} 조례안을 상정합니다.</p>")
                    body.append(f"<p>○정다은 위원 {sent}</p><p>{random.choice(FILLER)}</p>")
            recs.append(dict(RASMBLY_NM=ASSEMBLY_NAME[code], MTGNM=com,
                             MINTS_NM=f"{com} 회의록 제{session}회({c_i + 1}차)",
                             MTG_DE=f"{ym.year}{ym.month:02d}{day:02d}", MINTS_HTML="".join(body)))
    with open(os.path.join(OUT, f"{ASSEMBLY_NAME[code]}.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False)
print(f"synthetic data -> {OUT}")
