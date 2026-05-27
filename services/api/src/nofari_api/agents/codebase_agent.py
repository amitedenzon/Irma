"""Codebase observer — reads recent commits via async `git log` subprocess.

Per-commit `Signal(kind="commit", ...)` + one `kind="velocity_summary"` per
repo. Missing/non-git paths are logged and skipped (no crash).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import structlog

from nofari_api.models.signal import Signal

logger = structlog.get_logger(__name__)

# Record separator (\x1e) and field separator (\x1f) — control chars that
# never appear in commit messages, so we can safely split structured output.
_RS: Final[str] = "\x1e"
_FS: Final[str] = "\x1f"
_GIT_PRETTY: Final[str] = f"%H{_FS}%an{_FS}%aI{_FS}%s{_FS}%b{_RS}"


class CodebaseAgent:
    """Collect commit + velocity signals from every configured repo."""

    name = "codebase"

    def __init__(self, repos: list[Path], since: str = "3 days ago") -> None:
        self._repos = repos
        self._since = since

    async def collect(self) -> list[Signal]:
        valid_repos = [r for r in self._repos if self._is_git_repo(r)]
        if not valid_repos:
            return []
        results = await asyncio.gather(
            *(self._collect_one(repo) for repo in valid_repos),
            return_exceptions=False,
        )
        signals: list[Signal] = []
        for batch in results:
            signals.extend(batch)
        return signals

    @staticmethod
    def _is_git_repo(path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            logger.warning("codebase.repo_missing", path=str(path))
            return False
        if not (path / ".git").exists():
            logger.warning("codebase.not_a_repo", path=str(path))
            return False
        return True

    async def _collect_one(self, repo: Path) -> list[Signal]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
                "log",
                f"--since={self._since}",
                "--no-merges",
                "--date=iso-strict",
                f"--pretty=format:{_GIT_PRETTY}",
                "--numstat",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except (FileNotFoundError, PermissionError) as exc:
            logger.warning("codebase.git_unavailable", error=str(exc), repo=str(repo))
            return []

        if proc.returncode != 0:
            logger.warning(
                "codebase.git_log_failed",
                repo=str(repo),
                code=proc.returncode,
                stderr=stderr.decode(errors="replace").strip(),
            )
            return []

        signals = self._parse(repo, stdout.decode("utf-8", errors="replace"))
        signals.append(self._velocity_summary(repo, signals))
        return signals

    @staticmethod
    def _parse(repo: Path, raw: str) -> list[Signal]:
        """Parse the git-log stream from `_collect_one`.

        Output structure with `--pretty=format:%H..%b%x1e --numstat`::

            <header1>\\x1e\\n
            <numstat lines for commit1>\\n
            \\n
            <header2>\\x1e\\n
            <numstat lines for commit2>

        Splitting on `\\x1e` gives an array where index 0 is the first header
        and each subsequent chunk holds `<numstat of prev>\\n\\n<next header>`
        (or, for the trailing chunk, only the last commit's numstat). We walk
        lines and use the FS character — which only appears in headers — to
        find where the next header begins.
        """
        out: list[Signal] = []
        chunks = raw.split(_RS)
        if not chunks or _FS not in chunks[0]:
            return out

        headers: list[str] = [chunks[0]]
        trailers: list[str] = [""]

        for chunk in chunks[1:]:
            numstat_lines: list[str] = []
            header_lines: list[str] = []
            in_header = False
            for line in chunk.split("\n"):
                if not in_header and _FS in line:
                    in_header = True
                if in_header:
                    header_lines.append(line)
                else:
                    numstat_lines.append(line)
            # The collected numstat belongs to the PREVIOUS header.
            trailers[-1] = "\n".join(numstat_lines)
            if header_lines:
                headers.append("\n".join(header_lines))
                trailers.append("")

        for header, trailer in zip(headers, trailers, strict=True):
            fields = header.split(_FS)
            if len(fields) < 5:
                continue
            sha, author, iso_date, subject, body = fields[:5]
            try:
                ts = datetime.fromisoformat(iso_date)
            except ValueError:
                continue
            insertions, deletions, files_changed = _parse_numstat(trailer)
            out.append(
                Signal(
                    source="codebase",
                    kind="commit",
                    title=subject.strip(),
                    detail=body.strip(),
                    ts=ts,
                    meta={
                        "hash": sha,
                        "author": author,
                        "repo": repo.name,
                        "repo_path": str(repo),
                        "insertions": insertions,
                        "deletions": deletions,
                        "files_changed": files_changed,
                    },
                )
            )
        return out

    @staticmethod
    def _velocity_summary(repo: Path, commit_signals: list[Signal]) -> Signal:
        commits = [s for s in commit_signals if s.kind == "commit"]
        ins = sum(int(s.meta.get("insertions", 0)) for s in commits)
        dels = sum(int(s.meta.get("deletions", 0)) for s in commits)
        return Signal(
            source="codebase",
            kind="velocity_summary",
            title=f"{repo.name}: {len(commits)} commits / +{ins} / -{dels} over 3d",
            detail="",
            ts=datetime.now(UTC),
            meta={
                "repo": repo.name,
                "repo_path": str(repo),
                "commits": len(commits),
                "insertions": ins,
                "deletions": dels,
            },
        )


def _parse_numstat(block: str) -> tuple[int, int, int]:
    """Sum insertions + deletions and count file lines from a numstat block."""
    insertions = 0
    deletions = 0
    files = 0
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        ins_s, del_s, _path = parts[0], parts[1], parts[2]
        # Binary diffs report `-` for both — skip them silently.
        try:
            insertions += int(ins_s)
            deletions += int(del_s)
        except ValueError:
            pass
        files += 1
    return insertions, deletions, files
