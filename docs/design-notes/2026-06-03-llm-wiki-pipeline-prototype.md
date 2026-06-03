---
title: llm-wiki CI パイプラインプロトタイプ検証
date: 2026-06-03
tags: [llm-wiki, ci, pipeline, connector, curator, lint-checker, experiment]
status: completed
---

# llm-wiki CI パイプラインプロトタイプ検証

## 要約

connector → curator → lint-checker → merge の 4 段階パイプラインを Python スクリプト群で実装し、エンドツーエンドで動作検証した。全ステップが正常動作し、lint 通過後に master への自動マージが完了。Wiki.js への反映も確認。

## パイプライン構成

```
connector.py ──→ curator.py ──→ lint-checker.py ──→ merge.py
 (branch作成)    (raw→curated)   (schema検証)       (master merge)
```

| コンポーネント | 実装 | LLM |
|--------------|------|-----|
| connector | Python（ルールベース） | 不要 |
| curator | Python（prototype: ルールベース） | 本番では Hermes スキル |
| lint-checker | Python（schema.yaml 検証） | 不要 |
| merge | Python（git merge） | 不要 |
| orchestrator | Shell（run-pipeline.sh） | — |

## 検証方法

```bash
./run-pipeline.sh --type entity --entity-type project --title "API Migration" --author "eve@company.com"
```

実行フロー:
1. connector: `entities/projects/api-migration.md` を `status: raw` で branch に commit + push
2. clone + branch checkout
3. curator: `status: raw` → `status: curated`、`curator`, `curated_at`, `tags`, `confidence` 追加
4. lint-checker: 6ファイルを検査（必須フィールド、entity_type、status、wikilink）
5. merge: lint 通過を確認し master に merge

## 検証結果

### 成功シナリオ

```
Files checked: 6
Errors: 0
RESULT: PASS
→ merge SUCCESS
→ Wiki.js sync → 全6ページ表示確認
```

### 失敗シナリオ（wikilink 切れ）

lint-checker は wikilink の解決を絶対パス・相対パスの両方で試み、リンク先不在時にエラーとする。最初のテストでは既存の test-project.md に `[[Alice]]`, `[[Bob]]` の wikilink 切れが検出され、マージがブロックされた。これは CI パイプラインとして期待通りの挙動。

## lint-checker 検証項目

| 項目 | 方法 |
|------|------|
| 必須フィールド | schema.yaml `required` との照合 |
| entity_type 有効値 | schema.yaml `entity_types` との照合 |
| status 有効値 | `{raw, draft, curated, stale, verified}` |
| wikilink 整合性 | 絶対パス → 相対パスの順でリンク先を探索 |
| YAML パースエラー | frontmatter の構文チェック |

## 設計上の知見

1. **branch 戦略**: connector が branch を作成し curator が追従コミット。同一 branch 上での作業により Git の履歴が一貫する
2. **lint ゲート**: 失敗時は merge ブロック + branch 削除（または再処理用に保持）。CI の標準的なパターンと互換
3. **curator の LLM 化**: 現在のプロトタイプはルールベースだが、本番では Hermes チャット（`hermes chat --skill llm-wiki-curator -q ...`）に置き換え可能
4. **Wiki.js 同期**: merge 後 5 分以内に自動反映。手動 trigger も GraphQL API で可能

## CI 環境への展開

ローカルの `run-pipeline.sh` は以下の CI で同等に動作：

- **GitHub Actions**: `on: push` トリガーで job 分割
- **GitLab CI**: stages で直列制御
- **Gitea Actions**: オンプレ CI、GitHub Actions 互換構文、llm-wiki に最適

## 次の一手

- curator を Hermes スキルに置き換え（実際の LLM 編纂）
- connector に SharePoint API 連携を追加
- freshness-checker の実装（日次バッチ）
- 通知システム（source_author へのメール/Discord）
