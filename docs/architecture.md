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
├── raw/               # コネクタの作業ディレクトリ
│   ├── confluence/    # Confluence エクスポート
│   ├── sharepoint/    # SharePoint pull
│   ├── teams/         # Teams 会話ログ
│   └── external/      # Webclip / RSS / Bluesky
└── meta/
    └── schema.yaml    # llm-wiki schema 定義
```

### 2.3 llm-wiki エージェント（編纂層）

Git リポジトリに対して直接操作するエージェント群。CI/CD パイプラインとして実行。

| エージェント | 役割 | トリガー |
|------------|------|----------|
| **connector-confluence** | Confluence XML → Markdown 変換し raw/ に投入 | 初回のみ（インポート） |
| **connector-sharepoint** | SharePoint の新規/更新ページを raw/ に pull | 定期（15分〜1時間） |
| **connector-teams** | Teams 会話ログを raw/ に投入 | 定期 |
| **curator** | raw/ の内容を分析し entities/concepts に再編成 | raw/ 更新時 |
| **lint-checker** | 重複・矛盾・孤立・陳腐化を検出 | 定期 + PR 時 |
| **freshness-checker** | 最終更新日から鮮度を評価、更新提案 | 定期（日次） |

各エージェントは個別の Git ユーザーとしてコミット。権限は「どのパスに書くか」で表現される。

## 3. 権限モデル

### 3.1 Wiki.js Page Rules

```
デフォルト: 全 deny（何も許可されていない）

ルール例:
  Path Starts With /entities/public    → 全社 read
  Path Starts With /entities/internal  → 社員 read
  Path Starts With /concepts           → 全社 read
  Path Starts With /raw                → admin only（管理グループのみ）
  Path Is Exactly /home                → 全社 read（ランディングページ）
```

### 3.2 Git アクセス制御

| ロール | 権限 |
|--------|------|
| Wiki.js Deploy Key | read/write 全ファイル |
| llm-wiki エージェント（Bot） | read/write 全ファイル（信頼されたボット） |
| 人間（管理者） | read/write + PR マージ |
| 人間（一般） | read のみ。書き込みは fork → PR |

### 3.3 権限継承フロー

```
外部ソース（Confluence / SharePoint）
  → コネクタが raw/ に pull（元の ACL はメタデータとして保持）
  → curator が entities/concepts に再編成
  → 編成先のパスによって Wiki.js ACL が自動適用
  → 元の機密情報はパス設計でフィルタリング
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
