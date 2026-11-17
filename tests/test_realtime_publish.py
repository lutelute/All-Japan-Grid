"""毎時の公開(scripts/realtime_publish.sh)は、日別断面のうち今日と昨日と一覧だけを積む(2026-11-17)。

前は全日分をコピーしていたので、回の初めより後に main へ入った過去の日の直し(PR #184 の並べ直し)を、
回の初めに取り出した古い日で上書きした(11-17 11:12 の公開で 82 日分が古い基準の版に戻った)。
"""
from pathlib import Path

PUB = Path(__file__).resolve().parents[1] / "scripts" / "realtime_publish.sh"


def test_publish_copies_only_today_yesterday_and_manifest():
    s = PUB.read_text(encoding="utf-8")
    assert 'days/*.json' not in s.split("git -C \"$PUB\" add")[0], "日別断面を全日分コピーしている"
    for w in ('TODAY_D=', 'YD_D=', 'for d in "$YD_D" "$TODAY_D" manifest'):
        assert w in s
