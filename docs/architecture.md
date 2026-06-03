# アーキテクチャ設計

> **ステータス**: 初期設計 | 2026-06-03
> **派生元**: Hermes Design Notes/2026/experiments/2026-06-03-llm-wiki-organizational-deployment.md v5

## 1. 背景

- 現状: オンプレ Confluence（ディスコン → 移行必須）
- 移行先最有力候補: M365 SharePoint
- 根本問題: Confluence は玉石混交・検索性悪・情報の腐敗が深刻。SharePoint に移行しても同じ問題が再現する
- 仮説: AI 時代において「人間がドキュメントを積極的にメンテナンスする」モデル自体をやめるべき
- アプローチ: CMS ライクな自前ドキュメント基盤を構築し、その上に llm-wiki パターンをエージェンティックに実装する

llm-wiki は概念・パターンであり、特定のプロダクトではない。SharePoint vs llm-wiki の二択は誤り。

## 2. コンポーネント

### 2.1 Wiki.js（表示 + ACL 層）

**選定理由**: Git 双方向同期、パスベース ACL、GraphQL API、OIDC/SAML 認証。

| 要素 | 評価 |
|------|------|
| Markdown | ★★★★ ネイティブ |
| ACL（ページ単位） | ★★★★ Page Rules（パスベース） |
| Git バックエンド | ★★★★ 双方向同期 |
| API | ★★★★ GraphQL + REST |
| EntraID 連携 | ★★★★ OIDC/SAML |
| 全文検索 | ★★★★ PostgreSQL / Elasticsearch |
| 構造化 | ★★★★ 名前空間 + タグ |
| 運用負荷 | 中（Node.js + PostgreSQL） |
| 成熟度 | 活発（v2→v3 移行中） |

**カスタマイズ予定**:
- [ ] 日本語 UI 改善
- [ ] llm-wiki schema（entities/concepts/raw）向けナビゲーション
- [ ] エージェント編集の可視化（diff ビュー、変更通知）
- [ ] CI lint 結果のダッシュボード表示

### 2.2 Git リポジトリ（ソース・オブ・トゥルース）

```
wiki-content/
├── entities/          # 人物・組織・プロジェクト・技術 etc
│   ├── teams/
│   ├── projects/
│   └── technologies/
├── concepts/          # 概念・ベストプラクティス・ガイド
│   ├── architecture/
│   ├── security/
│   └── processes/
├── comparisons/       # 比較表・選定資料
└── meta/
    └── schema.yaml    # llm-wiki schema 定義
```

raw ディレクトリは存在しない。`status: raw` は frontmatter の一時的な状態。
connector が初回 commit で raw 状態のファイルを作成し、curator が同一ファイルを curated に変換する。

### 2.3 llm-wiki エージェント（編纂層）

Git リポジトリの CI パイプラインとして実行されるエージェント群。外部スケジューラではなく Git イベント（push, schedule）で駆動。

| エージェント | 役割 | トリガー |
|------------|------|----------|
| **connector-confluence** | Confluence XML → Markdown、適切なパスに `status: raw` で commit | 手動（初回インポート） |
| **connector-sharepoint** | SharePoint の新規/更新ドキュメントを取得し branch 作成 | 定期スケジュール |
| **curator** | 同一ファイルの `status: raw` → `status: curated` に変換。構造化・wikilink 付与 | connector の push |
| **lint-checker** | schema 違反・重複・wikilink 切れをチェック | curator の push |
| **freshness-checker** | `status: curated` のファイルの鮮度を評価、更新 branch 作成 | 定期（日次） |

各エージェントは個別の Git ユーザーとしてコミット。
**raw はディレクトリではなく frontmatter の状態。** 同一ファイル・同一パスで状態が遷移する。
Git の初期コミットが生データの履歴として残る。

## 3. 権限モデル

### 3.1 Wiki.js Page Rules

```
デフォルト: 全 deny（何も許可されていない）

ルール例:
  Path Starts With /entities/public    → 全社 read
  Path Starts With /entities/internal  → 社員 read
  Path Starts With /concepts           → 全社 read
  Path Is Exactly /home                → 全社 read（ランディングページ）
```

### 3.2 権限モデルの単純化

raw ディレクトリが存在しないことで、権限制御は大幅に単純化される：

- **ファイルは最初から最終パスに配置される**: connector が `entities/projects/foo.md` に直接 commit するため、Wiki.js の Page Rules が最初から適用される
- **中間ステージング領域がない**: 権限が剥がれる raw/ を経由しない
- **status: raw のページの可視性**: 必要なら `status: raw` のファイルは特定グループのみ read とする Page Rule を設定可能。または curator が処理するまでの短時間だけ非公開にする運用も選択可

### 3.3 Git アクセス制御

| ロール | 権限 |
|--------|------|
| Wiki.js Deploy Key | read/write 全ファイル |
| llm-wiki エージェント（Bot） | read/write 全ファイル（信頼されたボット） |
| 人間（管理者） | read/write + PR マージ |
| 人間（一般） | read のみ。書き込みは fork → PR |

### 3.4 権限フロー

```
外部ソース（Confluence / SharePoint）
  → connector が branch 作成、適切なパスに status: raw で commit
  → Wiki.js Page Rules が即時適用（path は最初から最終形）
  → curator が同一ファイルを status: curated に変換
  → パスは変わらない。権限も変わらない
```

## 4. 開発ロードマップ

### Phase 0: 検証
- [ ] Wiki.js をローカルにデプロイし Git 連携を動作確認
- [ ] OIDC で EntraID 連携の PoC
- [ ] Page Rules の挙動確認（パスベース ACL の実際の動作）
- [ ] raw/ への Markdown 手動 push → Wiki.js 反映の確認

### Phase 1: 基盤構築
- [ ] Wiki.js フォーク作成、カスタマイズ開始
- [ ] Git リポジトリ構造の確定
- [ ] Page Rules テンプレート作成
- [ ] CI/CD パイプライン設計

### Phase 2: エージェント実装
- [ ] connector-confluence の実装
- [ ] curator の PoC（1 スペースを AI 再編成）
- [ ] lint-checker の実装

### Phase 3: 運用
- [ ] コネクタの定期実行
- [ ] 人間レビューフローの確立
- [ ] ダッシュボード・通知の整備
