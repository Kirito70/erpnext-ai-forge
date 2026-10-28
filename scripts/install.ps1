# erpnext-ai-forge installer for Windows.
#
#   irm https://github.com/Kirito70/erpnext-ai-forge/releases/latest/download/install.ps1 | iex
#
# Frappe benches run inside WSL2 on Windows, and forge's hooks are bash, so
# forge is installed there: this script checks for WSL and a Linux distro, then
# runs install.sh inside WSL. Use `forge` from your WSL shell afterwards.
#
# Environment (set with $env:NAME='value' before running):
#   FORGE_INVITE         settings from `forge invite`
#   FORGE_GITHUB_TOKEN   read-only token, only if the repo is private
#   FORGE_REPO           owner/name to install from (default Kirito70/erpnext-ai-forge)
#   FORGE_VERSION        a specific release, e.g. v0.8.0 (default: latest)
#   FORGE_WSL_DISTRO     which WSL distro to install into (default: the WSL default)

& {
    $ErrorActionPreference = 'Stop'
    $repo = if ($env:FORGE_REPO) { $env:FORGE_REPO } else { 'Kirito70/erpnext-ai-forge' }

    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        Write-Host "WSL is not installed. In an Administrator PowerShell run:" -ForegroundColor Yellow
        Write-Host "    wsl --install -d Ubuntu"
        Write-Host "then restart Windows, open Ubuntu once to create your user, and re-run this command."
        return
    }

    # `wsl -l -q` prints UTF-16; strip the NULs before testing for output.
    $distros = @((wsl.exe -l -q) -replace "`0", '' | Where-Object { $_.Trim() })
    if ($distros.Count -eq 0) {
        Write-Host "WSL has no Linux distribution. Run:  wsl --install -d Ubuntu" -ForegroundColor Yellow
        Write-Host "then open Ubuntu once to create your user, and re-run this command."
        return
    }

    $distroArgs = @()
    if ($env:FORGE_WSL_DISTRO) { $distroArgs = @('-d', $env:FORGE_WSL_DISTRO) }

    # Hand settings to WSL through WSLENV rather than the command line, so the
    # token never appears in a process listing and nothing needs shell quoting.
    $pass = @(@('FORGE_INVITE', 'FORGE_GITHUB_TOKEN', 'FORGE_REPO', 'FORGE_VERSION') |
        Where-Object { [Environment]::GetEnvironmentVariable($_) })
    $env:FORGE_REPO = $repo
    if ($pass -notcontains 'FORGE_REPO') { $pass += 'FORGE_REPO' }
    $previousWslEnv = $env:WSLENV
    $env:WSLENV = (@($pass | ForEach-Object { "$_/u" }) + @($previousWslEnv | Where-Object { $_ })) -join ':'

    # Download install.sh on the Windows side and run the file inside WSL:
    # passing a script as an argument would go through Windows PowerShell 5.1's
    # native-argument quoting, which mangles embedded double quotes.
    $tmp = Join-Path $env:TEMP 'forge-install.sh'
    if ($env:FORGE_GITHUB_TOKEN) {
        $headers = @{ Authorization = "Bearer $env:FORGE_GITHUB_TOKEN"; Accept = 'application/vnd.github.raw' }
        Invoke-WebRequest -UseBasicParsing -Headers $headers -OutFile $tmp `
            -Uri "https://api.github.com/repos/$repo/contents/scripts/install.sh"
    } else {
        Invoke-WebRequest -UseBasicParsing -OutFile $tmp `
            -Uri "https://github.com/$repo/releases/latest/download/install.sh"
    }
    $wslPath = (wsl.exe @distroArgs -e wslpath -a ($tmp -replace '\\', '/')).Trim()

    Write-Host "==> installing erpnext-ai-forge into your WSL distro" -ForegroundColor Cyan
    try {
        wsl.exe @distroArgs -e bash $wslPath
        if ($LASTEXITCODE -ne 0) { throw "installer exited with code $LASTEXITCODE" }
        Write-Host ""
        Write-Host "Done. Open your WSL shell (e.g. 'wsl' or the Ubuntu app) and run: forge --help" -ForegroundColor Green
    }
    finally {
        $env:WSLENV = $previousWslEnv
        Remove-Item -Force -ErrorAction SilentlyContinue $tmp
    }
}
