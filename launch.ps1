$ErrorActionPreference = "Stop"

$chromePath   = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$userDataDir  = "C:\temp\chrome-gpt-debug"
$debugPort    = 9222
$chatUrl      = "https://chatgpt.com"
$pythonExe    = "python"
$mainPy       = Join-Path $PSScriptRoot "main.py"

$chromeStartedByScript = $false
$chromeProcess = $null

function Test-DebugPort {
    param([int]$Port)

    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2
        return $true
    }
    catch {
        return $false
    }
}

try {
    if (-not (Test-Path $chromePath)) {
        throw "Chrome не найден: $chromePath"
    }

    if (-not (Test-Path $userDataDir)) {
        New-Item -ItemType Directory -Path $userDataDir | Out-Null
    }

    if (-not (Test-Path $mainPy)) {
        throw "Не найден main.py: $mainPy"
    }

    if (-not (Test-DebugPort -Port $debugPort)) {
        Write-Host "[...] Запускаю Chrome с remote debugging..."

        $chromeProcess = Start-Process -FilePath $chromePath -ArgumentList @(
            "--remote-debugging-port=$debugPort",
            "--user-data-dir=$userDataDir",
            $chatUrl
        ) -PassThru

        $chromeStartedByScript = $true

        $maxAttempts = 30
        for ($i = 0; $i -lt $maxAttempts; $i++) {
            Start-Sleep -Milliseconds 700
            if (Test-DebugPort -Port $debugPort) {
                break
            }
        }

        if (-not (Test-DebugPort -Port $debugPort)) {
            throw "Chrome не поднял debug-порт $debugPort"
        }
    }
    else {
        Write-Host "[OK] Chrome с debug-портом уже запущен."
    }

    Write-Host "[...] Запускаю main.py..."
    & $pythonExe $mainPy
}
finally {
    if ($chromeStartedByScript -and $chromeProcess -and -not $chromeProcess.HasExited) {
        Write-Host "[...] Закрываю Chrome, который был запущен этим скриптом..."
        try {
            Stop-Process -Id $chromeProcess.Id -Force
        }
        catch {
        }
    }
}