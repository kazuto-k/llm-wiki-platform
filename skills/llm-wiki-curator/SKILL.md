---
name: llm-wiki-curator
description: "llm-wiki curator: status:raw のMarkdownファイルをstatus:curatedに変換する。frontmatter補完、構造化、wikilink付与を行う。"
---

# llm-wiki-curator

`status: raw` のMarkdownファイルを `status: curated` に変換するcuratorエージェント。

## このスキルが呼ばれるとき

`pipeline/curator.py` から以下の形式で呼ばれる：

```bash
hermes --profile llm-wiki-curator chat --skill llm-wiki-curator -q "<JSON形式のファイル情報>"
```

入力JSONの形式：
```json
{
  "path": "entities/projects/hoge.md",
  "frontmatter": {"title": "...", "type": "entity", "entity_type": "project", "status": "raw"},
  "body": "# タイトル\n\n内容..."
}
```

## タスク

以下の処理を行い、**変換後のMarkdown全文**のみを出力せよ。説明文や前置きは不要。

### 1. frontmatterの更新
- `status`: `raw` → `curated`
- `description`: 本文から100字以内で要約して設定
- `tags`: タイトル・本文のキーワードからカンマ区切りで設定（3〜7個）
- `curator`: `curator-bot`
- `curated_at`: 現在日時（ISO8601）
- `confidence`: 変換品質の自己評価（0.0〜1.0）

### 2. 本文の整形
- 口語・箇条書きの羅列を技術文書らしく整形
- 不足している情報は「※未確認」「※要確認」と注記
- 内容の削除は行わない（削除理由を注記する）

### 3. wikilinkの付与
- 既存ページ（`existing_pages`として渡される）への参照は `[[ページパス|表示名]]` 形式でリンク
- 未作成ページへの参照は `⚠ [[ページ名]]（ページ未作成）` と注記

## 出力形式

必ず以下の形式で出力すること：

```
---
title: ...
type: ...
status: curated
description: ...
tags: ...
curator: curator-bot
curated_at: ...
confidence: ...
---

# タイトル

本文...
```

**frontmatterと本文のみ。説明・前置き・後書き一切不要。**
