@echo off
rem 창이 바로 닫히지 않도록, 더블클릭하면 자신을 cmd /k 로 다시 연다 (오류가 나도 창이 남음)
if not "%~1"=="__run" (
  cmd /k ""%~f0" __run"
  exit /b
)
chcp 65001 >nul
cd /d "%~dp0"

rem 주의: 폴더 이름에 괄호가 들어갈 수 있으므로(예: ...-main (1)) 경로는 괄호 블록 안에서 쓰지 않는다
echo "%CD%" | find /i "\Temp" >nul
if not errorlevel 1 goto :err_zip
if not exist "run_pipeline.py" goto :err_place

rem ---- Python 찾기: py 실행기에 설치되어 있다고 나오는 버전만 시도, 3.14 우선
set "PY="
for %%V in (3.14 3.13 3.12 3.11 3.10) do call :try_py %%V
if not defined PY call :try_python
if not defined PY goto :err_python
"%PYEXE%" -c "import sys;print(sys.version.split()[0])" > "%TEMP%\cd_pyv.txt" 2>nul
set /p PYV=<"%TEMP%\cd_pyv.txt"
echo 사용할 Python: %PY%  [버전 %PYV%]

if not exist "data" mkdir "data"
dir /s /b "data\*.json" "data\*.json.gz" "data\*.jsonl" 2>nul | find /c /v "" > "%TEMP%\cd_n.txt"
set /p NJSON=<"%TEMP%\cd_n.txt"
if "%NJSON%"=="0" goto :err_data
echo 회의록 파일 %NJSON%개를 찾았습니다.

echo [1/4] 라이브러리 설치 중... 처음에는 몇 분 걸립니다. 자세한 기록: install_log.txt
"%PYEXE%" -m pip install --upgrade pip > "install_log.txt" 2>&1
"%PYEXE%" -m pip install -r requirements.txt >> "install_log.txt" 2>&1
if errorlevel 1 goto :err_pip
"%PYEXE%" -m pip install -r requirements-optional.txt >> "install_log.txt" 2>&1
if errorlevel 1 echo [안내] 선택 라이브러리 일부를 설치하지 못했습니다. 결과는 같고 속도만 느려질 수 있습니다.

echo [2/4] 지난 시점 분석: 2025-09-30까지, 사후 검증용, 약 15분...
set "PREV=--prev_out output_prev"
"%PYEXE%" run_pipeline.py --data_dir data --out_dir output_prev --until 2025-09-30
if errorlevel 1 set "PREV="
if not defined PREV echo [경고] 지난 시점 분석에 실패해 사후 검증 없이 최종 분석만 진행합니다.

echo [3/4] 최종 분석: 전체 기간, 약 15분...
"%PYEXE%" run_pipeline.py --data_dir data --out_dir output %PREV%
if errorlevel 1 goto :err_run

echo [4/4] 대시보드 열기
start "" "output\dashboard.html"
echo.
echo 완료했습니다. 이 창은 닫아도 됩니다.
goto :eof

:try_py
if defined PY goto :eof
py -0 2>nul | findstr /c:"-V:%1" >nul
if errorlevel 1 goto :eof
py -%1 -c "import sys;open(r'%TEMP%\cd_pyexe.txt','w').write(sys.executable)" >nul 2>nul
if errorlevel 1 goto :eof
set /p PYEXE=<"%TEMP%\cd_pyexe.txt"
set "PY=py -%1"
goto :eof

:try_python
python -c "import sys;open(r'%TEMP%\cd_pyexe.txt','w').write(sys.executable)" >nul 2>nul
if errorlevel 1 goto :eof
set /p PYEXE=<"%TEMP%\cd_pyexe.txt"
set "PY=python"
goto :eof

:err_zip
echo [오류] 압축을 풀지 않고 ZIP 안에서 바로 실행했습니다.
echo ZIP 파일을 우클릭해 '압축 풀기'를 한 뒤, 풀린 폴더 안의 run_windows.bat을 실행하세요.
goto :eof

:err_place
echo [오류] run_pipeline.py가 같은 폴더에 없습니다. 압축을 푼 폴더 안의 run_windows.bat을 실행하세요.
echo 지금 위치: "%CD%"
goto :eof

:err_python
echo [오류] 실행할 수 있는 Python을 찾지 못했습니다.
echo  - python.org/downloads 에서 Python 3.14 를 설치하세요. 설치 첫 화면에서 Add python.exe to PATH 를 체크하세요.
echo  - python 을 입력했을 때 Microsoft Store 가 열리는 것은 진짜 Python 이 아닙니다.
goto :eof

:err_data
echo [오류] data 폴더에 회의록 파일이 없습니다. 회의록 JSON을 아래 폴더에 넣은 뒤 다시 실행하세요.
echo "%CD%\data"
start "" "%CD%\data"
goto :eof

:err_pip
echo [오류] 필수 라이브러리 설치에 실패했습니다. 아래는 기록의 마지막 부분입니다.
echo ------------------------------------------------------------
powershell -NoProfile -Command "Get-Content -Encoding UTF8 -LiteralPath 'install_log.txt' -Tail 25"
echo ------------------------------------------------------------
echo  - 사용한 Python 버전: %PYV%. 3.12~3.14 가 아니면 3.14 를 설치한 뒤 다시 실행하세요.
echo  - 회사·학교 네트워크라면 휴대폰 핫스팟으로 다시 시도하세요.
echo  - install_log.txt 파일을 보내 주시면 원인을 확인할 수 있습니다.
goto :eof

:err_run
echo [오류] 분석 중 문제가 생겼습니다. 위 메시지를 확인하세요.
goto :eof
