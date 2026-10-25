param(
    [Parameter(Mandatory=$true)][string]$RuntimeDir,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
$addonRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $RuntimeDir '.venv\Scripts\python.exe'
$env:SCA_RUNTIME_DIR = [IO.Path]::GetFullPath($RuntimeDir)
if ($Arguments.Count -eq 1 -and $Arguments[0] -eq 'provision') {
    $bootstrapPython = $env:SCA_PHYSICS_BOOTSTRAP_PYTHON
    if (-not $bootstrapPython) { throw 'Set SCA_PHYSICS_BOOTSTRAP_PYTHON to CPython 3.12.' }
    & $bootstrapPython -I -B (Join-Path $PSScriptRoot 'provision.py') --runtime-dir $RuntimeDir
} else {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Runtime missing; provision sca-physics first.' }
    if ($Arguments.Count -eq 2 -and $Arguments[0] -eq 'argv-json-base64') {
        $token = $Arguments[1]
    } else {
        $json = ConvertTo-Json -InputObject ([string[]]@($Arguments)) -Compress
        $token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    }
    & $python -I -B (Join-Path $PSScriptRoot 'runtime_cli.py') $token
}
exit $LASTEXITCODE
