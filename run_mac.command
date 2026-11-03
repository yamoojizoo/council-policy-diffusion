#!/bin/bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "[오류] python3를 찾을 수 없습니다. Python 3.10 이상을 설치한 뒤 다시 실행하세요."; exit 1; }
[ -d data ] || { echo "[오류] data 폴더가 없습니다. 회의록 JSON을 data 폴더에 넣은 뒤 다시 실행하세요."; exit 1; }

echo "[1/4] 라이브러리 설치 중..."
python3 -m pip install -r requirements.txt || { echo "[오류] 라이브러리 설치에 실패했습니다. 인터넷 연결을 확인하세요."; exit 1; }

echo "[2/4] 지난 시점 분석 (2025-09-30까지, 사후 검증용, 약 15분)..."
if python3 run_pipeline.py --data_dir data --out_dir output_prev --until 2025-09-30; then
  PREV="--prev_out output_prev"
else
  echo "[경고] 지난 시점 분석에 실패해 사후 검증 없이 최종 분석만 진행합니다."; PREV=""
fi

echo "[3/4] 최종 분석 (전체 기간, 약 15분)..."
python3 run_pipeline.py --data_dir data --out_dir output $PREV || { echo "[오류] 분석 중 문제가 생겼습니다. 위 메시지를 확인하세요."; exit 1; }

echo "[4/4] 대시보드 열기"
open output/dashboard.html
