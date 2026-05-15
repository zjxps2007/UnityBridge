#!/bin/sh
set -eu

REPO="zjxps2007/UnityBridge"
VERSION="latest"
INSTALL_DIR="${HOME}/.local/bin"
ASSET_NAME=""
PACKAGE_SPEC="git+https://github.com/zjxps2007/UnityBridge.git"
PYTHON_MODE=0
NO_PATH_UPDATE=0

usage() {
    cat <<'EOF'
Install or update UnityBridge for macOS/Linux.

Usage:
  sh install.sh [options]

Options:
  --repo OWNER/NAME          GitHub repository. Default: zjxps2007/UnityBridge
  --version VERSION         Release tag or latest. Default: latest
  --install-dir DIR         Install directory. Default: ~/.local/bin
  --asset-name NAME         Override release asset name.
  --python-mode             Install the Python package instead of standalone binary.
  --package-spec SPEC       Python pip package spec. Implies --python-mode.
  --no-path-update          Do not append install dir to shell rc files.
  -h, --help                Show this help.
EOF
}

require_value() {
    if [ "$#" -lt 2 ]; then
        echo "$1 requires a value." >&2
        exit 2
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo)
            require_value "$@"
            REPO="$2"
            shift 2
            ;;
        --version)
            require_value "$@"
            VERSION="$2"
            shift 2
            ;;
        --install-dir)
            require_value "$@"
            INSTALL_DIR="$2"
            shift 2
            ;;
        --asset-name)
            require_value "$@"
            ASSET_NAME="$2"
            shift 2
            ;;
        --python-mode)
            PYTHON_MODE=1
            shift
            ;;
        --package-spec)
            require_value "$@"
            PACKAGE_SPEC="$2"
            PYTHON_MODE=1
            shift 2
            ;;
        --no-path-update)
            NO_PATH_UPDATE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

step() {
    printf '==> %s\n' "$1"
}

download() {
    url="$1"
    output="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$output"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$output" "$url"
    else
        echo "curl or wget is required to download UnityBridge." >&2
        exit 1
    fi
}

asset_for_current_platform() {
    os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
    case "$os_name" in
        darwin|linux)
            ;;
        *)
            echo "Unsupported OS: $os_name. Use install.ps1 on Windows." >&2
            exit 1
            ;;
    esac

    machine="$(uname -m)"
    case "$machine" in
        x86_64|amd64)
            arch="amd64"
            ;;
        arm64|aarch64)
            arch="arm64"
            ;;
        *)
            echo "Unsupported architecture: $machine" >&2
            exit 1
            ;;
    esac

    printf 'unity-bridge-%s-%s' "$os_name" "$arch"
}

path_contains() {
    case ":${PATH:-}:" in
        *":$1:"*) return 0 ;;
        *) return 1 ;;
    esac
}

add_path_entry() {
    entry="$1"
    if [ "$NO_PATH_UPDATE" -eq 1 ] || path_contains "$entry"; then
        return
    fi

    shell_name="$(basename "${SHELL:-sh}")"
    case "$shell_name" in
        zsh) rc_file="${HOME}/.zshrc" ;;
        bash) rc_file="${HOME}/.bashrc" ;;
        *) rc_file="${HOME}/.profile" ;;
    esac

    line="export PATH=\"$entry:\$PATH\""
    touch "$rc_file"
    if ! grep -Fqx "$line" "$rc_file"; then
        printf '\n%s\n' "$line" >> "$rc_file"
        printf 'Added %s to PATH in %s. Restart the shell to apply it.\n' "$entry" "$rc_file"
    fi
}

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                printf '%s' "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

python_scripts_dir() {
    "$1" -c 'import os, site, sysconfig
paths = []
def add(path):
    if path and path not in paths:
        paths.append(path)
add(sysconfig.get_path("scripts"))
try:
    add(sysconfig.get_path("scripts", "posix_user"))
except Exception:
    pass
try:
    add(os.path.join(site.getuserbase(), "bin"))
except Exception:
    pass
print(paths[0] if paths else "")'
}

install_python_package() {
    step "Finding Python 3.10+"
    python_cmd="$(find_python || true)"
    if [ -z "$python_cmd" ]; then
        echo "Python 3.10 or newer was not found. Use standalone mode or install Python first." >&2
        exit 1
    fi

    step "Installing UnityBridge Python package"
    "$python_cmd" -m pip install --upgrade "$PACKAGE_SPEC"

    script_dir="$(python_scripts_dir "$python_cmd")"
    if [ -n "$script_dir" ]; then
        add_path_entry "$script_dir"
        PATH="$script_dir:$PATH"
        export PATH
    fi

    printf '\nUnityBridge Python package is installed.\n'
    printf 'Try: unity-bridge status\n'
    printf 'Fallback: python -m unity_bridge status\n'
}

install_standalone() {
    if [ -z "$ASSET_NAME" ]; then
        ASSET_NAME="$(asset_for_current_platform)"
    fi

    if [ "$VERSION" = "latest" ] || [ -z "$VERSION" ]; then
        url="https://github.com/${REPO}/releases/latest/download/${ASSET_NAME}"
    else
        url="https://github.com/${REPO}/releases/download/${VERSION}/${ASSET_NAME}"
    fi

    step "Downloading ${ASSET_NAME}"
    mkdir -p "$INSTALL_DIR"
    temp_file="$(mktemp "${TMPDIR:-/tmp}/unity-bridge.XXXXXX")"
    trap 'rm -f "$temp_file"' EXIT INT TERM
    download "$url" "$temp_file"

    target="${INSTALL_DIR}/unity-bridge"
    mv "$temp_file" "$target"
    chmod +x "$target"
    trap - EXIT INT TERM

    if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
        xattr -d com.apple.quarantine "$target" >/dev/null 2>&1 || true
    fi

    add_path_entry "$INSTALL_DIR"
    PATH="$INSTALL_DIR:$PATH"
    export PATH

    step "Verifying unity-bridge"
    "$target" --help >/dev/null

    printf '\nUnityBridge standalone CLI is installed.\n'
    printf 'Install path: %s\n' "$target"
    printf 'Try: unity-bridge status\n'
}

if [ "$PYTHON_MODE" -eq 1 ]; then
    install_python_package
else
    install_standalone
fi
