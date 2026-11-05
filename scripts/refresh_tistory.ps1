# 티스토리 세션 갱신 + GitHub Secret 업데이트를 한 번에 수행한다.
#
#   powershell -ExecutionPolicy Bypass -File scripts/refresh_tistory.ps1
#
# 브라우저 창에서 로그인을 마치면 자동으로 세션을 저장하고,
# 같은 세션을 GitHub Actions 의 TISTORY_STORAGE_STATE Secret 에 반영한다.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

npm run login
if ($LASTEXITCODE -ne 0) {
    throw "티스토리 로그인/세션 저장 실패"
}

& (Join-Path $root "scripts/update_tistory_secret.ps1")
