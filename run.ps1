# 啟動「誰是 AI？」伺服器。第一次執行會自動建立虛擬環境。
# 用法：.\run.ps1            區網
#       .\run.ps1 --tunnel   加開 cloudflared 公開隧道
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $PSScriptRoot

$venv = Join-Path $env:LOCALAPPDATA 'aiwolf-venv'
$py = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $py)) { uv venv --python 3.12 $venv }
& $py -c "import fastapi, anthropic, openai, opencc, qrcode" 2>$null
if ($LASTEXITCODE -ne 0) { uv pip install --python $py -r requirements.txt }

& $py run.py @args
