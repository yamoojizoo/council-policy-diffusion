@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] 라이브러리 설치 중...
python -m pip install -r requirements.txt
echo [2/3] 분석 실행 중 (15~30분)...
python run_pipeline.py --data_dir data --out_dir output
echo [3/3] 대시보드 열기
start "" "output\dashboard.html"
pause
