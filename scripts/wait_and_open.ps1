param(
    [string]$HostName = '127.0.0.1',
    [int]$Port = 7860,
    [int]$TimeoutSec = 240
)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$url = "http://${HostName}:${Port}/health"
$ui  = "http://${HostName}:${Port}/"

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 1500
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) {
            Start-Sleep -Milliseconds 400
            Start-Process $ui
            exit 0
        }
    } catch {
        # 服务还在加载模型，继续等
    }
}

# 超时：仍然尝试打开，让用户看到错误页/连接失败
Start-Process $ui
exit 1
