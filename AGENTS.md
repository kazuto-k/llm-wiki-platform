# llm-wiki-platform — Agent Instructions

## プロジェクト概要

Wiki.js を基盤に llm-wiki パターン（connector → curator → lint → merge）を実装するナレッジ基盤。

## 主要ドキュメント

- `docs/design-deep-dive.md` — 設計詳細（最初に読む）
- `docs/design-notes/` — Phase 0 の全検証レポート
- `pipeline/README.md` — パイプライン各スクリプトの説明
- `test/README.md` — テスト環境の詳細

## エージェント向けルール

### Wiki.js 操作

- コンテナは `wikijs-test`（Docker, host ネットワーク, port 3000）
- 管理者: `admin@llm-wiki.internal` / `admin123`
- Git 同期は双方向 5 分間隔。手動トリガー: `python3 pipeline/trigger-sync.py`
- **SSH モード必須**（ローカル bare repo では basic 認証不可）
- **初回 init 後は既存ファイルが自動インポートされない**。ダミー commit で回避

### コンテンツ規則

- frontmatter に `type`, `entity_type`, `status` 必須（schema.yaml 参照）
- `[[wikilink]]` は内部表現。Wiki.js 表示用には `[text](path)` に変換
- status の遷移: `raw` → `curated` → `stale`/`verified`
- カスタム frontmatter は Wiki.js ラウンドトリップで保持される

### パイプライン

```bash
./run-pipeline.sh --type entity --entity-type team --title "Team Name" --author "user@company.com"
```

- connector: branch 作成 + `status: raw` commit
- curator: raw → curated 変換（LLM 必須）
- lint-checker: schema 検証（errors=block, warnings=allow）
- merge: master にマージ

### lint-checker の警告/エラー

- **ERROR**（ブロッキング）: 必須フィールド欠落、entity_type 不正、status 不正
- **WARNING**（非ブロッキング）: wikilink 切れ

## スキル

このプロジェクト用の Hermes スキルは `skills/llm-wiki-pipeline.md` に置かれている。
会社ホストにセットアップする場合、このファイルを `~/.hermes/skills/devops/llm-wiki-pipeline/SKILL.md` にコピーする。

## Git 運用

- bare repo: `test/wiki-remote.git/`
- Wiki.js 作業ディレクトリ: `test/wikijs-data/repo/`
- 手動コンテンツ投入時は bare repo に clone → commit → push
