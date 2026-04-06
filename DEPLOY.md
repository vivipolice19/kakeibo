# デプロイ手順（上から順にやる）

---

## 初めて公開するとき

**ステップ 1**　ブラウザで **https://github.com** を開き、ログインする。

**ステップ 2**　右上の **＋** → **New repository** を押す。リポジトリ名を決めて **Create repository** する（空のリポジトリができる）。

**ステップ 3**　パソコンで **PowerShell** を開く。次を実行する（`ユーザー名` と `リポジトリ名` はステップ 2 で作った名前に合わせる）。

```powershell
cd C:\Users\pskit\Downloads\s-system-kakeibo
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/ユーザー名/リポジトリ名.git
git push -u origin main
```

**ステップ 4**　ブラウザで GitHub のそのリポジトリを開き、**`app.py`** と **`requirements.txt`** が一覧に出ているか確認する。出ていれば OK。

**ステップ 5**　ブラウザで **https://dashboard.render.com** を開き、ログインする。

**ステップ 6**　**New** → **Web Service** を押す。

**ステップ 7**　GitHub を連携し、**ステップ 2 で作ったリポジトリ** を選び **Connect** を押す。

**ステップ 8**　画面の入力欄を次のようにする。

- **Runtime** → **Python 3**
- **Build Command** → `pip install -r requirements.txt`
- **Start Command** → `gunicorn --bind 0.0.0.0:$PORT --workers 1 app:app`
- **Instance type** → **Free**

**ステップ 9**　**Create Web Service** を押す。終わるまで待つ。

**ステップ 10**　画面上に出る **https://……onrender.com** をブラウザで開く。家計簿が表示されれば完了。

---

## コードを直したあと（2 回目以降）

**ステップ 1**　PowerShell で次を順に実行する。

```powershell
cd C:\Users\pskit\Downloads\s-system-kakeibo
git status
git log -1 --oneline
git push
```

**ステップ 2**　**https://dashboard.render.com** を開く → この家計簿のサービスを開く → **Manual Deploy** → **Deploy latest commit** を押す → 終わるまで待つ。

**ステップ 3**　ブラウザでアプリの URL を開く。古い画面が出るときは末尾に **`?v=2`** を付ける（例：`https://○○○.onrender.com/?v=2`）。次からは `?v=3` のように数字を変えてもよい。

---

## 補足

- フォルダの場所が違うときは、`cd` の行だけ自分のパスに変える。
- 無料プランは、しばらく使わないと最初の表示が遅いことがある。サーバー上のデータは消えることがあるので、大事なデータはアプリの CSV で保存する。
