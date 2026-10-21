#!/bin/bash
# eBay Research AI launcher for macOS (Apple Silicon / Intel)
set -u
cd "$(dirname "$0")" || exit 1

choose_python() {
  for c in python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; exit(0 if (3,11)<=sys.version_info[:2]<(3,14) else 1)' >/dev/null 2>&1; then
        command -v "$c"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(choose_python)" || {
  echo "Python 3.11 - 3.13 が見つかりません。python.org からインストールしてください。"
  echo "Install Python 3.11 - 3.13, then open run_mac.command again."
  read -r -p "Enterで終了..." _
  exit 1
}

if [ ! -x .venv_mac/bin/python ]; then
  echo "初回のPython環境を準備しています..."
  "$PYTHON" -m venv .venv_mac || {
    echo "仮想環境の作成に失敗しました。"
    read -r -p "Enterで終了..." _
    exit 1
  }
fi

if ! .venv_mac/bin/python -m pip install -r requirements.txt; then
  echo "ライブラリのインストールに失敗しました。インターネット接続を確認してください。"
  read -r -p "Enterで終了..." _
  exit 1
fi

echo "アプリを起動します。ブラウザが開かない場合 http://localhost:8501 を開いてください。"
echo "終了する場合は Control + C を押してください。"
.venv_mac/bin/python -m streamlit run app.py --server.address localhost
status=$?
echo "アプリが終了しました（終了コード: $status）。"
read -r -p "Enterで閉じる..." _
exit "$status"
