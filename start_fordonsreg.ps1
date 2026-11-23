# Windows-start utan krav pa Python. Ingen installation utan bekraftelse.
$ErrorActionPreference = 'Stop'
# Ingen terminal ska synas. Konsolfonstret som startfilen eventuellt
# skapades i dols direkt, innan nagot annat gors.
try {
    $sig = '[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow(); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);'
    $console = Add-Type -MemberDefinition $sig -Name 'FrConsole' -Namespace 'Fordonsreg' -PassThru
    $handle = $console::GetConsoleWindow()
    if ($handle -ne [IntPtr]::Zero) { $console::ShowWindow($handle, 0) | Out-Null }
} catch { }
Add-Type -AssemblyName System.Windows.Forms
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Show-Info([string]$message) {
    [System.Windows.Forms.MessageBox]::Show($message, 'Fordonsreg') | Out-Null
}
function Find-Python {
    $candidates = @()
    foreach ($name in @('python.exe', 'py.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += ,@($cmd.Source, ($name -eq 'py.exe')) }
    }
    # Python kan vara installerad men inte finnas i PATH. Använd endast
    # konkreta registervägar och kontrollera att de faktiskt fungerar.
    foreach ($rootKey in @('HKLM:\SOFTWARE\Python\PythonCore', 'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore', 'HKCU:\SOFTWARE\Python\PythonCore')) {
        if (!(Test-Path $rootKey)) { continue }
        foreach ($versionKey in @(Get-ChildItem $rootKey -ErrorAction SilentlyContinue)) {
            $installKey = Join-Path $versionKey.PSPath 'InstallPath'
            try {
                $install = (Get-Item -LiteralPath $installKey -ErrorAction Stop).GetValue('')
                if ($install) { $candidates += ,@((Join-Path $install 'python.exe'), $false) }
            } catch { }
        }
    }
    foreach ($item in $candidates) {
        $candidate = $item[0]
        # Windows Store-alias kan öppna Store i stället för att köra Python.
        # Betrakta aliaset som en oklar befintlig installation, inte frånvaro.
        if ($candidate -match '(?i)\\WindowsApps\\') { continue }
        try {
            $argsList = @('-c', 'import sys; assert sys.version_info.major == 3; print(sys.executable)')
            if ($item[1]) { $argsList = @('-3') + $argsList }
            $path = & $candidate @argsList 2>$null | Select-Object -First 1
            if ($LASTEXITCODE -eq 0 -and $path -and (Test-Path -LiteralPath $path)) { return $path }
        } catch { }
    }
    return $null
}
try {
    $python = Find-Python
    if (!$python) {
        # En launcher, registerpost eller Python i PATH kan betyda att Python
        # finns men ar trasig eller otillganglig. Installera aldrig i det laget.
        $registered = @(
            'HKLM:\SOFTWARE\Python\PythonCore',
            'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore',
            'HKCU:\SOFTWARE\Python\PythonCore'
        ) | Where-Object { (Test-Path $_) -and @(Get-ChildItem $_ -ErrorAction SilentlyContinue).Count -gt 0 }
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        $pythonPresent = [bool]$pythonCommand
        # WindowsApps kan innehalla Microsoft Stores tomma alias, aven nar
        # Python inte finns. Godta franvaro bara om Appx kan undersokas.
        if ($pythonCommand -and $pythonCommand.Source -match '(?i)\\WindowsApps\\') {
            try {
                if (!(Get-Command Get-AppxPackage -ErrorAction SilentlyContinue)) { throw 'Appx kan inte kontrolleras.' }
                $storePython = @(Get-AppxPackage -ErrorAction Stop | Where-Object { $_.Name -match '(?i)python' })
                $pythonPresent = $storePython.Count -gt 0
            } catch {
                Show-Info 'Windows Store-installationer kunde inte kontrolleras. Ingen ny installation erbjuds.'
                exit 1
            }
        }
        if ($pythonPresent -or (Get-Command py.exe -ErrorAction SilentlyContinue) -or $registered) {
            Show-Info 'Python eller en Python-launcher finns redan men fungerar inte. Reparera den befintliga installationen; ingen ny installation gors.'
            exit 1
        }
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (!$winget) { Show-Info 'Python och winget kunde inte hittas. Kontrollera om Python redan finns och installera vid behov manuellt.'; exit 1 }
        $listing = & $winget.Source list --source winget --accept-source-agreements --disable-interactivity 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -or $listing -match '(?i)Python\.Python|PythonSoftwareFoundation\.Python') {
            Show-Info 'Det gick inte att utesluta en befintlig Pythoninstallation via winget. Ingen ny installation gors.'
            exit 1
        }
        $choice = [System.Windows.Forms.MessageBox]::Show(
            'Ingen Python hittades i PATH, registret eller winget. Portabla eller andra oregistrerade installationer kan finnas. Om Python verkligen saknas: installera senaste Python for hela datorn via winget?',
            'Fordonsreg', [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
        if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }
        $response = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/python-versions/contents/versions-manifest.json' -Headers @{ 'User-Agent' = 'Fordonsreg-Python-Check' } -TimeoutSec 15
        $manifest = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($response.content)) | ConvertFrom-Json
        $latest = $manifest | Where-Object { $_.stable -and $_.version -match '^3\.\d+\.\d+$' } | Sort-Object { [version]$_.version } -Descending | Select-Object -First 1
        if (!$latest -or $latest.version -notmatch '^3\.(\d+)\.\d+$') { throw 'Kunde inte faststalla senaste stabila version.' }
        $package = 'Python.Python.3.' + $Matches[1]
        $available = & $winget.Source show --id $package --exact --source winget --versions --disable-interactivity 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -or $available -notmatch ('(?<![\d.])' + [regex]::Escape($latest.version) + '(?![\d.])')) { throw 'Winget erbjuder inte den kontrollerade senaste versionen.' }
        & $winget.Source install --id $package --exact --source winget --version $latest.version --scope machine --accept-source-agreements --accept-package-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw 'Pythoninstallationen misslyckades.' }
        $python = Find-Python
        if (!$python) { Show-Info 'Installationen slutfords, men Python kunde inte hittas i denna process. Logga in igen och kontrollera installationen innan du startar om.'; exit 1 }
    }
    # pythonw.exe startar appen utan konsol. Saknas den anvands python.exe,
    # men da startas processen dold sa att inget terminalfonster syns.
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    $hidden = $false
    if (Test-Path -LiteralPath $pythonw) { $python = $pythonw } else { $hidden = $true }
    $startArgs = @{ FilePath = $python; ArgumentList = ('"' + (Join-Path $root 'start.pyw') + '"'); WorkingDirectory = $root }
    if ($hidden) { $startArgs['WindowStyle'] = 'Hidden' }
    Start-Process @startArgs
} catch {
    Show-Info ('Starten eller Pythoninstallationen kunde inte slutfors: ' + $_.Exception.Message)
    exit 1
}
