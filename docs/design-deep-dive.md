# エージェント設計と運用課題の詳細検討

> **ステータス**: 作業中 | 2026-06-03

## 1. エージェントアーキテクチャ

### 1.1 エージェント一覧と責務

| エージェント | トリガー | 書き込み先 | リスク | 承認モデル |
|------------|----------|-----------|--------|-----------|
| **connector-confluence** | 手動（初回インポート） | raw/confluence/ | 低 | 直接 push |
| **connector-sharepoint** | 定期（15〜60分） | raw/sharepoint/ | 低 | 直接 push |
| **connector-teams** | 定期 | raw/teams/ | 中（会話ログの機密性） | 直接 push、raw/ は admin only |
| **curator** | raw/ 更新検出時 | entities/, concepts/ | **高**（構造化品質・誤分類） | PR レビュー |
| **lint-checker** | PR 時 + 定期 | なし（レポートのみ） | 低 | CI 自動実行 |
| **freshness-checker** | 定期（日次） | 既存ページ更新 or PR | 中（誤判定） | PR レビュー |

### 1.2 パイプライン構成

```
[定期トリガー or webhook]
         │
         ▼
   connector-* （raw/ に pull）
         │
         ▼
   curator （raw/ → entities/concepts 再編成）
         │
         ▼
   lint-checker （CI。失敗 = ブロック）
         │
         ▼
   freshness-checker （鮮度評価 → 更新PR）
         │
         ▼
   Wiki.js 同期（5分以内に表示反映）
```

- **逐次実行**: Git が調整機構。並列書き込みは避ける
- **コネクタは直接 push**: リスク低、raw/ は Wiki.js 上で admin-only
- **編纂系は PR ベース**: curator / freshness-checker は branch → PR → CI → merge

### 1.3 Git コミッター設計

各エージェントに個別の Git ユーザーを割り当て、コミットログで追跡可能にする：

```
llm-wiki-bot <bot@llm-wiki.internal>          # 全般
curator-bot <curator@llm-wiki.internal>       # 編纂
connector-sp-bot <sp-connector@llm-wiki.internal>  # SharePoint
connector-teams-bot <teams-connector@llm-wiki.internal>
freshness-bot <freshness@llm-wiki.internal>
```

コミットメッセージ規約：
```
[curator] restructure raw/confluence/space-x → entities/projects/foo
[lint] fix broken wikilinks in concepts/architecture
[freshness] flag entities/teams/bar as stale (last updated 2025-12-01)
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
source: raw/confluence/space-engineering/page-42
source_url: https://confluence.internal/display/ENG/Arch
last_curated: 2026-06-03T14:00:00Z
curated_by: curator-bot
confidence: 0.85      # 編纂の確信度（0-1）
tags: [architecture, microservices, kubernetes]
related: [[entities/teams/platform]], [[concepts/k8s-best-practices]]
---
```

これにより：
- **来歴追跡**: どの raw ソースから生成されたか
- **鮮度判断**: last_curated と source の更新日を比較
- **信頼度表示**: confidence が低いものは人間レビューが必要
- **自動タグ**: エージェントが生成、人間が修正可能

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
| 0.2 | 手動 Markdown push → Wiki.js 反映 | エージェントの出力が Wiki.js でどう見えるか |
| 0.3 | OIDC 認証（EntraID シミュレーション） | ACL 連携の実現性 |
| 0.4 | Page Rules の挙動確認 | パスベース ACL が期待通り動作するか |
| 0.5 | raw/ → entities の手動変換テスト | 1 つの Confluence スペースを手動で Markdown 化し、curator の処理対象を模擬 |
| 0.6 | GraphQL API の操作テスト | エージェントが API 経由で Wiki.js を操作できるか |

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

2. **raw/ の扱い**: Wiki.js 上で raw/ は admin-only だが、Git 上ではエージェントが全アクセス。raw/ を Git サブモジュールにして物理的に分離すべきか？ あるいは単一リポジトリで ACL は Wiki.js に任せるか？

3. **エージェント実行環境**: Hermes cron job？ GitHub Actions？ GitLab CI？ オンプレ制約があるなら GitLab CI が現実的か。

4. **検索**: Wiki.js の組み込み検索（PostgreSQL FTS / Elasticsearch）は ACL を尊重する。だがエージェントが横断的に検索する場合、ACL をバイパスして Git の内容を直接 grep することになる。この「検索の二重構造」をどう説明するか。

5. **マルチテナント**: 今回の対象は 1 組織だが、将来複数組織が使う場合のテナント分離。Git リポジトリを組織ごとに分割？ Wiki.js インスタンスを組織ごとに立てる？
