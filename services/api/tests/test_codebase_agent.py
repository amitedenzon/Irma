"""CodebaseAgent exercised against a real git repo in a tmp dir."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from nofari_api.agents.codebase_agent import CodebaseAgent


def _have_git() -> bool:
    return shutil.which("git") is not None


@pytest.mark.skipif(not _have_git(), reason="git unavailable")
def test_codebase_agent_collects_commits_and_velocity(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    run("init", "-q", "-b", "main")
    run("config", "commit.gpgsign", "false")

    (repo / "a.txt").write_text("hello\n")
    run("add", "a.txt")
    run("commit", "-m", "first commit\n\nbody line", "--no-gpg-sign")

    (repo / "a.txt").write_text("hello\nworld\nthird\n")
    run("add", "a.txt")
    run("commit", "-m", "extend a.txt", "--no-gpg-sign")

    agent = CodebaseAgent(repos=[repo])
    signals = asyncio.run(agent.collect())

    commit_signals = [s for s in signals if s.kind == "commit"]
    velocity_signals = [s for s in signals if s.kind == "velocity_summary"]

    assert len(commit_signals) == 2
    assert len(velocity_signals) == 1

    titles = {s.title for s in commit_signals}
    assert "first commit" in titles
    assert "extend a.txt" in titles

    velocity = velocity_signals[0]
    assert velocity.meta["commits"] == 2
    assert velocity.meta["insertions"] >= 3  # 1 initial line + 2 extensions


@pytest.mark.skipif(not _have_git(), reason="git unavailable")
def test_codebase_agent_skips_non_git_path(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    agent = CodebaseAgent(repos=[not_a_repo, tmp_path / "missing"])
    signals = asyncio.run(agent.collect())
    assert signals == []
