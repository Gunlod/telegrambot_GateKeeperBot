# GateKeeperBot

Telegram グループへ参加したユーザーを Google スプレッドシートのブラックリストと照合し、一致すれば除外する polling 型の管理 Bot です。Python 3.12 以降を対象にしています。

## セットアップ

1. Python 3.12 以降で仮想環境を作成し、依存関係を入れます。

   ```bash
   python3.12 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```

2. `config.example.yaml` を `config.yaml` にコピーして、Bot Token・スプレッドシート URL・サービスアカウント JSON のパスを設定します。`config.yaml` と認証 JSON は Git の対象外です。

3. Google Cloud で Sheets API を有効化したサービスアカウントを作成し、そのサービスアカウントのメールアドレスに対象スプレッドシートの**編集者権限**を付与します。ブラックリストの読み込みに加え、参加ログを追記するためです。

4. `blacklist` ワークシートの 1 行目を、必ず次のヘッダーにします。

   | username | display_name | numeric_id | enabled | note |
   | --- | --- | --- | --- | --- |
   | @example_user |  |  | TRUE | spam account |
   |  | Example User |  | TRUE | trouble user |
   |  |  | 123456789 | TRUE | numeric ID match |

   `enabled` が `TRUE` の行だけが有効です。username、display_name、numeric_id は OR 条件で、いずれかの完全一致で対象になります。numeric ID は Telegram の数値 ID です。旧形式（numeric_id 列なし）のブラックリストは、次回の読み込み時に同列を自動追加します。

   入室ログ用シートは Bot がグループごとに自動作成します。シート名は既定で `join_log_<chat_id>` となり、接頭辞は `google.join_log_worksheet_prefix` で変更できます。各自動作成シートの 1 行目は次のヘッダーです。

   | username | display_name | numeric_id | joined_at |
   | --- | --- | --- | --- |

   自分自身を除く参加者ごとに、`@Gunlod` のような Telegram username、表示名、numeric ID、参加イベント時刻を UTC の ISO 8601 形式で追記します。username 未設定のユーザーは username 列を空欄にします。他 Bot も記録対象です。既存の 3 列ログシートは、次の書き込み時に numeric_id 列を自動追加します。ログ用シートへの書き込みが失敗しても、ブラックリスト照合・BAN 処理は継続します。

5. Bot を対象グループの管理者にし、**ユーザーを禁止（BAN）する権限**を付与します。プライバシーモードを無効化すると、参加イベントを確実に受け取れます。

6. 起動します。

   ```bash
   python main.py --config config.yaml
   ```

## 管理コマンド

グループ管理者だけが使用できます。

- `/blacklist_reload` — スプレッドシートを直ちに再取得します。
- `/blacklist_status` — 件数と最終正常更新時刻を表示します。

## 運用上の仕様

- 起動時に読み込み、以後 `blacklist.refresh_interval` 秒ごとに更新します（既定 60 秒）。取得に失敗しても最後の正常キャッシュを使い続けます。
- `telegram.action: ban` は再参加も防ぎます。`kick` は BAN 後ただちに unban し、再参加を許可します。`kick` の unban API 呼び出しに失敗した場合は安全側に倒れ、対象者は BAN 状態のままになり、エラーが記録されます。
- username は `@`・大小文字・前後空白を無視します。表示名は連続空白を半角 1 文字へ正規化して大小文字を区別せず、部分一致はしません。
- GateKeeperBot 自身は対象外です。他の Bot アカウントは通常ユーザーとして照合します。管理者は Telegram API 上 ban 不可のため検出時にログを残してスキップします。

## systemd の例

`/etc/systemd/system/gatekeeperbot.service`:

```ini
[Unit]
Description=GateKeeperBot
After=network-online.target

[Service]
Type=simple
User=gatekeeper
WorkingDirectory=/opt/gatekeeperbot
ExecStart=/opt/gatekeeperbot/.venv/bin/python /opt/gatekeeperbot/main.py --config /opt/gatekeeperbot/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

反映後に `sudo systemctl daemon-reload`、`sudo systemctl enable --now gatekeeperbot` を実行してください。
