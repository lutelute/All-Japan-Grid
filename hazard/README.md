# hazard — 地震ハザード

All-Japan-Grid の正典モデルの上で、地震が起きたときの停電と復旧を解く。
1 つの地震を 1 つのプロジェクトとして扱い、コード・設定・データ・レポート・スライド・成果物をその地震のディレクトリにまとめる。
All-Japan-Grid 本体(`docs/`・`src/`)には置かない。

| ディレクトリ | 地震 |
|---|---|
| [nankai/](nankai/README.md) | 南海トラフ巨大地震(J-SHIS 最大クラス Mw9.1 + A40 津波)。北海道 2018・福島 2022 のヒンドキャストは南海の手法の検証としてここに含む |

別の地震を始めるときは `hazard/<名前>/` を作り、南海と同じ並び(`config/ src/ scripts/ tests/ data/ docs/ reports/ slides/`)にする。
