#!/usr/bin/env python3
"""lint-checker: schema.yaml に基づいて frontmatter を検証する。

チェック項目:
1. 必須フィールドの存在
2. entity_type の有効値
3. wikilink の有効性（リンク先ファイルの存在確認）
4. status 値の整合性

Usage:
    python3 lint-checker.py /path/to/repo
    python3 lint-checker.py /tmp/llm-wiki-connector --schema meta/schema.yaml

Exit code: 0 = pass, 1 = errors found
"""

import argparse, sys, os, yaml, re, json
from pathlib import Path

WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

def load_schema(repo_path):
    schema_path = os.path.join(repo_path, "meta", "schema.yaml")
    if not os.path.exists(schema_path):
        print(f"[ERROR] Schema not found: {schema_path}")
        sys.exit(1)
    with open(schema_path) as f:
        return yaml.safe_load(f)

def parse_frontmatter(content):
    """Extract YAML frontmatter and body from markdown content."""
    if not content.startswith("---"):
        return None, None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, None
    try:
        fm = yaml.safe_load(parts[1])
        body = parts[2]
        return fm, body
    except yaml.YAMLError as e:
        return {"_parse_error": str(e)}, None

def find_markdown_files(repo_path):
    """Find all .md files, excluding meta/ and .git/"""
    md_files = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in (".git", "meta")]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))
    return md_files

def check_required_fields(fm, required, file_path):
    errors = []
    for field in required:
        if field not in fm:
            errors.append(f"[{file_path}] Missing required field: '{field}'")
    return errors

def check_entity_type(fm, valid_types, file_path):
    errors = []
    if "entity_type" in fm:
        if fm["entity_type"] not in valid_types:
            errors.append(f"[{file_path}] Invalid entity_type: '{fm['entity_type']}'. Valid: {valid_types}")
    return errors

def check_wikilinks(body, repo_path, file_path, all_files):
    """Check that wikilinks reference existing files.
    Resolves both absolute (from repo root) and relative paths.
    """
    errors = []
    if not body:
        return errors
    links = WIKILINK_RE.findall(body)
    current_dir = os.path.dirname(file_path)
    for link in links:
        found = False
        # Try absolute path from repo root
        for candidate_suffix in [link + ".md", link + "/index.md"]:
            candidate = os.path.join(repo_path, candidate_suffix)
            if os.path.exists(candidate):
                found = True
                break
        # Try relative path from current file
        if not found:
            for candidate_suffix in [link + ".md", link + "/index.md"]:
                candidate = os.path.join(repo_path, current_dir, candidate_suffix)
                if os.path.exists(candidate):
                    found = True
                    break
        if not found:
            errors.append(f"[{file_path}] Broken wikilink: [[{link}]] → file not found")
    return errors

def check_status(fm, file_path):
    errors = []
    valid_statuses = {"raw", "draft", "curated", "stale", "verified"}
    if "status" in fm and fm["status"] not in valid_statuses:
        errors.append(f"[{file_path}] Invalid status: '{fm['status']}'. Valid: {valid_statuses}")
    return errors

def main():
    parser = argparse.ArgumentParser(description="llm-wiki lint-checker")
    parser.add_argument("repo", help="Path to the repository root")
    parser.add_argument("--schema", default="meta/schema.yaml", help="Path to schema.yaml relative to repo")
    parser.add_argument("--json", action="store_true", help="Output errors as JSON")
    args = parser.parse_args()

    repo_path = args.repo
    schema = load_schema(repo_path)
    all_files = [os.path.relpath(f, repo_path) for f in find_markdown_files(repo_path)]

    all_errors = []
    all_warnings = []

    for fpath in find_markdown_files(repo_path):
        with open(fpath) as f:
            content = f.read()
        fm, body = parse_frontmatter(content)

        rel_path = os.path.relpath(fpath, repo_path)

        if fm is None:
            all_errors.append(f"[{rel_path}] No valid frontmatter found")
            continue

        if "_parse_error" in fm:
            all_errors.append(f"[{rel_path}] YAML parse error: {fm['_parse_error']}")
            continue

        # Determine content type from path or frontmatter
        content_type = fm.get("type", "")
        if not content_type:
            path_parts = rel_path.split("/")
            if len(path_parts) > 0:
                content_type = path_parts[0].rstrip("s") if path_parts[0].endswith("s") else path_parts[0]

        # Schema validation (ERRORS)
        if content_type in schema:
            type_schema = schema[content_type]
            required = type_schema.get("required", [])
            all_errors += check_required_fields(fm, required, rel_path)

            if content_type == "entity":  # content_type is "entities" (schema key)
                valid_types = type_schema.get("entity_types", [])
                all_errors += check_entity_type(fm, valid_types, rel_path)

        # Universal checks
        all_errors += check_status(fm, rel_path)
        all_warnings += check_wikilinks(body, repo_path, rel_path, all_files)

    if args.json:
        print(json.dumps({
            "errors": all_errors, "warnings": all_warnings,
            "error_count": len(all_errors), "warning_count": len(all_warnings),
            "files_checked": len(all_files)
        }))
    else:
        if all_errors:
            for err in all_errors:
                print(f"ERROR: {err}")
        if all_warnings:
            for w in all_warnings:
                print(f"WARN:  {w}")
        print(f"\nFiles checked: {len(all_files)}")
        print(f"Errors: {len(all_errors)}")
        print(f"Warnings: {len(all_warnings)}")
        if all_errors:
            print("RESULT: FAIL (errors found)")
        else:
            print("RESULT: PASS" + (" (with warnings)" if all_warnings else ""))

    sys.exit(1 if all_errors else 0)

if __name__ == "__main__":
    main()
