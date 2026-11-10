# Clean-machine QA inside Windows Sandbox (networking disabled). Folders mapped by vdqa.wsb:
#   C:\vd\release (read-only: Setup, Portable, SHA256SUMS)  C:\vd\inputs (read-only: QA documents)
#   C:\vd\tools   (read-only: these scripts)                C:\vd\out (writable: results)
# Every stage records its result; a failing stage never hides the others. The sandbox shuts down at the end.
param([switch]$NoShutdown, [string]$Only = '')   # -Only 'a,b': run just those stages
. C:\vd\tools\vdqa_common.ps1
$ErrorActionPreference = 'Continue'
$Out = 'C:\vd\out'; $Rel = 'C:\vd\release'; $In = 'C:\vd\inputs'
New-Item -ItemType Directory -Force $Out | Out-Null
$R = [ordered]@{ started = (Get-Date).ToString('s') }
function Stage([string]$Name, [scriptblock]$Body) {
  if ($Only -and ($Only -split ',') -notcontains $Name) { return }
  Write-Log $Out "stage $Name"
  try { $R[$Name] = & $Body } catch { $R[$Name] = [ordered]@{ error = $_.Exception.Message; at = $_.InvocationInfo.PositionMessage } }
  Save-Json $R (Join-Path $Out 'results.json')
}
$setup = (Get-ChildItem $Rel -Filter '*-Setup.exe' | Select-Object -First 1).FullName
$zip = (Get-ChildItem $Rel -Filter '*-Portable.zip' | Select-Object -First 1).FullName
$docs = Get-Content (Join-Path 'C:\vd\tools' 'sandbox_docs.txt') | Where-Object { $_.Trim() }
$subset = $docs | Where-Object { $_ -like '383_p1_200dpi.png=*' -or $_ -like '9624*metadata_fast' -or $_ -like '10333*native_text' }
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\VietDoc OCR'
$appData = Join-Path $env:APPDATA 'VietDoc OCR'

Stage 'environment' { Get-Environment-Facts }
Stage 'sha256' { Test-Sums $Rel }
Stage 'gui_install' {
  $g = Invoke-GuiInstall $setup $Out $true
  $g.facts = Get-InstallFacts $installDir
  $g
}
Stage 'install_fallback' { if (Test-Path -LiteralPath (Join-Path $installDir 'VietDoc OCR.exe')) { 'not needed: GUI install worked' } else {
  Start-Process -FilePath $setup -ArgumentList '/S' -Wait; [ordered]@{ silent_install_used = $true; facts = Get-InstallFacts $installDir } } }
Stage 'lifecycle_installed_1' { Test-Lifecycle (Join-Path $installDir 'VietDoc OCR.exe') }
Stage 'default_appdata' { [ordered]@{ path = $appData; exists = (Test-Path $appData)
                                       entries = [string[]]@(Get-ChildItem -LiteralPath $appData -Name -ErrorAction SilentlyContinue) } }
Stage 'lifecycle_installed_2_restart' { Test-Lifecycle (Join-Path $installDir 'VietDoc OCR.exe') }
Stage 'ocr_installed' { Invoke-OcrSet (Join-Path $installDir 'resources') $In $docs $Out 'installed' }
Stage 'upgrade_silent_reinstall' {
  New-Item -ItemType Directory -Force $appData | Out-Null
  Set-Content -LiteralPath (Join-Path $appData 'qa_marker.txt') -Value 'marker' -Encoding UTF8
  New-Item -ItemType Directory -Force $appData | Out-Null
  $prefs = Join-Path $appData 'Preferences'
  $before = if (Test-Path $prefs) { (Get-FileHash -LiteralPath $prefs).Hash } else { $null }
  $t = Measure-Command { Start-Process -FilePath $setup -ArgumentList '/S' -Wait }
  [ordered]@{ seconds = [math]::Round($t.TotalSeconds, 1); facts = Get-InstallFacts $installDir
              marker_kept = (Test-Path -LiteralPath (Join-Path $appData 'qa_marker.txt'))
              preferences_unchanged = $(if ($before) { (Get-FileHash -LiteralPath $prefs).Hash -eq $before } else { 'no Preferences before' })
              lifecycle_after = Test-Lifecycle (Join-Path $installDir 'VietDoc OCR.exe') }
}
Stage 'upgrade_gui_reinstall' {
  $g = Invoke-GuiInstall $setup $Out $false
  $g.facts = Get-InstallFacts $installDir
  $g
}
# Portable in a Vietnamese folder name with spaces on the Desktop.
$pname = 'Th' + [char]0x01B0 + ' m' + [char]0x1EE5 + 'c Portable c' + [char]0x00F3 + ' d' + [char]0x1EA5 + 'u ' + [char]0x0103
$pdir = Join-Path ([Environment]::GetFolderPath('Desktop')) $pname
Stage 'portable' {
  $snap = { @(Get-ChildItem -LiteralPath $appData -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { "$($_.FullName)|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }) }
  $before = & $snap
  $t = Measure-Command { Expand-Archive -LiteralPath $zip -DestinationPath $pdir }
  $exe = Join-Path $pdir 'VietDoc OCR\VietDoc OCR.exe'
  $life = Test-Lifecycle $exe
  $ocr = Invoke-OcrSet (Join-Path $pdir 'VietDoc OCR\resources') $In $subset $Out 'portable'
  $after = & $snap
  [ordered]@{ folder = $pdir; extract_seconds = [math]::Round($t.TotalSeconds, 1); lifecycle = $life; ocr = $ocr
              data_folder_entries = [string[]]@(Get-ChildItem -LiteralPath (Join-Path $pdir 'VietDoc OCR Data') -Name)
              appdata_changed = @(Compare-Object $before $after -ErrorAction SilentlyContinue).Count }
}
# Two copies sharing %APPDATA%\VietDoc OCR (as an installed app and the development runner do): the second must not
# start a second backend; Electron's single-instance lock hands over to the first.
Stage 'shared_profile_conflict' {
  $data = Join-Path $pdir 'VietDoc OCR Data'
  Rename-Item -LiteralPath $data -NewName 'VietDoc OCR Data.off'
  $first = Start-Process -FilePath (Join-Path $installDir 'VietDoc OCR.exe') -PassThru
  Start-Sleep -Seconds 20
  $second = Start-Process -FilePath (Join-Path $pdir 'VietDoc OCR\VietDoc OCR.exe') -PassThru
  $secondExited = $second.WaitForExit(30000)
  $portableBackends = @(Get-AppProcesses (Join-Path $pdir 'VietDoc OCR') | Where-Object { $_.ProcessName -eq 'vietdoc-backend' }).Count
  $first.Refresh(); $first.CloseMainWindow() | Out-Null; $first.WaitForExit(60000) | Out-Null
  Start-Sleep -Seconds 3
  Rename-Item -LiteralPath (Join-Path $pdir 'VietDoc OCR Data.off') -NewName 'VietDoc OCR Data'
  [ordered]@{ second_copy_exited = $secondExited; second_exit_code = $(if ($secondExited) { $second.ExitCode } else { $null })
              second_copy_backends = $portableBackends
              left = (@(Get-AppProcesses $installDir).Count + @(Get-AppProcesses (Join-Path $pdir 'VietDoc OCR')).Count) }
}
Stage 'vietnamese_account' {
  $name = 'Nguy' + [char]0x1EC5 + 'n V' + [char]0x0103 + 'n Th' + [char]0x1EED
  $pw = ConvertTo-SecureString ('Vd-Sandbox-' + (Get-Random) + '!a') -AsPlainText -Force
  New-LocalUser -Name $name -Password $pw -PasswordNeverExpires | Out-Null
  $pub = 'C:\Users\Public\vdqa'
  New-Item -ItemType Directory -Force $pub | Out-Null
  Copy-Item -LiteralPath $setup -Destination $pub
  Copy-Item -LiteralPath $In -Destination (Join-Path $pub 'inputs') -Recurse
  Copy-Item -LiteralPath 'C:\vd\tools\vdqa_common.ps1', 'C:\vd\tools\vn_user_stage.ps1', 'C:\vd\tools\sandbox_docs.txt' -Destination $pub
  $cred = New-Object Management.Automation.PSCredential($name, $pw)
  $p = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Credential $cred -LoadUserProfile `
       -WorkingDirectory $pub -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $pub 'vn_user_stage.ps1') `
       -RedirectStandardOutput (Join-Path $pub 'vn_stdout.txt') -RedirectStandardError (Join-Path $pub 'vn_stderr.txt') -PassThru
  $done = $p.WaitForExit(3600000)
  foreach ($f in 'vn_stdout.txt', 'vn_stderr.txt') { if (Test-Path (Join-Path $pub $f)) { Copy-Item -LiteralPath (Join-Path $pub $f) -Destination $Out } }
  $result = Join-Path $pub 'vn_out\result.json'
  if (Test-Path $result) { Copy-Item -LiteralPath (Join-Path $pub 'vn_out') -Destination (Join-Path $Out 'vn_out') -Recurse -Force }
  [ordered]@{ account = $name; finished = $done; exit_code = $(if ($done) { $p.ExitCode } else { $null }); result_file = (Test-Path $result) }
}
Stage 'uninstall' {
  $t = Measure-Command { Start-Process -FilePath (Join-Path $installDir 'Uninstall VietDoc OCR.exe') -ArgumentList '/S' -Wait }
  for ($i = 0; $i -lt 120 -and (Test-Path -LiteralPath (Join-Path $installDir 'VietDoc OCR.exe')); $i++) { Start-Sleep -Milliseconds 500 }
  Start-Sleep -Seconds 3
  [ordered]@{ seconds = [math]::Round($t.TotalSeconds, 1); facts = Get-InstallFacts $installDir
              install_dir_left = (Test-Path -LiteralPath $installDir)
              appdata_kept = (Test-Path -LiteralPath (Join-Path $appData 'qa_marker.txt'))
              processes_left = @(Get-Process | Where-Object { $_.ProcessName -in 'VietDoc OCR', 'vietdoc-backend' }).Count }
}
$R.finished = (Get-Date).ToString('s')
Save-Json $R (Join-Path $Out 'results.json')
Set-Content -LiteralPath (Join-Path $Out 'done.txt') -Value 'done'
if (-not $NoShutdown) { Stop-Computer -Force }
