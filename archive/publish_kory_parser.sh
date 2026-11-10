#!/usr/bin/env bash
# Export only the parser project to its independent Git repository.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash archive/publish_kory_parser.sh [--push] [--branch NAME] [--message TEXT]
                                        [--remote URL]

Without --push, show the proposed changes without committing or uploading.
--push          Commit and push the parser snapshot.
--branch NAME   Destination branch (default: main). Use a new branch for a PR.
--message TEXT  Commit message (default: Update Kory Parser).
--remote URL    Destination repository (default: https://github.com/styglab/kory-parser.git).

Each run clones main into a temporary directory and mirrors the parser project.
Remote-only files are removed from that snapshot. Keep public repository files
in archive/kory_parser/ so that subsequent uploads preserve them.
The temporary clone is removed on exit. Teoria's Git state is never modified.
EOF
}

fail() { echo "Error: $*" >&2; exit 1; }

publish=false
branch=main
message='Update Kory Parser'
remote=https://github.com/styglab/kory-parser.git
while (($#)); do
  case "$1" in
    --push) publish=true; shift ;;
    --branch|--message|--remote)
      (($# >= 2)) && [[ -n "$2" ]] || fail "$1 requires a value"
      case "$1" in
        --branch) branch=$2 ;;
        --message) message=$2 ;;
        --remote) remote=$2 ;;
      esac
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

git check-ref-format --branch "$branch" >/dev/null || fail 'Invalid branch name'
[[ "$branch" != -* && "$branch" != 'HEAD' && "$branch" != '@{-'* ]] || fail 'Invalid branch name'
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source_dir="$script_dir/kory_parser"
files=(.gitignore README.md pyproject.toml uv.lock LICENSE NOTICE src docs third_party)
for name in "${files[@]}"; do
  [[ -e "$source_dir/$name" ]] || fail "Missing parser input: $name"
  [[ ! -L "$source_dir/$name" ]] || fail "Symlink in parser input: $name"
done
[[ -z "$(find "$source_dir/src" "$source_dir/docs" "$source_dir/third_party" -type l -print -quit)" ]] \
  || fail 'Symlinks in publication directories are not supported'

temporary_dir=$(mktemp -d "${TMPDIR:-/tmp}/kory_parser_publish.XXXXXXXX")
trap 'rm -rf -- "$temporary_dir"' EXIT
checkout="$temporary_dir/repository"
git clone --quiet --single-branch --branch main -- "$remote" "$checkout"
if [[ "$branch" != main ]]; then
  git -C "$checkout" switch --quiet -c "$branch"
fi

# Only this fresh temporary clone is cleared; parser input and Teoria stay intact.
git -C "$checkout" rm --quiet -r --ignore-unmatch -- .
tar -C "$source_dir" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
  -cf - -- "${files[@]}" | tar -C "$checkout" -xf -
git -C "$checkout" add --all -- .
git -C "$checkout" diff --cached --check
echo "Destination: $remote ($branch)"
git -C "$checkout" diff --cached --stat
if git -C "$checkout" diff --cached --quiet; then
  echo 'No parser changes to upload.'
  exit 0
fi
if [[ "$publish" == false ]]; then
  echo 'Preview only. Add --push to commit and upload these changes.'
  exit 0
fi

git -C "$checkout" commit --quiet -m "$message"
git -C "$checkout" push origin "HEAD:refs/heads/$branch"
echo "Uploaded $(git -C "$checkout" rev-parse --short HEAD) to $branch."
if [[ "$branch" != main ]]; then
  echo "Create a pull request from $branch to main on GitHub."
fi
