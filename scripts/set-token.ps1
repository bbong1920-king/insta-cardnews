# .env 에 비밀 값을 안전하게 넣는다 (입력한 값은 화면에 보이지 않음)
# 사용법: & .\scripts\set-token.ps1            → CLAUDE_CODE_OAUTH_TOKEN
#         & .\scripts\set-token.ps1 IG_ACCESS_TOKEN
param([string]$Name = "CLAUDE_CODE_OAUTH_TOKEN")

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root ".env.example") $envFile }

$secure = Read-Host "$Name 값을 붙여넣고 Enter (화면에 표시되지 않습니다)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim()
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

if (-not $value) { Write-Host "값이 비어 있어서 아무것도 바꾸지 않았습니다."; exit 1 }

$lines = [IO.File]::ReadAllLines($envFile)
$found = $false
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match "^$Name=") { $lines[$i] = "$Name=$value"; $found = $true }
}
if (-not $found) { $lines += "$Name=$value" }
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))

Write-Host "저장 완료: $Name (길이 $($value.Length)자)"
