@echo off
setlocal
set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%.env" copy "%PROJECT_DIR%.env.example" "%PROJECT_DIR%.env" >nul
echo Starting the FastAPI backend and Streamlit frontend in separate windows...
echo Ensure dependencies are installed and Ollama is running with qwen2.5:3b.
if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    start "Repository Explainer API" /D "%PROJECT_DIR%" cmd /k ""%PROJECT_DIR%.venv\Scripts\python.exe" -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"
    start "Repository Explainer UI" /D "%PROJECT_DIR%" cmd /k ""%PROJECT_DIR%.venv\Scripts\python.exe" -m streamlit run frontend\app.py"
) else (
    start "Repository Explainer API" /D "%PROJECT_DIR%" cmd /k "python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"
    start "Repository Explainer UI" /D "%PROJECT_DIR%" cmd /k "python -m streamlit run frontend\app.py"
)
endlocal
