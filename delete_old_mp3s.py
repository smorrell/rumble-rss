
import subprocess
import sys
from pathlib import Path


BRANCH = "master"
BACKUP_BUNDLE = "before-purge.bundle"
PATHS_FILE = "removed_historical_paths.txt"


def git(*args, capture=True):
    return subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )


def main():
    try:
        # Require a clean working tree.
        status = git("status", "--porcelain").stdout
        if status.strip():
            print("ERROR: Commit or stash changes before running.")
            sys.exit(1)

        # Ensure master exists locally.
        git("rev-parse", "--verify", BRANCH)

        # Back up all refs and reachable history.
        git("bundle", "create", BACKUP_BUNDLE, "--all")
        print(f"Backup created: {BACKUP_BUNDLE}")

        # Paths present anywhere in master history.
        history = git(
            "log", "--format=", "--name-only", BRANCH
        ).stdout

        historical_paths = {
            line for line in history.splitlines() if line
        }

        # Paths in the current master tree.
        current = git(
            "ls-tree", "-r", "--name-only", BRANCH
        ).stdout

        current_paths = {
            line for line in current.splitlines() if line
        }

        # Historical paths absent from current master.
        removed = sorted(historical_paths - current_paths)

        if not removed:
            print("No obsolete historical paths found.")
            return

        Path(PATHS_FILE).write_text(
            "".join(path + "\n" for path in removed),
            encoding="utf-8",
        )

        print(f"Paths to remove from history: {len(removed)}")
        for path in removed:
            print(path)

        confirm = input(
            "\nRewrite Git history to remove these paths? Type YES: "
        )
        if confirm != "YES":
            print("Cancelled. Repository unchanged.")
            return

        # Require git-filter-repo.
        subprocess.run(
            ["git", "filter-repo", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )

        # Build a path-filter command. Each --path is an exact path.
        command = [
            "git", "filter-repo",
            "--paths-from-file", PATHS_FILE,
            "--invert-paths",
        ]

        subprocess.run(command, check=True)

        print("\nHistory rewritten.")
        print("Review the repository and verify the result.")
        print("The backup bundle is available for recovery.")

    except FileNotFoundError as exc:
        print(f"Required command not found: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
