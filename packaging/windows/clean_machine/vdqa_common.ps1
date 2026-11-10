# Shared helpers for the clean-machine QA of VietDoc OCR (Windows PowerShell 5.1, no Python on the machine).
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

function Write-Log([string]$Out, [string]$Message) {
  $line = (Get-Date).ToString('s') + ' ' + $Message
  Add-Content -LiteralPath (Join-Path $Out 'log.txt') -Value $line -Encoding UTF8
}

function Save-Json($Object, [string]$Path) {
  $json = $Object | ConvertTo-Json -Depth 8
  [IO.File]::WriteAllText($Path, $json, (New-Object Text.UTF8Encoding($false)))
}

function Save-Screen([string]$Path) {
  try {
    $b = [Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object Drawing.Bitmap($b.Width, $b.Height)
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [Drawing.Point]::Empty, $b.Size)
    $bmp.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
  } catch { }
}

function Get-Environment-Facts {
  $os = Get-CimInstance Win32_OperatingSystem
  $tools = @{}
  foreach ($t in 'python', 'python3', 'py', 'node', 'npm', 'git') {
    $c = Get-Command $t -ErrorAction SilentlyContinue
    $tools[$t] = if ($c) { $c.Source } else { $null }
  }
  [ordered]@{
    computer = $env:COMPUTERNAME; user = $env:USERNAME; profile = $env:USERPROFILE
    os = $os.Caption; version = $os.Version; build = $os.BuildNumber; arch = $os.OSArchitecture
    acp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage').ACP
    long_paths = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem').LongPathsEnabled
    tools_on_path = $tools
    paddlex_cache = Test-Path (Join-Path $env:USERPROFILE '.paddlex')
    network_adapters_up = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up').Count
    appdata_vietdoc_before = Test-Path (Join-Path $env:APPDATA 'VietDoc OCR')
  }
}

function Test-Sums([string]$Folder) {
  $result = [ordered]@{}
  foreach ($line in Get-Content -LiteralPath (Join-Path $Folder 'SHA256SUMS.txt')) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split '\s+', 2
    $actual = (Get-FileHash -LiteralPath (Join-Path $Folder $parts[1]) -Algorithm SHA256).Hash.ToLower()
    $result[$parts[1]] = ($actual -eq $parts[0].ToLower())
  }
  $result
}

# Start the packaged backend the way Electron does (token on stdin, resources as working directory, bundled models).
function Start-Backend([string]$Resources, [string]$Out, [string]$Tag) {
  $exe = Join-Path $Resources 'backend\vietdoc-backend\vietdoc-backend.exe'
  $stdout = Join-Path $Out "backend_$Tag.out.txt"
  $stderr = Join-Path $Out "backend_$Tag.err.txt"
  $cmdline = '"' + $exe + '" --repo-root "' + $Resources + '" --frontend-dist "' + (Join-Path $Resources 'frontend') +
          '" --model-lock "' + (Join-Path $Resources 'model_lock.json') + '" --paddlex-home "' + (Join-Path $Resources 'paddlex') + '"'
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = "$env:SystemRoot\System32\cmd.exe"
  $psi.Arguments = '/d /c "' + $cmdline + ' >"' + $stdout + '" 2>"' + $stderr + '""'
  $psi.WorkingDirectory = $Resources
  $psi.UseShellExecute = $false
  $psi.RedirectStandardInput = $true
  $psi.CreateNoWindow = $true
  $psi.EnvironmentVariables['VIETDOC_MODEL_ROOT'] = (Join-Path $Resources 'models')
  $psi.EnvironmentVariables['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
  $token = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
  [Console]::InputEncoding = New-Object Text.UTF8Encoding($false)   # otherwise .NET writes a BOM before the token
  $p = [Diagnostics.Process]::Start($psi)
  $bytes = [Text.Encoding]::ASCII.GetBytes($token + [char]10)   # raw bytes: no BOM, no carriage return
  $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
  $p.StandardInput.BaseStream.Flush()
  $deadline = (Get-Date).AddSeconds(300)
  while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $stdout) {
      $ready = Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | Where-Object { $_ -like 'VIETDOC_READY *' } | Select-Object -First 1
      if ($ready) {
        $info = $ready.Substring(14) | ConvertFrom-Json
        return @{ process = $p; port = $info.port; token = $token; ready = [string]$ready }   # plain string: Get-Content adds provider properties
      }
    }
    if ($p.HasExited) { break }
    Start-Sleep -Milliseconds 500
  }
  throw "backend did not start ($Tag)"
}

function New-Client([string]$Token) {
  $c = New-Object Net.Http.HttpClient
  $c.Timeout = [TimeSpan]::FromMinutes(30)
  $c.DefaultRequestHeaders.Add('X-VietDoc-Token', $Token)
  $c
}

function Get-Status($Backend) {
  $c = New-Client $Backend.token
  $c.GetStringAsync("http://127.0.0.1:$($Backend.port)/__desktop__/status").Result | ConvertFrom-Json
}

function Invoke-Ocr($Backend, [string]$Path, [string]$Mode, [string]$OutDir) {
  $types = @{ '.pdf' = 'application/pdf'; '.png' = 'image/png'; '.jpg' = 'image/jpeg' }
  $c = New-Client $Backend.token
  $form = New-Object Net.Http.MultipartFormDataContent
  $form.Add((New-Object Net.Http.StringContent($Mode)), 'mode')
  $file = New-Object Net.Http.ByteArrayContent(, [IO.File]::ReadAllBytes($Path))
  $file.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::Parse($types[[IO.Path]::GetExtension($Path).ToLower()])
  $name = [IO.Path]::GetFileName($Path)
  $form.Add($file, 'file', $name)
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $response = $c.PostAsync("http://127.0.0.1:$($Backend.port)/api/ocr", $form).Result
  $body = $response.Content.ReadAsStringAsync().Result
  $watch.Stop()
  New-Item -ItemType Directory -Force $OutDir | Out-Null
  [IO.File]::WriteAllText((Join-Path $OutDir "$name`__$Mode.json"), $body, (New-Object Text.UTF8Encoding($false)))
  [ordered]@{ document = $name; mode = $Mode; http = [int]$response.StatusCode; seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1) }
}

function Stop-Backend($Backend) {
  try { (New-Client $Backend.token).PostAsync("http://127.0.0.1:$($Backend.port)/__desktop__/shutdown", (New-Object Net.Http.StringContent(''))).Result | Out-Null } catch { }
  if (-not $Backend.process.WaitForExit(60000)) { $Backend.process.Kill() }
}

function Invoke-OcrSet([string]$Resources, [string]$Inputs, [string[]]$Docs, [string]$Out, [string]$Tag) {
  $b = Start-Backend $Resources $Out $Tag
  $status = Get-Status $b
  $rows = @()
  foreach ($d in $Docs) {
    $name, $mode = $d -split '=', 2
    $rows += Invoke-Ocr $b (Join-Path $Inputs $name) $mode (Join-Path $Out "ocr_$Tag")
  }
  Stop-Backend $b
  [ordered]@{ ocr_allowed = $status.ocr_allowed; model_downloads = $status.model_downloads; ready = $b.ready; requests = $rows }
}

function Get-AppProcesses([string]$AppDir) {
  @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase) })
}

# Open the release app like a user, wait for its backend listener, close the window, check nothing is left.
function Test-Lifecycle([string]$Exe, [int]$Wait = 10) {
  $dir = Split-Path -Parent $Exe
  $start = Get-Date
  $p = Start-Process -FilePath $Exe -WorkingDirectory $dir -PassThru
  $ready = $null; $external = @()
  while (((Get-Date) - $start).TotalSeconds -lt 240) {
    $backend = Get-AppProcesses $dir | Where-Object { $_.ProcessName -eq 'vietdoc-backend' }
    foreach ($b in $backend) {
      $listen = Get-NetTCPConnection -OwningProcess $b.Id -State Listen -ErrorAction SilentlyContinue
      if ($listen -and -not $ready) { $ready = [math]::Round(((Get-Date) - $start).TotalSeconds, 1) }
    }
    foreach ($q in (Get-AppProcesses $dir)) {
      $external += @(Get-NetTCPConnection -OwningProcess $q.Id -ErrorAction SilentlyContinue |
        Where-Object { $_.RemoteAddress -and $_.RemoteAddress -notmatch '^(127\.|::1|0\.0\.0\.0|::$)' } |
        ForEach-Object { "$($q.ProcessName) $($_.RemoteAddress):$($_.RemotePort)" })
    }
    if ($ready -and ((Get-Date) - $start).TotalSeconds -gt ($ready + $Wait)) { break }
    Start-Sleep -Milliseconds 500
  }
  $p.Refresh()
  $earlyExit = $p.HasExited   # e.g. another instance already holds the profile lock
  $closed = if ($earlyExit) { $false } else { $p.CloseMainWindow() }
  $exited = $p.WaitForExit(60000)
  Start-Sleep -Seconds 3
  $left = @(Get-AppProcesses $dir | ForEach-Object { "$($_.ProcessName) $($_.Id)" })
  [ordered]@{ backend_listening_after_s = $ready; exited_before_close = $earlyExit; close_sent = $closed; exited = $exited; leftover = $left
              external = @($external | Select-Object -Unique)
              pass = ($ready -ne $null -and -not $earlyExit -and $exited -and $left.Count -eq 0 -and $external.Count -eq 0) }
}

# --- NSIS installer driven through its own controls (no mouse, no keyboard focus needed) ---
# Compiled only when the GUI installer is driven: Windows PowerShell's C# compiler cannot write to a TEMP folder
# whose path has Vietnamese letters (the Vietnamese-account stage never needs it).
function Initialize-VdWin {
  if ('VdWin' -as [type]) { return }
  Add-Type -TypeDefinition @'
  using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
  public static class VdWin {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr p, EnumProc f, IntPtr l);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern IntPtr SendMessageTimeout(IntPtr h, uint m, IntPtr w, IntPtr l, uint flags, uint ms, out IntPtr result);
    public static IntPtr Send(IntPtr h, uint m, IntPtr w, IntPtr l) { IntPtr r; SendMessageTimeout(h, m, w, l, 2, 5000, out r); return r; }
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
    public static string Text(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
    public static string Class(IntPtr h) { var s = new StringBuilder(256); GetClassName(h, s, 256); return s.ToString(); }
    public static List<IntPtr> Top(uint pid) { var r = new List<IntPtr>(); EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p); if (p == pid && IsWindowVisible(h)) r.Add(h); return true; }, IntPtr.Zero); return r; }
    public static List<IntPtr> Children(IntPtr parent) { var r = new List<IntPtr>(); EnumChildWindows(parent, (h, l) => { r.Add(h); return true; }, IntPtr.Zero); return r; }
    // Posted, not sent: a page shown with nsDialogs runs its own message loop, so a sent WM_COMMAND would never return.
    public static void Click(IntPtr dialog, int id, IntPtr button) { PostMessage(dialog, 0x0111, (IntPtr)id, button); }
    public static void SetCheck(IntPtr box, bool on) { Send(box, 0x00F1, (IntPtr)(on ? 1 : 0), IntPtr.Zero); }
    public static bool Checked(IntPtr box) { return Send(box, 0x00F0, IntPtr.Zero, IntPtr.Zero) == (IntPtr)1; }
  }
'@
}

function Invoke-GuiInstall([string]$Setup, [string]$Out, [bool]$DesktopShortcut) {
  Initialize-VdWin
  $p = Start-Process -FilePath $Setup -PassThru
  $pages = @(); $start = Get-Date; $shot = 0
  while (-not $p.HasExited -and ((Get-Date) - $start).TotalMinutes -lt 15) {
    Start-Sleep -Milliseconds 1500
    $win = [VdWin]::Top([uint32]$p.Id) | Where-Object { [VdWin]::Class($_) -eq '#32770' } | Select-Object -First 1
    if (-not $win) { continue }
    $kids = [VdWin]::Children($win) | Where-Object { [VdWin]::IsWindowVisible($_) }
    $texts = @($kids | ForEach-Object { [VdWin]::Text($_) } | Where-Object { $_ })
    $next = $kids | Where-Object { [VdWin]::GetDlgCtrlID($_) -eq 1 -and [VdWin]::Class($_) -eq 'Button' } | Select-Object -First 1
    if (-not $next -or -not [VdWin]::IsWindowEnabled($next)) { continue }   # progress page
    $label = [VdWin]::Text($next)
    $shot++; Save-Screen (Join-Path $Out ("gui_{0:00}.png" -f $shot))
    $boxes = $kids | Where-Object { [VdWin]::Class($_) -eq 'Button' -and [VdWin]::GetDlgCtrlID($_) -ne 1 -and [VdWin]::GetDlgCtrlID($_) -ne 2 -and [VdWin]::GetDlgCtrlID($_) -ne 3 }
    $desktop = $boxes | Where-Object { [VdWin]::Text($_) -like '*Desktop*' } | Select-Object -First 1
    $run = $boxes | Where-Object { ([VdWin]::Text($_) -replace '&', '') -like 'Run *' } | Select-Object -First 1
    $page = [ordered]@{ button = $label; texts = @($texts | Select-Object -First 8) }
    if ($desktop) { $page.desktop_checkbox_before = [VdWin]::Checked($desktop)
                    if ($DesktopShortcut) { [VdWin]::SetCheck($desktop, $true) }   # never clears a preselected box
                    $page.desktop_checkbox = [VdWin]::Checked($desktop) }
    if ($run) { [VdWin]::SetCheck($run, $false); $page.run_checkbox_cleared = -not [VdWin]::Checked($run) }
    $pages += $page
    [VdWin]::Click($win, 1, $next)
    Start-Sleep -Milliseconds 2500
  }
  $exited = $p.WaitForExit(120000)
  [ordered]@{ exited = $exited; exit_code = $(if ($exited) { $p.ExitCode } else { $null }); pages = $pages
              seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1) }
}

function Get-InstallFacts([string]$InstallDir) {
  $sm = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VietDoc OCR.lnk'
  $dk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'VietDoc OCR.lnk'
  $entries = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | ForEach-Object { Get-ItemProperty $_.PSPath } |
    Where-Object { $_.DisplayName -like 'VietDoc*' } | ForEach-Object { $_.DisplayName })
  $files = @(Get-ChildItem -LiteralPath $InstallDir -Recurse -File -ErrorAction SilentlyContinue)
  [ordered]@{ install_dir = $InstallDir; exists = (Test-Path -LiteralPath (Join-Path $InstallDir 'VietDoc OCR.exe'))
              files = $files.Count; bytes = ($files | Measure-Object Length -Sum).Sum
              start_menu_lnk = (Test-Path -LiteralPath $sm); desktop_lnk = (Test-Path -LiteralPath $dk)
              uninstall_entries = $entries
              updater_cache = (Test-Path (Join-Path $env:LOCALAPPDATA 'vietdoc-ocr-desktop-updater'))
              appdata_vietdoc = (Test-Path (Join-Path $env:APPDATA 'VietDoc OCR')) }
}
