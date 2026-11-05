param(
    [string]$StatePath = ".state/tistory_storage_state.json"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $StatePath)) {
    throw "세션 파일이 없습니다: $StatePath  (먼저 'npm run login' 실행)"
}

$resolved = (Resolve-Path $StatePath).Path
$bytes = [System.IO.File]::ReadAllBytes($resolved)
$b64 = [System.Convert]::ToBase64String($bytes)

# gh secret set 은 stdin 입력을 받는다.
$b64 | gh secret set TISTORY_STORAGE_STATE

if ($LASTEXITCODE -ne 0) {
    throw "gh secret set 실패 (gh auth login 상태를 확인하세요)"
}

Write-Host "TISTORY_STORAGE_STATE 갱신 완료 ($resolved)"
