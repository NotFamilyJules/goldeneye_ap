@echo off
setlocal EnableDelayedExpansion
set "GOLDENEYE_CMDLINE=!CMDCMDLINE!"
setlocal DisableDelayedExpansion
set "GOLDENEYE_LAUNCHER=%~f0"
set "GOLDENEYE_FOLDER=%~dp0"
set /a GOLDENEYE_ARGUMENT_COUNT=0
:arguments
if "%~1"=="" goto launch
set "GOLDENEYE_ARGUMENT_%GOLDENEYE_ARGUMENT_COUNT%=%~1"
set /a GOLDENEYE_ARGUMENT_COUNT+=1
shift
goto arguments
:launch
set "GOLDENEYE_BOOTSTRAP=$source=[IO.File]::ReadAllText($env:GOLDENEYE_LAUNCHER); & ([scriptblock]::Create($source.Substring($source.IndexOf([char]10 + '# PowerShell'))))"
powershell -NoProfile -ExecutionPolicy Bypass -Command "%GOLDENEYE_BOOTSTRAP%"
exit /b %errorlevel%

# PowerShell
$directory = $env:GOLDENEYE_FOLDER
$ClientArguments = @(for ($index = 0; $index -lt [int]$env:GOLDENEYE_ARGUMENT_COUNT; $index++) {
    [Environment]::GetEnvironmentVariable("GOLDENEYE_ARGUMENT_$index")
})
# Explorer's new console contains just cmd and this bootstrap. A terminal has
# another attached shell, or an interactive cmd command line without /c.
Add-Type @'
using System.Runtime.InteropServices;
public class PlayConsole {
    [DllImport("kernel32.dll")]
    public static extern uint GetConsoleProcessList(uint[] processes, uint count);
}
'@
$consoleProcesses = New-Object uint32[] 32
$processCount = [PlayConsole]::GetConsoleProcessList($consoleProcesses, 32)
if (-not $env:GOLDENEYE_DESKTOP -and $processCount -gt 0 -and $processCount -le 2 -and $env:GOLDENEYE_CMDLINE -match '(?i)\s/c\s') {
    # A detached child also avoids leaving a Windows Terminal tab open.
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = (Get-Command powershell.exe).Source
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.EnvironmentVariables['GOLDENEYE_DESKTOP'] = '1'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($env:GOLDENEYE_BOOTSTRAP))
    $start.Arguments = '-NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + $encoded
    [System.Diagnostics.Process]::Start($start) | Out-Null
    exit
}
# Reuse the installed Archipelago Python and libraries; copy neither.
$stateDirectory = Join-Path $env:LOCALAPPDATA '1964GE_AP'
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
$settingsPath = Join-Path $stateDirectory 'settings.json'
$configuration = if (Test-Path -LiteralPath $settingsPath) {
    Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
} else { [pscustomobject]@{} }
$archipelago = $configuration.archipelago
if (-not $archipelago) { $archipelago = Join-Path $env:ProgramData 'Archipelago' }
if (-not (Test-Path "$archipelago\ArchipelagoLauncher.exe") -or $ClientArguments -contains '--configure') {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Choose your Archipelago Installation'
    $picker.Filter = 'Archipelago launcher|ArchipelagoLauncher.exe'
    $picker.InitialDirectory = $archipelago
    if ($picker.ShowDialog() -ne 'OK') { exit }
    $archipelago = Split-Path $picker.FileName
}
$configuration | Add-Member -NotePropertyName archipelago -NotePropertyValue $archipelago -Force
[IO.File]::WriteAllText($settingsPath, ($configuration | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
$runtimeDirectory = $configuration.archipelago
$env:PYTHONHOME = $runtimeDirectory
$env:PYTHONPATH = "$runtimeDirectory\lib;$runtimeDirectory\lib\library.zip"
$pythonDll = (Get-ChildItem $runtimeDirectory -Filter 'python3*.dll' |
              Where-Object Name -ne 'python3.dll' | Select-Object -First 1).FullName
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CandidatePython {
    [DllImport(@"$pythonDll", CallingConvention = CallingConvention.Cdecl)]
    public static extern int Py_Main(int argc, IntPtr argv);
}
"@
$arguments = @('python', "$directory\1964GE_AP.py") + $ClientArguments
$pointers = @($arguments | ForEach-Object { [Runtime.InteropServices.Marshal]::StringToHGlobalUni($_) })
$argumentArray = [Runtime.InteropServices.Marshal]::AllocHGlobal([IntPtr]::Size * $pointers.Count)
for ($index = 0; $index -lt $pointers.Count; $index++) {
    [Runtime.InteropServices.Marshal]::WriteIntPtr($argumentArray, $index * [IntPtr]::Size, $pointers[$index])
}
try { $result = [CandidatePython]::Py_Main($pointers.Count, $argumentArray) }
finally {
    foreach ($pointer in $pointers) { [Runtime.InteropServices.Marshal]::FreeHGlobal($pointer) }
    [Runtime.InteropServices.Marshal]::FreeHGlobal($argumentArray)
}
exit $result

