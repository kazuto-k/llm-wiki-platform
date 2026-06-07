# ローカルLLM curator 品質評価

> **評価日**: 2026-06-06 | **評価者**: 牧瀬紅莉栖（Hermes Agent, deepseek-v4-pro） | **ステータス**: Phase 0.7 事前評価

## 目的

Mnemosyne の curator エージェントをローカルLLMで運用する場合の品質・コスト・実用性を評価する。

社内ドキュメントを外部APIに投げるセキュリティリスクを回避するため、ローカルLLMの curator 適性を検証する。

## テスト環境

- **サーバー**: macbook-pro-16 (macOS, Tailscale `100.75.63.85`)
- **ollama**: port 11434
- **LM Studio**: port 1234

## 評価モデル

| モデル | パラメータ | 量子化 | サイズ | コンテキスト | 実行環境 |
|--------|-----------|--------|--------|-------------|---------|
| gemma4:12b | 11.9B | Q4_K_M | 7.6 GB | 262K | ollama |
| gpt-oss:20b | 20.9B | MXFP4 | 13.8 GB | 131K | ollama |
| qwen3:14b | 14.8B | Q4_K_M | 9.3 GB | 41K | ollama |
| qwen3.6-35b-a3b-uncensored | 35B (MoE, 3B active) | MLX | — | — | LM Studio |

## 評価項目

1. **要約力**: raw ドキュメントから適切な日本語要約を生成できるか
2. **enum制約遵守**: entity_type を指定された選択肢（technology/concept/person/team/project）から選べるか
3. **タグ付け**: 適切なタグを3〜5個生成できるか
4. **wikilinks/related**: 関連ドキュメントを適切に提案できるか
5. **本文構造化**: raw テキストを箇条書きで整形できるか
6. **応答速度・効率**: 実用的なレイテンシとトークン効率か

## テスト結果

### Test Case 1: 要約 + タグ + wikilinks（マイクロサービス移行プロジェクト）

| 項目 | gemma4:12b | gpt-oss:20b | qwen3.6-35b |
|------|-----------|-------------|-------------|
| 要約 | ✅ 自然な100字要約 | — | — |
| タグ | ✅ `マイクロサービス, システム移行, Go, Kubernetes, CI/CD` | — | — |
| wikilinks | ✅ 4件提案 | — | — |
| entity_type | ✅ `project` | — | — |

### Test Case 2: Frontmatter 補完 + 構造化（GraphQL API設計ガイド）

| 項目 | gemma4:12b | gpt-oss:20b | qwen3.6-35b-unc |
|------|-----------|-------------|-------------------|
| title | ✅ `GraphQL API設計ガイド` | ✅ | ✅ |
| entity_type | ❌ `"技術仕様書"` (schema外) | ✅ `"technology"` | ✅ `"technology"` |
| tags | ✅ `GraphQL, API, Architecture, Backend` | ✅ `GraphQL, API Design, JWT, ...` | ✅ `GraphQL, API設計, JWT認証, ...` |
| related | ✅ `REST, Apollo Federation, DataLoader` | ⚠️ 空 | ⚠️ 1件（`認証ガイド`） |
| 本文構造化 | ✅ 4項目 | ✅ 5項目（詳細） | ✅ 簡潔5項目 |

### qwen3:14b / qwen3.6-27b-mlx

いずれも **thinking/reasoning モデル** であり、思考トークンが出力トークンを消費し curator として実用的でない。非 thinking モードが必要。

## 総合評価

```
curator 適性: gemma4:12b > gpt-oss:20b > qwen3.6-35b-a3b-unc
コスパ:      gemma4:12b >>> 他
```

### gemma4:12b — 推奨

- **長所**: 12Bで7.6GB、応答速い、日本語自然、要約・タグ・wikilinksすべて高品質
- **短所**: enum制約の遵守が甘い（`"技術仕様書"` などschema外の値を返すことがある）
- **対策**: プロンプトで `entity_type は technology|concept|person|team|project のいずれかから必ず選べ。他の値は許容されない。` と厳密に指示
- **コスト**: 初期投資（GPUサーバー）+ 電気代のみ。API従量課金なし

### gpt-oss:20b — 次点

- enum制約遵守は優秀だが、related/wikilinksが弱い
- 13.8GBとサイズが大きく、応答も遅い

### qwen3.6-35b-a3b — 条件付き

- MoEでアクティブ3Bと軽量だが、thinkingモデルのため無駄な推論トークンが多い
- 非thinkingモードが利用可能になれば再評価の価値あり

## 推奨アクション

1. **curator のデフォルトモデルを gemma4:12b に設定**
2. **プロンプトに enum 制約の厳密な指示を追加**（lint-checker のエラー率低減）
3. **gpt-oss:20b を代替/fallback として保持**
4. **qwen3.6 は非thinkingモードの利用可否を調査**

## 関連

- `docs/design-deep-dive.md` — エージェント設計詳細
- `skills/curator-quality-standards.md` — curator 品質基準
- Phase 0.7: 実データ（Confluence）での curator 品質検証（未着手）
