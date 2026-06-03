# llm-wiki Pipeline

CI パイプラインのプロトタイプ。各スクリプトは独立して動作し、シェルスクリプトで連結する。

## アーキテクチャ

```
connector.py  ──→  curator.py  ──→  lint-checker.py  ──→  merge.py
 (branch作成)      (raw→curated)     (schema検証)         (masterにmerge)
```

## スクリプト一覧

| スクリプト | 役割 | LLM要否 |
|-----------|------|---------|
| `connector.py` | 新規コンテンツを branch に `status: raw` で commit | 不要（ルールベース） |
| `curator.py` | `status: raw` → `curated` 変換、frontmatter 補完、タグ付与 | 要（本番では Hermes スキル） |
| `lint-checker.py` | schema.yaml 検証、必須フィールド、entity_type 有効値、wikilink 整合性 | 不要 |
| `merge.py` | lint 通過 branch を master にマージ | 不要 |
| `run-pipeline.sh` | 上記を順次実行するオーケストレーター | — |

## 使用方法

```bash
# 単一ページのパイプライン実行
./run-pipeline.sh --type entity --entity-type team --title "Platform Team" --author "bob@company.com"

# 各ステップを個別に
python3 connector.py --type entity --entity-type project --title "New Project" --author "eve@company.com"
python3 curator.py /tmp/llm-wiki-connector --branch connector/entity/new-project-20260603
python3 lint-checker.py /tmp/llm-wiki-connector
python3 merge.py /tmp/llm-wiki-connector --branch connector/entity/new-project-20260603
```

## lint-checker 検証項目

1. **必須フィールド**: schema.yaml の `required` に指定されたキーが存在するか
2. **entity_type 有効値**: `entities.entity_types` に含まれるか
3. **status 有効値**: `raw`, `draft`, `curated`, `stale`, `verified` のいずれか
4. **wikilink 整合性**: 絶対パス・相対パス両方でリンク先ファイルの存在確認

## パイプライン結果（2026-06-03）

```
connector → curator → lint-checker (6 files, 0 errors) → merge SUCCESS
```

### Wiki.js 反映後のページ一覧

| path | title |
|------|-------|
| home | Home |
| entities/projects/test-project | テストプロジェクト概要 |
| entities/projects/api-migration | API Migration |
| entities/people/alice | Alice |
| entities/people/bob | Bob |
| concepts/git-sync | Git Sync |

## CI 環境への展開

現在のスクリプトはローカル実行だが、以下の CI で同等に動作する：

- **GitHub Actions**: 各ステップを job に分割、`connector → push → curator (on: push) → lint → merge`
- **GitLab CI**: stages で順序制御、`GIT_STRATEGY: clone` で branch 間の共有
- **ローカル cron/手動**: `run-pipeline.sh` を直接実行

## Gitea Actions 検討

軽量・オンプレ CI として Gitea Actions が最も llm-wiki に適合する可能性が高い：

- Docker 不要（Git 操作のみ）
- LLM API アクセスが可能（オンプレネットワーク内）
- GitHub Actions 互換構文
- Git リポジトリと一体化（Wiki.js の Git ストレージと相性が良い）
