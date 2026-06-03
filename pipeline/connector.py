#!/usr/bin/env python3
"""connector: 新規コンテンツを branch に status: raw で commit する。

実際の運用では SharePoint/Confluence 等から取得するが、
このプロトタイプではサンプルコンテンツを生成する。

Usage:
    python3 connector.py --type entity --entity-type team --title "Platform Team" --author "bob@company.com"
    python3 connector.py --type concept --title "Git Sync Overview" --author "alice@company.com"
"""

import argparse, subprocess, sys, os, datetime, uuid, yaml
from pathlib import Path

REPO_URL = os.path.expanduser("~/projects/llm-wiki-platform/test/wiki-remote.git")
SCHEMA_PATH = os.path.expanduser("~/projects/llm-wiki-platform/test/wiki-content/meta/schema.yaml")
WORK_DIR = "/tmp/llm-wiki-connector"

# --- Content template per entity_type ---

CONTENT_TEMPLATES = {
    ("entity", "team"): """# {title}

{team_name}のチームページです。

## メンバー

-

## 担当領域

-

## 連絡先

-
""",
    ("entity", "project"): """# {title}

{project_name}のプロジェクト概要です。

## 目的

-

## マイルストーン

-

## 参加チーム

-
""",
    ("entity", "person"): """# {title}

## 役割

-

## 所属

-

## スキル

-
""",
    ("entity", "technology"): """# {title}

## 概要

-

## 用途

-

## 関連プロジェクト

-
""",
    ("concept",): """# {title}

## 概要

-

## なぜ重要か

-

## 関連

-
""",
}

def load_schema():
    with open(SCHEMA_PATH) as f:
        return yaml.safe_load(f)

def get_template(content_type, entity_type=None):
    if content_type == "entity" and entity_type:
        key = ("entity", entity_type)
    else:
        key = (content_type,)
    return CONTENT_TEMPLATES.get(key, CONTENT_TEMPLATES.get((content_type,), "# {title}\n\n"))

def run(cmd, cwd=None):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"[ERROR] {cmd}\n{result.stderr}")
        sys.exit(1)
    return result.stdout.strip()

def main():
    parser = argparse.ArgumentParser(description="llm-wiki connector")
    parser.add_argument("--type", required=True, choices=["entity", "concept", "comparison"])
    parser.add_argument("--entity-type", choices=["person", "team", "project", "technology", "process"])
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="unknown@llm-wiki.internal")
    parser.add_argument("--source-url", default="")
    args = parser.parse_args()

    schema = load_schema()
    # Map singular type names to schema keys (which use plural)
    type_to_schema_key = {
        "entity": "entities",
        "concept": "concepts",
        "comparison": "comparisons",
    }
    schema_key = type_to_schema_key.get(args.type)
    if not schema_key or schema_key not in schema:
        print(f"[ERROR] Unknown content type: {args.type}")
        sys.exit(1)
    content_type = schema_key
    entity_type = args.entity_type
    type_schema = schema[content_type]
    if args.type == "entity":
        if not entity_type:
            print("[ERROR] --entity-type is required for type=entity")
            sys.exit(1)
        if entity_type not in type_schema.get("entity_types", []):
            print(f"[ERROR] Unknown entity_type: {entity_type}. Valid: {type_schema['entity_types']}")
            sys.exit(1)

    # Determine path
    slug = args.title.lower().replace(" ", "-")
    if args.type == "entity":
        file_path = f"entities/{entity_type}s/{slug}.md"
    else:
        file_path = f"{content_type}/{slug}.md"

    # Branch name
    branch = f"connector/{args.type}/{slug}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Clone bare repo
    if os.path.exists(WORK_DIR):
        run(f"rm -rf {WORK_DIR}")
    run(f"git clone {REPO_URL} {WORK_DIR}")
    run(f"git checkout -b {branch}", cwd=WORK_DIR)

    # Generate content
    title = args.title
    template = get_template(args.type, entity_type)
    body = template.format(title=title, team_name=title, project_name=title)

    # Build frontmatter
    now = datetime.datetime.now(datetime.UTC).isoformat()
    frontmatter = {
        "title": title,
        "type": args.type,  # singular form (entity/concept/comparison)
        "status": "raw",
        "source_author": args.author,
    }
    if entity_type:
        frontmatter["entity_type"] = entity_type
    if args.source_url:
        frontmatter["source_url"] = args.source_url

    yaml_fm = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    content = f"---\n{yaml_fm}\n---\n\n{body}"

    # Write file
    full_path = os.path.join(WORK_DIR, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)

    # Commit and push
    author_name = args.author.split("@")[0].replace(".", " ").title()
    author_email = args.author
    run(f"git add {file_path}", cwd=WORK_DIR)
    run(f"git commit -m '[connector] import {file_path} (status: raw)' --author=\"{author_name} <{author_email}>\"", cwd=WORK_DIR)
    run(f"git push origin {branch}", cwd=WORK_DIR)

    print(f"[OK] Branch: {branch}")
    print(f"[OK] File:   {file_path}")
    print(f"[OK] Status: raw → awaiting curator")
    print(f"\nbranch={branch}")

    # Cleanup
    run(f"rm -rf {WORK_DIR}")

if __name__ == "__main__":
    main()
