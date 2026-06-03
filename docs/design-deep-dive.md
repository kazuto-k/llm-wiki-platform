# エージェント設計と運用課題の詳細検討

> **ステータス**: 作業中 | 2026-06-03

## 1. エージェントアーキテクチャ

### 1.1 エージェント一覧と責務

| エージェント | トリガー | 操作 | リスク | 公開モデル |
|------------|----------|------|--------|-----------|
| **connector-confluence** | 手動（初回インポート） | エクスポート XML を Markdown に変換し、適切なパスに `status: raw` で commit | 低 | Wiki.js ACL が即時適用 |
| **connector-sharepoint** | 定期（15〜60分） | SharePoint の新規/更新ドキュメントを取得し、branch 作成 → `status: raw` で commit | 低 | 同上 |
| **curator** | connector の branch への push でトリガー | 同一ファイルの `status: raw` → `status: curated` に変換。構造化・wikilink 付与 | **高** | auto-merge 即公開 + 著者通知 |
| **lint-checker** | curator の push でトリガー | schema 違反・重複・wikilink 切れをチェック。失敗 = merge ブロック | 低 | CI ゲート |
| **freshness-checker** | 定期（日次） | `status: curated` のファイルの鮮度を評価。必要なら更新 branch 作成 | 中 | auto-merge + 著者通知 |

### 1.2 パイプライン構成（CI 駆動）

エージェントは Git リポジトリの CI パイプラインとして実行される。Hermes cron のような外部スケジューラではなく、Git のイベント（push, schedule）で駆動する。

```
[定期スケジュール or SharePoint webhook]
         │
         ▼
   connector-sharepoint（CI job）
   新規/更新ドキュメントを取得
   branch: connector/sp/2026-06-03-1 を作成
   ファイルを status: raw で commit → push
         │
         ▼
   curator（CI job、branch への push でトリガー）
   同一 branch 上で status: raw → curated に変換
   frontmatter 補完、wikilink 付与、構造化
   commit → push
         │
         ├── lint-checker（CI job、curator の push でトリガー）
         │   失敗 → PR ブロック、curator に再処理指示
         │   成功 → 後続へ
         │
         ▼
   PR 作成 → auto-merge（lint 通過 = 即 merge）
         │
         ├── Wiki.js 同期（5分以内に表示反映）
         │
         └── 著者通知（source_author 宛）
              「あなたの文書が AI によって整理されました」
         │
         ▼
   freshness-checker（CI job、日次 schedule）
   status: curated のファイルを走査
   鮮度低下を検出 → 更新 branch 作成 → curator 同様のフロー
```

**設計上のポイント**:

- **raw は「場所」ではなく「状態」**: `raw/` ディレクトリは存在しない。status: raw は frontmatter の一時的な値であり、curator の処理を経て status: curated に遷移する
- **同一ファイル、同一パス**: connector が最初に正しいパス（entities/〜、concepts/〜）に配置する。curator はその場で内容を改善する。ファイルが移動しないので Wiki.js の ACL が一貫する
- **Git の working tree が作業場**: 外部の raw/ ステージング領域不要。branch 上の working tree で全処理が完結
- **イベント駆動**: connector の push → curator 起動 → lint 起動。Git の標準的な CI トリガーで連鎖

### 1.3 Git コミッター設計

各エージェントに個別の Git ユーザーを割り当て、コミットログで追跡可能にする：

```
curator-bot <curator@llm-wiki.internal>              # 編纂
connector-sp-bot <sp-connector@llm-wiki.internal>     # SharePoint
connector-conf-bot <conf-connector@llm-wiki.internal>  # Confluence
freshness-bot <freshness@llm-wiki.internal>           # 鮮度チェック
```

コミットメッセージ規約：
```
[curator] transform status: raw → curated
[curator] add wikilinks to entities/projects/foo
[connector-sp] import from https://sharepoint.internal/.../doc
[freshness] flag entities/teams/bar as stale (last updated 2025-12-01)
```

### 1.4 CI 実装戦略（Hermes 連携）

エージェントの実体は Hermes の `chat` コマンドでスキルを呼び出す形が最もシンプルで実用的。
3 段階の実装レベルを状況に応じて使い分ける。

#### レベル 1: 軽量（ワンライナー）

```yaml
# .github/workflows/curator.yml
curate:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: |
        hermes chat \
          --profile llm-wiki \
          --skill llm-wiki-curator \
          -q "branch 上の status: raw の全ファイルを curated に変換し、commit して push せよ"
```

単発の変換、シンプルな curator に適する。

#### レベル 2: 標準（スキル + プロファイル分離）

| スキル | プロファイル | 役割 |
|--------|------------|------|
| `llm-wiki-connector-sp` | `llm-wiki-connector` | SharePoint の新規/更新ドキュメントを取得、branch 作成、status: raw で commit |
| `llm-wiki-curator` | `llm-wiki-curator` | status: raw → curated 変換、構造化、wikilink 付与 |
| `llm-wiki-freshness` | `llm-wiki-freshness` | 鮮度評価、更新 branch 作成 |
| `llm-wiki-lint` | `llm-wiki-lint` | schema 検証、重複検出、wikilink 整合性 |

プロファイルで API キー・モデル・ツールセットを分離することで：
- curator は高性能モデル（DeepSeek V4 Pro）、connector は軽量モデル（Flash）
- スキルごとに必要なツールだけを有効化しトークン消費を抑制
- エージェント間の権限分離（Git の committer と対応）

#### レベル 3: 本格（Hermes SDK）

複数ファイルのバッチ処理やステートフルなワークフローが必要になった場合。
`hermes_tools` を CI スクリプトから直接 import し、細粒度の制御を行う。

```python
# .github/scripts/curate.py
from hermes_tools import terminal, read_file, write_file, search_files

files = search_files(pattern="status: raw", target="content", path=".")
for f in files:
    content = read_file(f["path"])["content"]
    # LLM 処理...
    write_file(f["path"], curated_content)
terminal("git add -A && git commit -m '[curator] transform raw → curated' && git push")
```

#### 選択基準

```
始めはレベル 1 で十分。
スキルが複雑化してきたらレベル 2 に分割。
パフォーマンスや状態管理が必要になったらレベル 3 に移行。
```

---

## 2. Markdown メタデータ設計

エージェントが生成する Markdown に frontmatter でメタデータを埋め込む：

```yaml
---
title: "プロジェクト X アーキテクチャ概要"
type: entity          # entity | concept | comparison
entity_type: project  # person | team | project | technology | ...
status: curated       # raw | draft | curated | stale
source_url: https://confluence.internal/display/ENG/Arch  # 元文書の URL（raw の所在ではない）
source_author: alice@company.com    # 元の文書の著者。通知先
last_curated: 2026-06-03T14:00:00Z
curated_by: curator-bot
confidence: 0.85      # 編纂の確信度（0-1）
tags: [architecture, microservices, kubernetes]
related: [[entities/teams/platform]], [[concepts/k8s-best-practices]]
---
```

これにより：
- **来歴追跡**: source_url で元文書を参照可能。Git の初期コミットに生データが残る
- **鮮度判断**: last_curated と source_url 先の更新日を比較
- **信頼度表示**: confidence が低いものは人間レビューが必要
- **自動タグ**: エージェントが生成、人間が修正可能
- **著者追跡**: source_author を元の文書から引き継ぎ、通知先として使用

### 2.1 著者フィードバックモデル（中核設計）

**原則: 事前レビューではなく、著者への事後通知と修正機会の提供。**

#### なぜ事前レビューをしないか

全件事前承認は回らない。**Confluence が死んだのと同じ理由**——人間はドキュメントをレビューしない。curator が日次で数十の PR を生成したら、レビューキューが溜まり、誰も見なくなり、結局 auto-merge 運用になるのが目に見えている。

#### 代わりに何をするか

```
curator がページ生成
      │
      ▼
lint-checker 通過（CI ゲート）
      │
      ▼
auto-merge → Wiki.js に即公開
      │
      ▼
source_author に通知:
  「あなたが書いた [元文書] を AI が整理し、
   以下のページを生成しました:
   - entities/projects/foo
   - concepts/architecture/bar
   問題があれば直接編集してください。
   編集内容は curator の次回更新より優先されます。」
      │
      ▼
著者が修正 → Git に commit → それが正
著者が無視   → curator の出力がそのまま残る（confidence は低めに表示）
著者が「確認済み」→ status: verified になる
```

#### 通知の設計

| 項目 | 内容 |
|------|------|
| **通知先** | source_author（元文書の著者） |
| **通知手段** | Teams / メール（コネクタが著者情報を取得できる場合） |
| **通知タイミング** | curator の処理完了直後 |
| **通知内容** | 元文書のタイトル、生成されたページへのリンク、修正方法の案内 |
| **リマインダー** | 1 週間後に未確認のものだけ再通知 |
| **エスカレーション** | 1 ヶ月未確認 → ページに「未確認」バッジ表示 |

#### 著者不在の問題

著者が退職・異動している場合、source_author が無効になる。その場合：
- 部署のグループ宛に通知（SharePoint の所属グループ情報から）
- それもできない場合は「著者不在」フラグを立て、admin が確認

#### なぜ「書いた本人」なのか

- **ownership**: 自分の書いた文書がどう整理されたか、書いた本人が一番気にする
- **ドメイン知識**: 内容の正確さを判断できる唯一の存在
- **動機**: 自分の文書が「変な風に整理される」のは心理的に嫌なはずで、修正する動機が働く
- **スケーラビリティ**: 中央の「レビューア」を置くより、著者ごとに分散する方が回る

#### curator と人間の競合解決

1. curator がページを生成 → status: curated
2. 人間が編集 → curator はそれ以降、そのページの該当セクションを上書きしない
3. 人間が編集したことは Git diff で検出可能（curator-bot 以外の committer）
4. 人間の編集があったページは curator の更新対象から外れる（または「提案」モードに切り替わる）
5. 人間が「再編成してほしい」と明示的に要求した場合のみ curator が再介入

---

## 3. 運用上の課題と対策

### 3.0 Wiki.js との同期・ページ管理

**課題**: Wiki.js の Git 同期はデフォルト 5 分間隔。また Wiki.js は Git リポジトリ全体を専有する前提であり、サブディレクトリ運用は想定されていない。

**確認が必要な点（Phase 0 で実機検証）**:

| 確認項目 | 懸念 |
|---------|------|
| Git → Wiki.js の新規ページ反映 | raw/ や entities/ に push した Markdown が Wiki.js のページとして自動認識されるか？ ディレクトリ構造はページ階層にマッピングされるか？ |
| Wiki.js → Git の更新 | Wiki.js UI で人間が編集した内容が Git に push される時、ファイルパスは保持されるか？ |
| エージェント push と Wiki.js commit の競合 | エージェントが push した直後に Wiki.js が別の変更を commit しようとした場合、rebase/fast-forward で解決されるか？ |
| 同期エラーの通知 | Git 同期に失敗した場合（認証切れ、conflict 等）、Wiki.js 管理画面にエラー表示されるか？ |
| 大量ファイルの初回同期 | 数百ページを一括 push した場合の同期時間・メモリ使用量は実用的か？ |
| ファイル削除の反映 | Git で削除した Markdown ファイルは Wiki.js 側でもページ削除されるか？ |

**想定される問題と対策**:
- Wiki.js が期待するディレクトリ構造と llm-wiki の entities/concepts/raw 構造が衝突する可能性 → Wiki.js 側のナビゲーション設定で吸収、または Wiki.js が期待する構造に合わせる
- 5 分の同期遅延はドキュメント用途では許容範囲。即時性が必要なら GraphQL API で補完

### 3.1 編纂の競合

**課題**: 人間が Wiki.js UI でページを編集し、同時に curator が同じページを Git から更新。

**対策**:
- curator は必ず `git pull --rebase` してから作業
- コンフリクトしたら curator 側の変更を破棄し、人間の編集を優先
- 人間の編集があったことは freshness-checker が検出できる（Wiki.js の commit として Git に残る）

### 3.2 LLM API コスト

**課題**: 全 raw を読んで entities/concepts を生成するたびに API コールが発生。

**対策**:
- **差分処理**: raw/ の変更があったファイルだけを対象に
- **キャッシュ**: 同じ raw ソースから同じ内容なら再生成しない（content hash 比較）
- **段階的モデル**: connector は安価なモデル（DeepSeek V4 Flash）、curator は高性能モデル
- **バッチ化**: 複数 raw を一度のコンテキストで処理
- **コスト上限**: 月額予算を設定し超過時にアラート

試算（仮）:
```
connector: 100 raw ページ × 5K tokens × $0.0028/M = $1.40
curator: 20 新規 entity × 20K tokens × $0.01/M = $0.004
freshness: 200 ページ × 2K tokens × $0.0028/M = $1.12
──────────────────────────────────────────
1 サイクルあたり約 $2.50
1 日 6 サイクル + 日次 freshness = 約 $16/日 → 約 $500/月
```
実際のページ数と更新頻度に大きく依存。PoC で実測が必要。

### 3.3 鮮度判定の精度

**課題**: 何をもって「古い」と判断するか。単純な日付比較では誤検出が多い。

**鮮度シグナル（組み合わせて判定）**:
1. `last_curated` からの経過日数
2. source（raw/）の最終更新日との差分
3. wikilink 先のページが更新されているか（依存先が変われば自分も要更新）
4. 関連する外部ソース（SharePoint 原文等）の更新
5. 人間が「確認済み」マークをつけたか

**閾値設計**（初期案）:
```
1 ヶ月未満         → fresh（緑）
1〜3 ヶ月          → aging（黄）→ freshness-checker が確認
3〜6 ヶ月          → stale（橙）→ 更新 PR を自動生成
6 ヶ月以上          → critical（赤）→ 人間レビュー必須
依存先が更新された   → 即時に要確認フラグ
```

### 3.4 エージェントの失敗処理

| 失敗モード | 影響 | 対策 |
|-----------|------|------|
| connector API タイムアウト | raw/ 未更新 | 次サイクルでリトライ。3 回連続失敗で通知 |
| curator LLM エラー | raw が蓄積 | 次サイクルで再処理。蓄積量が閾値を超えたら通知 |
| lint 失敗 | PR ブロック | 人間が手動修正 or curator に再生成指示 |
| Git push 失敗（conflict） | 変更が失われる | 作業ディレクトリを破棄し再実行 |
| freshness-checker の誤判定 | 不要な更新 PR | PR を見た人間が close。パターンを学習 |

### 3.5 機密情報の漏洩防止

**課題**: エージェントは Git レベルで全ファイルを読める。機密 raw を誤って public entity に転載するリスク。

**対策**:
- **パスによるゲート**: raw/legal/* や raw/hr/* は curator の対象外にする（設定で制御）
- **lint ルール**: 生成された entity が制限パスのファイルを参照していないかチェック
- **機密スキャン**: クレジットカード番号、個人情報等の正規表現パターンを CI で検出
- **人間レビュー**: curator の出力は常に PR レビュー。機密情報が紛れていないか目視確認
- **raw/ は Wiki.js 上で admin only**: 一般ユーザーは raw/ を閲覧不可

### 3.6 サーキュラー依存と更新ループ

**課題**: 
- curator が entity A を更新 → freshness-checker が entity B（A に依存）を stale 判定 → 更新 → ...
- 連鎖的に全ページが更新対象になる

**対策**:
- freshness-checker の実行頻度を制限（日次）
- 同一ページの更新は最小間隔（例: 7 日）を設ける
- 依存先更新による stale フラグは「提案」レベルに留め、強制更新しない
- 更新連鎖の深さを制限（2 ホップまで）

### 3.7 Wiki.js フォークの保守負荷

**課題**: Wiki.js をフォークしてカスタマイズすると、upstream の更新追従が負荷になる。

**戦略**:
- コア改変は**極力避ける**。代わりに：
  - テーマカスタマイズ（CSS/JS 注入）
  - GraphQL API 経由の外部連携
  - Wiki.js のプラグイン機構があればそれを活用
- 本当に必要なコア改変だけを isolated commit として管理
- upstream のリリースノートを監視（Hermes Upstream Catchup パターン）
- 四半期ごとに rebase 評価

**現時点でコア改変が必要そうな項目**:
1. ナビゲーションのカスタマイズ（entities/concepts/raw の 3 ペイン表示）→ テーマで対応可能か要検証
2. エージェント編集の可視化（「このページは AI が編纂しました」バナー）→ frontmatter の `curated_by` を読み取るカスタムレンダラ
3. CI lint 結果のダッシュボード → 外部 Web アプリ + iframe 埋め込みで回避可能か

---

## 4. 実装優先順位

### Phase 0: 実機検証（最優先）

| # | 検証項目 | 目的 |
|---|---------|------|
| 0.1 | Wiki.js ローカルデプロイ + Git 連携 | 基本動作確認。ディレクトリ構造→ページ階層のマッピング確認 |
| 0.2 | 手動 Markdown push → Wiki.js 反映 | エージェントの出力が Wiki.js でどう見えるか。status: raw → curated の状態遷移を Wiki.js 上でどう表示するか |
| 0.3 | OIDC 認証（EntraID シミュレーション） | ACL 連携の実現性 |
| 0.4 | Page Rules の挙動確認 | パスベース ACL が期待通り動作するか。同一パスで状態だけ変わるファイルの権限は一貫するか |
| 0.5 | CI 環境の選定と疎通 | GitHub Actions / GitLab CI / Gitea Actions の比較。LLM API へのアクセス可否、オンプレ適合性 |
| 0.6 | connector → curator の CI 連鎖テスト | branch 作成 → push → 別 job が同一 branch で追従コミット → PR 作成 の一連の流れが実現可能か |
| 0.7 | 1 つの Confluence スペースを手動で Markdown 化し curator の処理対象を模擬 | 実際のデータで品質検証 |

### Phase 1: 基盤（設計確定後）

| # | 項目 |
|---|------|
| 1.1 | Git リポジトリ構造の確定とテンプレート |
| 1.2 | Wiki.js フォーク作成、最小カスタマイズ |
| 1.3 | Page Rules テンプレート（YAML → Wiki.js 設定） |
| 1.4 | Markdown frontmatter schema 定義と validator |
| 1.5 | CI/CD パイプライン骨格（Git 操作、エージェント実行環境） |

### Phase 2: エージェント

| # | 項目 |
|---|------|
| 2.1 | connector-confluence（XML → Markdown） |
| 2.2 | curator PoC（1 スペースを AI 再編成し品質評価） |
| 2.3 | lint-checker（schema 違反、wikilink 切れ、重複検出） |
| 2.4 | freshness-checker（シグナル収集 + 判定 + PR 生成） |

### Phase 3: 運用

| # | 項目 |
|---|------|
| 3.1 | connector-sharepoint（Graph API） |
| 3.2 | connector-teams |
| 3.3 | 通知システム（変更サマリー、レビュー依頼） |
| 3.4 | ダッシュボード |
| 3.5 | 定期実行スケジューラ |

---

## 5. 未解決の問い

1. **Wiki.js のページ階層と llm-wiki ディレクトリ構造のマッピング**: Wiki.js のナビゲーションは folder/page の 2 階層。entities/teams/platform.md は `entities > teams > platform` になるか？ それとも独自のナビゲーション構造を定義する必要があるか？ → Phase 0 で確認

2. **CI 実行環境**: どの CI を使うか。GitHub Actions（クラウド）、GitLab CI（オンプレ可）、Gitea Actions（軽量オンプレ）。オンプレ制約と LLM API へのアクセス経路を考慮する必要がある。

3. **connector のパス決定ロジック**: SharePoint のドキュメントを取得したとき、どのパス（entities/〜、concepts/〜）に配置するかを connector がどう判断するか。SharePoint のサイト構造やメタデータから推測するのか、それとも connector は常に特定のパスに置き curator が移動も行うのか。

4. **検索**: Wiki.js の組み込み検索（PostgreSQL FTS / Elasticsearch）は ACL を尊重する。だがエージェントが横断的に検索する場合、ACL をバイパスして Git の内容を直接 grep することになる。この「検索の二重構造」をどう説明するか。

5. **マルチテナント**: 今回の対象は 1 組織だが、将来複数組織が使う場合のテナント分離。Git リポジトリを組織ごとに分割？ Wiki.js インスタンスを組織ごとに立てる？

6. **著者通知の実現手段**: source_author をどこから取得するか。SharePoint の場合は Graph API の `createdBy` で取れる。Confluence の場合はエクスポート XML に author 情報が含まれるか要確認。これらを connector が確実に取得し frontmatter に書き込めるかは要検証。

7. **確認済みステータスの管理**: 著者が「確認済み」にした場合、その状態をどこに保存するか。Markdown frontmatter に `status: verified` と `verified_by: alice@company.com`、`verified_at: 日時` を書く。Git の commit として残るので監査可能。著者が Wiki.js UI で編集した場合、どうやってその編集が「確認」を意味するのかを判定する必要がある（単なる typo 修正かもしれない）。
