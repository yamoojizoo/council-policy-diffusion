@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (echo [오류] Python을 찾을 수 없습니다. python.org에서 Python 3.10 이상을 설치한 뒤 다시 실행하세요. & pause & exit /b 1)
echo "%CD%" | find /i "\Temp\" >nul && (echo [오류] 압축을 풀지 않고 ZIP 안에서 바로 실행했습니다. ZIP 파일을 우클릭해 '압축 풀기'를 한 뒤, 풀린 폴더 안의 run_windows.bat을 실행하세요. & pause & exit /b 1)
if not exist run_pipeline.py (echo [오류] run_pipeline.py가 같은 폴더에 없습니다. 압축을 푼 폴더 안의 run_windows.bat을 실행하세요. & echo 지금 위치: %CD% & pause & exit /b 1)
if not exist data mkdir data
dir /s /b data\*.json data\*.json.gz data\*.jsonl 2>nul | find /c /v "" > "%TEMP%\cd_n.txt"
set /p NJSON=<"%TEMP%\cd_n.txt"
if "%NJSON%"=="0" (echo [오류] data 폴더에 회의록 파일이 없습니다. & echo 회의록 JSON을 아래 폴더에 넣은 뒤 다시 실행하세요. & echo %CD%\data & start "" "%CD%\data" & pause & exit /b 1)
echo 회의록 파일 %NJSON%개를 찾았습니다.

echo [1/4] 라이브러리 설치 중...
python -m pip install -r requirements.txt || (echo [오류] 라이브러리 설치에 실패했습니다. 인터넷 연결을 확인하세요. & pause & exit /b 1)

echo [2/4] 지난 시점 분석 (2025-09-30까지, 사후 검증용, 약 15분)...
python run_pipeline.py --data_dir data --out_dir output_prev --until 2025-09-30
if errorlevel 1 (
  echo [경고] 지난 시점 분석에 실패해 사후 검증 없이 최종 분석만 진행합니다.
  set PREV=
) else (
  set PREV=--prev_out output_prev
)

echo [3/4] 최종 분석 (전체 기간, 약 15분)...
python run_pipeline.py --data_dir data --out_dir output %PREV% || (echo [오류] 분석 중 문제가 생겼습니다. 위 메시지를 확인하세요. & pause & exit /b 1)

echo [4/4] 대시보드 열기
start "" "output\dashboard.html"
pause
