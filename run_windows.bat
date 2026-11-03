@echo off
chcp 65001 >nul
cd /d "%~dp0"
set LOG=%~dp0install_log.txt

echo "%CD%" | find /i "\Temp\" >nul && (echo [오류] 압축을 풀지 않고 ZIP 안에서 바로 실행했습니다. ZIP 파일을 우클릭해 '압축 풀기'를 한 뒤, 풀린 폴더 안의 run_windows.bat을 실행하세요. & pause & exit /b 1)
if not exist run_pipeline.py (echo [오류] run_pipeline.py가 같은 폴더에 없습니다. 압축을 푼 폴더 안의 run_windows.bat을 실행하세요. & echo 지금 위치: %CD% & pause & exit /b 1)

rem ---- Python 찾기: py 실행기에 '설치되어 있다고 나오는' 버전만 시도한다
rem      (없는 버전을 부르면 새 설치 관리자가 설치 여부를 묻느라 멈출 수 있음). 모든 라이브러리 설치 파일이 있는 3.14 우선
set PY=
for %%V in (3.14 3.13 3.12 3.11 3.10) do if not defined PY (py -0 2>nul | findstr /c:"-V:%%V" >nul && py -%%V -c "import sys" >nul 2>nul && set PY=py -%%V)
if not defined PY (python -c "import sys" >nul 2>nul && set PY=python)
if not defined PY (
  echo [오류] 실행할 수 있는 Python을 찾지 못했습니다.
  echo  - python.org/downloads 에서 Python 3.13 을 내려받아 설치하세요.
  echo  - 설치 첫 화면에서 'Add python.exe to PATH' 를 체크하세요.
  echo  - 'python' 을 입력했을 때 Microsoft Store 가 열리는 것은 진짜 Python 이 아닙니다.
  pause & exit /b 1)
for /f "delims=" %%i in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set PYV=%%i
echo 사용할 Python: %PY% (버전 %PYV%)

if not exist data mkdir data
dir /s /b data\*.json data\*.json.gz data\*.jsonl 2>nul | find /c /v "" > "%TEMP%\cd_n.txt"
set /p NJSON=<"%TEMP%\cd_n.txt"
if "%NJSON%"=="0" (echo [오류] data 폴더에 회의록 파일이 없습니다. & echo 회의록 JSON을 아래 폴더에 넣은 뒤 다시 실행하세요. & echo %CD%\data & start "" "%CD%\data" & pause & exit /b 1)
echo 회의록 파일 %NJSON%개를 찾았습니다.

echo [1/4] 라이브러리 설치 중... (자세한 기록: install_log.txt)
%PY% -m pip install --upgrade pip > "%LOG%" 2>&1
%PY% -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [오류] 필수 라이브러리 설치에 실패했습니다. 아래는 기록의 마지막 부분입니다.
  echo ------------------------------------------------------------
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 '%LOG%' -Tail 25"
  echo ------------------------------------------------------------
  echo  - Python 버전이 %PYV% 입니다. 3.12 또는 3.13 이 아니면 3.13 을 설치한 뒤 다시 실행하세요.
  echo  - 회사·학교 네트워크라면 휴대폰 핫스팟으로 다시 시도하세요.
  echo  - install_log.txt 파일을 그대로 보내 주시면 원인을 확인할 수 있습니다.
  pause & exit /b 1)
%PY% -m pip install -r requirements-optional.txt >> "%LOG%" 2>&1 || echo [안내] 선택 라이브러리 일부를 설치하지 못했습니다. 분석 결과는 같고 속도만 느려질 수 있습니다.

echo [2/4] 지난 시점 분석 (2025-09-30까지, 사후 검증용, 약 15분)...
%PY% run_pipeline.py --data_dir data --out_dir output_prev --until 2025-09-30
if errorlevel 1 (
  echo [경고] 지난 시점 분석에 실패해 사후 검증 없이 최종 분석만 진행합니다.
  set PREV=
) else (
  set PREV=--prev_out output_prev
)

echo [3/4] 최종 분석 (전체 기간, 약 15분)...
%PY% run_pipeline.py --data_dir data --out_dir output %PREV%
if errorlevel 1 (echo [오류] 분석 중 문제가 생겼습니다. 위 메시지를 확인하세요. & pause & exit /b 1)

echo [4/4] 대시보드 열기
start "" "output\dashboard.html"
pause
