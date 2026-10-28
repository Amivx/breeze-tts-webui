# Breeze TTS 2 本地控制台启动器
# 由 start-webui.bat 调用；也可直接右键「使用 PowerShell 运行」。
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

# 让控制台按 UTF-8 显示，Python 与 PowerShell 的中文都不会乱码
try { chcp 65001 > $null } catch {}
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {}

$env:PYTHONUTF8 = '1'
$env:HF_ENDPOINT = 'https://hf-mirror.com'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:TOKENIZERS_PARALLELISM = 'false'

$HostName = '127.0.0.1'
$Port = 7860

# 允许 --port 覆盖
for ($i = 0; $i -lt $ExtraArgs.Count - 1; $i++) {
    if ($ExtraArgs[$i] -eq '--port') { $Port = [int]$ExtraArgs[$i + 1] }
    if ($ExtraArgs[$i] -eq '--host') { $HostName = $ExtraArgs[$i + 1] }
}

$py = Join-Path $Root '.venv\Scripts\python.exe'
$ckpt = Join-Path $Root 'checkpoints\Breeze-TTS-2'

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host '  Breeze TTS 2 本地控制台' -ForegroundColor Cyan
Write-Host ("  界面  http://{0}:{1}/" -f $HostName, $Port) -ForegroundColor Cyan
Write-Host ("  文档  http://{0}:{1}/docs" -f $HostName, $Port) -ForegroundColor Cyan
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "[错误] 找不到虚拟环境: $py" -ForegroundColor Red
    Write-Host '        请先在项目目录执行: python -m venv .venv 并安装依赖。'
    Read-Host '按回车退出'
    exit 1
}
if (-not (Test-Path -LiteralPath $ckpt)) {
    Write-Host "[错误] 找不到模型权重: $ckpt" -ForegroundColor Red
    Write-Host '        请把 Breeze-TTS-2 权重下载到 checkpoints\Breeze-TTS-2。'
    Read-Host '按回车退出'
    exit 1
}

# 端口占用检查
$busy = $null
try {
    $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch {
    $netstat = netstat -ano | Select-String -Pattern (":$Port\s+.*LISTENING")
    if ($netstat) { $busy = $netstat }
}
if ($busy) {
    $owner = ($busy | Select-Object -First 1).OwningProcess
    Write-Host "[提示] 端口 $Port 已被占用（PID $owner），可能已经有一个控制台在运行。" -ForegroundColor Yellow
    Write-Host ("       直接打开 http://{0}:{1}/ 看看；要换端口：start-webui.bat --port 7861" -f $HostName, $Port)
    Write-Host '       仍要再启动一个实例吗？直接回车继续，输入 n 退出。'
    $a = Read-Host '  [回车/n]'
    if ($a -eq 'n') { exit 0 }
}

Write-Host '正在加载模型（首次需要 15~30 秒），就绪后会自动打开浏览器...'
Write-Host '本窗口不要关闭，关闭即停止服务。' -ForegroundColor DarkGray
Write-Host ''

# 后台轮询 /health，就绪后打开浏览器
$opener = Join-Path $Root 'scripts\wait_and_open.ps1'
if (Test-Path -LiteralPath $opener) {
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$opener`"", '-HostName', $HostName, '-Port', $Port) `
        -WindowStyle Hidden | Out-Null
}

# 前台运行服务，日志实时输出到本窗口
$argv = @('-m', 'webui.server', $ckpt, '--host', $HostName, '--port', $Port) + $ExtraArgs
& $py @argv
$code = $LASTEXITCODE

Write-Host ''
Write-Host '================================================================' -ForegroundColor DarkYellow
Write-Host '  服务已退出，以上为退出日志。' -ForegroundColor DarkYellow
Write-Host '   端口被占用     改用 start-webui.bat --port 7861'
Write-Host '   显存不足       关闭其他占用显卡的程序后重试'
Write-Host '   依赖或权重缺失 检查 .venv 与 checkpoints\Breeze-TTS-2'
Write-Host '================================================================' -ForegroundColor DarkYellow
if ($code -ne 0) { Write-Host ("退出码: " + $code) -ForegroundColor Red }
Read-Host '按回车关闭窗口'
