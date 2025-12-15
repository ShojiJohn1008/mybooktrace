# Kashidashi Flask App

ローカルにある `kashidashi1215.db` を使って、貸出ログを追加する簡単なFlaskアプリです。

動作手順（macOS / zsh）:

1. 仮想環境（任意）を有効にする:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 依存をインストール:

```bash
pip install -r requirements.txt
```

3. アプリ実行:

```bash
python app.py
```

4. ブラウザで `http://127.0.0.1:5000/` にアクセスし、フォームから `LOAN_LOGS` に記録を追加できます。

注意:
- `kashidashi1215.db` はこのリポジトリのルート（`app.py` と同じ場所）に置いてください。
- 本番では `SECRET_KEY` を変更してください。
