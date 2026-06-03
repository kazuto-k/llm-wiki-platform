# Curator Quality Standards

curator が `status: raw` → `status: curated` 変換時に行うべき処理の具体例。

## 変換前後の比較（Payment Service 刷新プロジェクト）

### raw（Confluence からエクスポートされた状態）

```markdown
# 概要
決済サービスのリプレース案件です。
現在のシステムが老朽化してるので新しいのに変えます。

## メンバー
なんか色々いる
田中（PM）
佐藤（リード）

## スケジュール
なんか来年の3月くらいまでには終わる予定らしい。

## メモ
なんかSlackで「もう無理」って誰かが言ってたらしい（伝聞）
```

問題点:
- 口語・崩れた表現（「今のやつ」「なんか」「らしい」）
- 事実と推測の混在
- 構造化されていない情報（メンバーが箇条書きのみ）
- 不適切な伝聞の記載

### curated（curator による編纂後）

```markdown
---
title: Payment Service 刷新プロジェクト
description: 決済サービスのリプレース案件。既存システムの老朽化対応と PCI DSS 準拠を目的とする。
type: entity
entity_type: project
status: curated
curator: curator-bot
curated_at: 2026-06-03T09:47:00Z
confidence: 0.7
tags: payment, pci-dss, api, refactoring, migration
---

## 背景
- 現行システムは 2019 年構築、保守負荷が限界に達している
- PCI DSS 準拠対応が必須

## メンバー
| 氏名 | 役割 |
|------|------|
| 田中 | プロジェクトマネージャー |
| 佐藤 | テックリード |

## スケジュール
| マイルストーン | 予定 |
|---------------|------|
| 完了目標 | 2027 年 3 月 |

> **注意**: 日付は伝聞ベース。正式なスケジュールの確認が必要。

## 編纂ノート
- 原文にあった「メモ: Slack で『もう無理』と言われている」は伝聞かつ不適切な表現のため削除
```

## curator が行うべき処理チェックリスト

1. [ ] **文体整形**: 口語→技術文書（「今のやつ」→「現行システム」）
2. [ ] **構造化**: 箇条書き→表、階層整理
3. [ ] **不足情報の注記**: 伝聞・未確認事項を明示（「要確認」「伝聞ベース」）
4. [ ] **既存ページへの wikilink 付与**: 存在確認付きで関連ページをリンク
5. [ ] **未作成参照先の警告**: `⚠ ページ未作成 — <説明>` として明示
6. [ ] **不適切内容のフィルタリング**: 削除理由を「編纂ノート」に注記
7. [ ] **メタデータ補完**: `description`, `tags`, `confidence` を設定
8. [ ] **トレーサビリティ**: `curator`, `curated_at` を必ず記録
9. [ ] **wikilink → markdown link 変換**: Wiki.js 表示用に `[[path]]` を `[title](rel-path)` に変換

## confidence 設定基準

| 値 | 条件 |
|----|------|
| 0.9-1.0 | 全情報が明確、正式ソースから確認済み |
| 0.7-0.8 | 情報はあるが伝聞や未確認事項を含む |
| 0.4-0.6 | 情報が断片的、大きな欠落がある |
| 0.1-0.3 | ほとんど情報がない、大幅な補完が必要 |

## wikilink 変換ルール

Wiki.js は `[[wikilink]]` をリンクとして解釈しないため、curator は表示用に変換する:

```markdown
# 内部表現（Git 上のファイル）
[[entities/projects/api-migration]]

# Wiki.js 表示用に変換
[API Migration](../api-migration)
```

変換は curator の最終ステップとして実行する。内部表現（`[[path]]`）は lint-checker や freshness-checker が依存しているため、Git 上のファイルでは wikilink 形式を維持する。
