#!/usr/bin/env bash
# erpnext-ai-forge installer — read-only install of a tagged release.
#
#   curl -fsSL https://github.com/Kirito70/erpnext-ai-forge/releases/latest/download/install.sh | bash
#
# Installs into ~/.local/share/erpnext-ai-forge/<version>, points `current` at
# it, and puts a `forge` wrapper in ~/.local/bin. Re-run to upgrade.
#
# Options (flags after `bash -s --` when piped):
#   --version vX.Y.Z   install a specific release (default: latest)
#   --uninstall        remove the wrapper and every installed version (keeps config)
#
# Environment:
#   FORGE_GITHUB_TOKEN   read-only token, needed only if the repo is private;
#                        used for this run, never written to disk
#   FORGE_BENCH_PATH     bench path   } skip the prompts (non-interactive installs)
#   FORGE_PRIMARY_SITE   site name    }
#   FORGE_INSTALL_DIR    default ~/.local/share/erpnext-ai-forge
#   FORGE_BIN_DIR        default ~/.local/bin
#   FORGE_CONFIG_DIR     default ~/.config/erpnext-ai-forge
#
# Why a git clone, not a tarball: generated files stamp the commit that last
# touched their source, which needs history. A blobless clone has full history
# at a fraction of the size.
set -euo pipefail

REPO="Kirito70/erpnext-ai-forge"
INSTALL_DIR="${FORGE_INSTALL_DIR:-$HOME/.local/share/erpnext-ai-forge}"
BIN_DIR="${FORGE_BIN_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${FORGE_CONFIG_DIR:-$HOME/.config/erpnext-ai-forge}"
CONFIG_FILE="$CONFIG_DIR/env"
WRAPPER="$BIN_DIR/forge"
WRAPPER_MARKER="# erpnext-ai-forge wrapper"
# Directories forge writes into at runtime; everything else is made read-only.
WRITABLE_DIRS=(audit discovery forge/.venv .git)

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

has_tty() { [[ -r /dev/tty ]] && (exec </dev/tty) 2>/dev/null; }

ask() {  # ask <prompt> <default> -> echoes answer
    local prompt=$1 default=$2 reply=""
    has_tty || die "no terminal to prompt on; set FORGE_BENCH_PATH and FORGE_PRIMARY_SITE"
    read -r -p "$prompt${default:+ [$default]}: " reply </dev/tty
    printf '%s' "${reply:-$default}"
}

github_api() {  # github_api <path>
    local auth=()
    [[ -n "${FORGE_GITHUB_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer $FORGE_GITHUB_TOKEN")
    curl -fsSL "${auth[@]}" -H "Accept: application/vnd.github+json" "https://api.github.com/$1"
}

latest_version() {
    github_api "repos/$REPO/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1
}

uninstall() {
    if [[ -f "$WRAPPER" ]] && grep -qF "$WRAPPER_MARKER" "$WRAPPER"; then
        rm -f "$WRAPPER"
        say "removed $WRAPPER"
    fi
    if [[ -d "$INSTALL_DIR" ]]; then
        chmod -R u+w "$INSTALL_DIR"
        rm -r "$INSTALL_DIR"
        say "removed $INSTALL_DIR"
    fi
    say "config kept at $CONFIG_FILE (delete it by hand if you want)"
}

require_tools() {
    command -v git  >/dev/null || die "git is required; install it and re-run"
    command -v curl >/dev/null || die "curl is required; install it and re-run"
    command -v uv   >/dev/null && return
    [[ -x "$HOME/.local/bin/uv" ]] && { PATH="$HOME/.local/bin:$PATH"; return; }
    say "uv (Python package manager) is not installed"
    if has_tty; then
        local yn
        yn=$(ask "Install uv from https://astral.sh/uv now? (y/N)" "N")
        [[ "$yn" =~ ^[Yy] ]] || die "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
    else
        die "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null || die "uv installed but not on PATH; open a new shell and re-run"
}

clone_release() {  # clone_release <version> <dest>
    local version=$1 dest=$2 url="https://github.com/$REPO.git" git_auth=()
    if [[ -n "${FORGE_GITHUB_TOKEN:-}" ]]; then
        local basic
        basic=$(printf 'x-access-token:%s' "$FORGE_GITHUB_TOKEN" | base64 | tr -d '\n')
        git_auth=(-c "http.extraHeader=Authorization: Basic $basic")
    fi
    local tmp="$dest.partial"
    [[ -d "$tmp" ]] && { chmod -R u+w "$tmp"; rm -r "$tmp"; }
    say "downloading $version"
    git "${git_auth[@]}" clone --quiet --filter=blob:none --branch "$version" \
        -c advice.detachedHead=false "$url" "$tmp" \
        || die "could not clone $REPO at $version (private repo? set FORGE_GITHUB_TOKEN)"
    mv "$tmp" "$dest"
}

install_deps() {  # install_deps <dir>
    say "installing Python dependencies (first run downloads Python; takes a minute)"
    # Non-editable: nothing at runtime needs to build inside the read-only tree.
    (cd "$1/forge" && uv sync --frozen --no-editable --quiet)
}

lock_down() {  # lock_down <dir>
    local dir=$1 d
    chmod -R a-w "$dir"
    chmod u+w "$dir"          # so a later uninstall/upgrade can manage it
    for d in "${WRITABLE_DIRS[@]}"; do
        mkdir -p "$dir/$d"    # the top level is writable, nested ones already exist
        chmod -R u+w "$dir/$d"
    done
}

write_config() {
    mkdir -p "$CONFIG_DIR"
    # shellcheck disable=SC1090
    [[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE"
    local bench="${FORGE_BENCH_PATH:-}" site="${FORGE_PRIMARY_SITE:-}"
    if [[ -z "$bench" || -z "$site" ]]; then
        say "configure your bench"
        bench=$(ask "Absolute path to your Frappe bench" "$bench")
        site=$(ask "Primary site name" "$site")
    fi
    [[ "$bench" = /* ]] || die "bench path must be absolute: $bench"
    [[ -d "$bench/apps" ]] || warn "$bench/apps not found; is that a Frappe bench?"
    umask 077
    cat >"$CONFIG_FILE" <<EOF
# erpnext-ai-forge settings — read by the forge wrapper. Edit freely.
FORGE_BENCH_PATH=$(printf '%q' "$bench")
FORGE_PRIMARY_SITE=$(printf '%q' "$site")
EOF
    say "settings saved to $CONFIG_FILE"
}

write_wrapper() {
    mkdir -p "$BIN_DIR"
    if [[ -e "$WRAPPER" ]] && ! grep -qF "$WRAPPER_MARKER" "$WRAPPER"; then
        die "$WRAPPER exists and is not ours; move it aside and re-run"
    fi
    cat >"$WRAPPER" <<EOF
#!/usr/bin/env bash
$WRAPPER_MARKER — regenerated by install.sh; do not edit.
set -euo pipefail
set -a
# shellcheck disable=SC1091
source "$CONFIG_FILE"
set +a
# forge locates its canonical/ tree from the working directory.
cd "$INSTALL_DIR/current"
exec "$INSTALL_DIR/current/forge/.venv/bin/forge" "\$@"
EOF
    chmod 755 "$WRAPPER"
}

main() {
    local version="" action=install
    while [[ $# -gt 0 ]]; do
        case $1 in
            --version)   version=${2:?--version needs a value}; shift 2 ;;
            --uninstall) action=uninstall; shift ;;
            -h|--help)   sed -n '2,24p' "$0" 2>/dev/null || true; exit 0 ;;
            *)           die "unknown option: $1" ;;
        esac
    done
    [[ $action = uninstall ]] && { uninstall; return; }

    require_tools
    [[ -n "$version" ]] || version=$(latest_version) \
        || die "could not look up the latest release (private repo? set FORGE_GITHUB_TOKEN)"
    [[ -n "$version" ]] || die "no published release found for $REPO"

    mkdir -p "$INSTALL_DIR"
    local dest="$INSTALL_DIR/$version"
    if [[ -d "$dest" ]]; then
        say "$version already downloaded"
    else
        clone_release "$version" "$dest"
        install_deps "$dest"
        lock_down "$dest"
    fi
    ln -sfn "$version" "$INSTALL_DIR/current"

    write_config
    write_wrapper

    say "installed erpnext-ai-forge $version"
    # shellcheck disable=SC2016  # the printf prints a literal $PATH to paste
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) warn "$BIN_DIR is not on your PATH; add this to your shell profile:"
           printf '    export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
    esac
    cat <<EOF

Next:
  forge --version
  forge sync --all --dry-run     # preview what would be written to your bench
  forge sync --all               # write it

Upgrade: re-run the install command.  Remove: add --uninstall.
EOF
}

main "$@"
