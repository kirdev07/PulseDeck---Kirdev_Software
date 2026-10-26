# PulseDeck: установка одной командой, без предупреждения SmartScreen.
#
#   irm https://raw.githubusercontent.com/kirdev07/PulseDeck---Kirdev_Software/main/install.ps1 | iex
#
# Скачивает установщик последней версии с GitHub Releases и запускает его.
# Права администратора не нужны: PulseDeck ставится для текущего пользователя.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # иначе Invoke-WebRequest качает в разы медленнее
$repo = 'kirdev07/PulseDeck---Kirdev_Software'

Write-Host ''
Write-Host '  PulseDeck — установка' -ForegroundColor White
Write-Host ''

if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'PulseDeck работает только на 64-битной Windows 10 или 11.'
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Host '  Ищу последнюю версию на GitHub…'
$release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'PulseDeck-install' }
$asset = $release.assets | Where-Object { $_.name -like '*-Setup.exe' } | Select-Object -First 1
if (-not $asset) { throw "В релизе $($release.tag_name) нет установщика." }

$target = Join-Path $env:TEMP $asset.name
Write-Host "  Скачиваю $($asset.name) ($([math]::Round($asset.size / 1MB)) МБ)…"
Invoke-WebRequest $asset.browser_download_url -OutFile $target -UseBasicParsing -Headers @{ 'User-Agent' = 'PulseDeck-install' }
if ((Get-Item $target).Length -ne $asset.size) { throw 'Файл скачался не полностью. Запустите команду ещё раз.' }

Write-Host '  Запускаю установщик…'
Start-Process $target -ArgumentList '/SP-' -Wait
Remove-Item $target -ErrorAction SilentlyContinue
Write-Host ''
Write-Host "  Готово: PulseDeck $($release.tag_name.TrimStart('v')) установлен." -ForegroundColor Green
Write-Host ''
