# リポジトリ概要

- ルートに共通ビルドはない。`alf/`、`lamp/`、`interstellar-mission-control/`、`rufflecopter/` は、それぞれ独立した Compose プロジェクトとして扱う。
- CI、テストスイート、lint/formatter 設定、依存ロックファイルは存在しない。変更したサービスだけをビルドし、Compose で動作確認する。
- Compose の相対パスとプロジェクト名を揃えるため、コマンドは対象サービスのディレクトリで実行する。設定だけなら `docker compose config --quiet`、起動は `docker compose up`、停止と通常ボリュームの保持は `docker compose down`。
- `alf`、`interstellar-mission-control`、`rufflecopter` の Dockerfile は `faust.cs.fau.de:5000/*_deps` に依存する。レジストリへ接続・認証できない環境ではローカルビルドできない。

# サービス別の要点

## `alf/`

- Flask アプリの入口は `src:create_app()`。Gunicorn は `[::]:1986`、PostgreSQL は Compose の `db` を使用し、`DATA_PATH` と `DB_URL` は Compose でのみ設定される。
- 依存マニフェストはなく、Python/Typst 依存は外部の `alf_deps` イメージに入っている。確認は `docker compose build alf && docker compose up alf db`。
- 起動時にテーブルを作成する。cron は3分ごとに cleanup を実行し、20分超のユーザー、翻訳履歴、プロジェクトを削除するため、長時間の手動確認ではデータ消失を考慮する。

## `lamp/`

- 一般的なWebサーバーではない。`socat` が TCP/1337 の接続ごとに `entrypoint.sh` を実行し、`srv/main.tex` を XeLaTeX `--shell-escape` で走らせて HTTP を処理する。
- `./srv` はコンテナの `/srv` へ read-only bind mount されるため、TeX、静的ファイル、`srv/*.sh` の変更にイメージ再ビルドは不要。ルートの `entrypoint.sh`、`cleanup.sh`、Dockerfile の変更時は `docker compose build latex cleanup`。
- MariaDB/Redis の接続先と資格情報は `srv/main.tex` に固定されている。cleanup は5分ごとに動き、`/storage` の90分超のファイルを削除する。

## `interstellar-mission-control/`

- `imc/src/Makefile` が実質的なビルド定義。`make -C imc/src all` で `.neko` を `.n` にし、`make -C imc/src run` で単体実行、コンテナは `make socks` で Neko を TCP/8080 に公開する。
- 実行入口は `imc/src/imc.neko`、プロトコルの振り分けは `parser.neko`、SQLite は `/imc/data/db.db`。起動時に20分超の行が削除される。
- Dockerfile はソース一式をコピーするだけで native module を再ビルドしない。`file.ndll`、`sqlite.ndll`、`date.ndll` のC実装を変えた場合は Neko ヘッダー/ライブラリのある環境で `make -C imc/src buildlibs` が必要。`rand.ndll` には Makefile ルールがなく、既存バイナリを使用する。
- コンテナ確認は `docker compose build imc && docker compose up imc`。DB は名前付きボリューム `imc_db` に残る。

## `rufflecopter/`

- Rust の入口は `service/src/main.rs` だが、実際のアプリロジックとUIはチェックイン済みの `service/server.swf` と `service/content/` にある。SWF の生成元・生成手順はこのリポジトリにない。
- バイナリは作業ディレクトリから相対指定で `server.swf` を開く。ローカル実行時も `service/` から起動する。
- Rust の焦点確認は `cargo check --manifest-path service/Cargo.toml`。`Cargo.lock` はなく、Ruffle v0.6.0 の Git 依存を取得できるネットワークが必要。
- `docker-compose.yml` の `rufflecopter_deps` は存在しない `service/Dockerfile.deps` を参照するため、プロジェクト全体を `--build` してはいけない。変更時は `docker compose build rufflecopter` のみをビルドし、その後 `docker compose up` する。
- 公開ポートは host `35244` から container `8080`。Rust 側の特殊ソケット `127.0.13.37:31337` が実際の `[::]:8080` listener を作るため、この分岐を通常の外向き接続と同一視しない。
