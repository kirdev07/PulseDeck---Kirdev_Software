# Unit tests of an Android app without Gradle's test runner (it breaks on a Cyrillic user folder).
#
#   powershell -File tools\dev\android-tests.ps1 PulseDeck-MobileAPP
#   powershell -File tools\dev\android-tests.ps1 PulseDeck-PanelAPP
#
# The apps are separate repositories next to this one (C:\My Project\PulseDeck-MobileAPP, …);
# a full path to an app folder works too.
param([Parameter(Mandatory)] [string] $App)

$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot)
$appDir = if (Test-Path $App) { (Resolve-Path $App).Path } else { Join-Path (Split-Path $root) $App }
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = Join-Path $HOME '.jdks\jbr-21.0.11' }
$env:CP_OUT = Join-Path $env:TEMP "pulsedeck-test-cp-$App.txt"

Push-Location $appDir
try {
    & .\gradlew.bat -q -I (Join-Path $PSScriptRoot 'android-test-classpath.gradle') `
        :app:bundleDebugClassesToRuntimeJar :app:bundleDebugClassesToCompileJar :app:printTestClasspath
    if ($LASTEXITCODE -ne 0) { throw 'Gradle failed' }
    $package = ((git grep -h '^package' -- app/src/test | Select-Object -First 1) -replace 'package ', '').Trim()
    $classes = git grep -h '^class \w*Test' -- app/src/test | ForEach-Object { "$package." + (($_ -split '\s+')[1] -replace '[({].*', '') }
    $cp = (Get-Content $env:CP_OUT -Raw -Encoding UTF8).Trim()
    & (Join-Path $env:JAVA_HOME 'bin\java.exe') -cp $cp org.junit.runner.JUnitCore @classes
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
