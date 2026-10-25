"""regenerate_all は、追跡している入力が欠けていたら作り直す前に止める(issue #97・2026-10-26)。"""
import subprocess

from scripts.regenerate_all import missing_tracked_inputs


def _repo(tmp_path):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    for rel in ("data/stations/観測.json", "data/reference/b.json", "config/c.json", "docs/out.json"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    return git


def test_complete_checkout_has_nothing_missing(tmp_path):
    _repo(tmp_path)
    assert missing_tracked_inputs(str(tmp_path)) == []


def test_deleted_and_sparse_inputs_are_reported(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / "data/stations/観測.json").unlink()        # 名前が日本語でも拾う
    (tmp_path / "docs/out.json").unlink()                  # 出力の置き場は見ない
    git("update-index", "--skip-worktree", "config/c.json")  # sparse checkout で外したもの
    assert missing_tracked_inputs(str(tmp_path)) == ["config/c.json", "data/stations/観測.json"]


def test_without_git_it_cannot_tell(tmp_path):
    assert missing_tracked_inputs(str(tmp_path / "nogit")) is None
