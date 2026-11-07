"""Small git helpers shared by the git/publish tests."""
import subprocess
from pathlib import Path


def git(cwd, *args, check=True):
    # UTF-8 explicitly: without it Windows decodes git's output with the ANSI code page.
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def write(root, relative, text="x\n"):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def remote_log(repo):
    remote = Path(git(repo, "remote", "get-url", "origin"))
    if not remote.is_absolute():
        remote = Path(repo) / remote
    # --git-dir is explicit, so it works even when the user's git has safe.bareRepository=explicit
    # (running "git log" with a bare repository as the working directory is refused then).
    return git(repo, "--git-dir", str(remote), "log", "--format=%s", "main").splitlines()
