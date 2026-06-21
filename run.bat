@echo off
:: Run MemEd as Administrator (required for process memory access)
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath 'python' -ArgumentList '\"%~dp0app.py\"' -Verb RunAs"
) else (
    python "%~dp0app.py"
)
