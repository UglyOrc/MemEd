@echo off
:: Run MemEd — requests Administrator privileges automatically
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath 'python' -ArgumentList '\"%~dp0main.py\"' -Verb RunAs"
) else (
    python "%~dp0main.py"
)
