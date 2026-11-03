#!/bin/bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "[오류] python3를 찾을 수 없습니다. Python 3.10 이상을 설치한 뒤 다시 실행하세요."; exit 1; }
mkdir -p data
N=$(find data -type f \( -name "*.json" -o -name "*.json.gz" -o -name "*.jsonl" \) | wc -l | tr -d ' ')
[ "$N" -gt 0 ] || { echo "[오류] data 폴더에 회의록 파일이 없습니다. 아래 폴더에 회의록 JSON을 넣은 뒤 다시 실행하세요."; echo "$(pwd)/data"; open data; exit 1; }
echo "회의록 파일 ${N}개를 찾았습니다."

echo "[1/4] 라이브러리 설치 중..."
python3 -m pip install --upgrade pip > install_log.txt 2>&1
python3 -m pip install -r requirements.txt >> install_log.txt 2>&1 || { echo "[오류] 필수 라이브러리 설치에 실패했습니다. 기록의 마지막 부분:"; tail -25 install_log.txt; echo "Python $(python3 -V) — 3.12 또는 3.13이 아니면 3.13을 설치한 뒤 다시 실행하세요. install_log.txt를 보내 주시면 원인을 확인할 수 있습니다."; exit 1; }
python3 -m pip install -r requirements-optional.txt >> install_log.txt 2>&1 || echo "[안내] 선택 라이브러리 일부를 설치하지 못했습니다. 분석 결과는 같고 속도만 느려질 수 있습니다."

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
