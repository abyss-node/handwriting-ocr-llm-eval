# Probes Gemini 3.1 Pro quota; if the key has quota (requires billing enabled on the
# AI Studio key - free tier limit is 0), runs the full 5-doc parse sweep.
# Run manually: powershell -File run-pro.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
$log = Join-Path $root "pro-probe.log"

"[{0}] probing gemini-3.1-pro-preview quota" -f (Get-Date -Format s) | Add-Content $log

$probe = @"
import os, sys, requests
from dotenv import load_dotenv
load_dotenv(os.path.join(r'$root', '.env'))
r = requests.post(
    'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent',
    headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']},
    json={'contents': [{'parts': [{'text': 'Reply with exactly: OK'}]}]}, timeout=120)
sys.exit(0 if r.status_code == 200 else 1)
"@
$probeFile = Join-Path $env:TEMP "gemini_pro_probe.py"
Set-Content -Path $probeFile -Value $probe -Encoding utf8

& $py $probeFile
if ($LASTEXITCODE -ne 0) {
    "[{0}] no quota yet (probe failed)" -f (Get-Date -Format s) | Add-Content $log
    exit 0
}

"[{0}] QUOTA AVAILABLE - running full Pro sweep" -f (Get-Date -Format s) | Add-Content $log
$env:GEMINI_MODEL = 'gemini-3.1-pro-preview'
Set-Location $root
& $py compare.py docs\Doc1.pdf docs\Doc2.pdf docs\Doc3.pdf docs\Doc4.pdf docs\Doc5.pdf `
    --skip-lit --skip-llama --gemini 2>&1 | Add-Content $log
"[{0}] sweep finished - see results\<doc>\gemini-3.1-pro-preview.md" -f (Get-Date -Format s) | Add-Content $log
