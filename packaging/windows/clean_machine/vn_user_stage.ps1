# Runs as the Windows account "Nguyễn Văn Thử" (profile folder with Vietnamese letters): default per-user install,
# real OCR from the installed app, open/close, uninstall. Results: C:\Users\Public\vdqa\vn_out\result.json
. C:\Users\Public\vdqa\vdqa_common.ps1
$ErrorActionPreference = 'Continue'
$pub = 'C:\Users\Public\vdqa'; $Out = Join-Path $pub 'vn_out'
New-Item -ItemType Directory -Force $Out | Out-Null
$R = [ordered]@{ user = $env:USERNAME; profile = $env:USERPROFILE; localappdata = $env:LOCALAPPDATA }
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\VietDoc OCR'
$setup = (Get-ChildItem $pub -Filter '*-Setup.exe' | Select-Object -First 1).FullName
try {
  $t = Measure-Command { Start-Process -FilePath $setup -ArgumentList '/S' -Wait }
  $R.install = [ordered]@{ seconds = [math]::Round($t.TotalSeconds, 1); facts = Get-InstallFacts $installDir }
} catch { $R.install = $_.Exception.Message }
Save-Json $R (Join-Path $Out 'result.json')
try {
  $docs = Get-Content (Join-Path $pub 'sandbox_docs.txt') | Where-Object { $_ -like '383_p1_200dpi.png=*' -or $_ -like '9624*' -or $_ -like '10333*' }
  $R.ocr = Invoke-OcrSet (Join-Path $installDir 'resources') (Join-Path $pub 'inputs') $docs $Out 'vn_user'
} catch { $R.ocr = $_.Exception.Message }
Save-Json $R (Join-Path $Out 'result.json')
try { $R.lifecycle = Test-Lifecycle (Join-Path $installDir 'VietDoc OCR.exe') } catch { $R.lifecycle = $_.Exception.Message }
$R.appdata = Test-Path (Join-Path $env:APPDATA 'VietDoc OCR')
try {
  Start-Process -FilePath (Join-Path $installDir 'Uninstall VietDoc OCR.exe') -ArgumentList '/S' -Wait
  for ($i = 0; $i -lt 120 -and (Test-Path -LiteralPath (Join-Path $installDir 'VietDoc OCR.exe')); $i++) { Start-Sleep -Milliseconds 500 }
  $R.uninstall = Get-InstallFacts $installDir
} catch { $R.uninstall = $_.Exception.Message }
Save-Json $R (Join-Path $Out 'result.json')
