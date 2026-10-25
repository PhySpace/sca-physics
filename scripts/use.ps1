param(
    [Parameter(Mandatory=$true)][string]$ScaPython,
    [Parameter(Mandatory=$true)][string]$AddonHome,
    [Parameter(Mandatory=$true)][string]$SkillsDir,
    [Parameter(Mandatory=$true)][string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
$json = ConvertTo-Json -InputObject @($Arguments) -Compress
$token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
if ($token.Length -gt 6000) { throw 'Arguments exceed Windows transport capacity; use a config file.' }
& $ScaPython -I -B -m simplecadapi.cli addon use --home $AddonHome --skills-dir $SkillsDir sca-physics argv-json-base64 $token
exit $LASTEXITCODE
