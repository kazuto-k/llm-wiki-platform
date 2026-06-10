#!/usr/bin/env python3
"""Wiki.js の Git 同期を手動トリガーする。

Usage:
    python3 trigger-sync.py
    python3 trigger-sync.py --url http://localhost:3000 --email admin@llm-wiki.internal --password admin123
"""

import urllib.request, json, argparse, sys, os

def gql(url, query, jwt=None):
    data = json.dumps({"query": query}).encode()
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = "Bearer " + jwt
    req = urllib.request.Request(url + "/graphql", data=data, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Trigger Wiki.js Git sync")
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--email", default=os.environ.get("WIKIJS_EMAIL", "admin@llm-wiki.internal"))
    parser.add_argument("--password", default=os.environ.get("WIKIJS_PASSWORD", "admin123"))
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    # Login
    result = gql(base_url, f'''
        mutation {{
            authentication {{
                login(username: "{args.email}", password: "{args.password}", strategy: "local") {{
                    jwt
                }}
            }}
        }}
    ''')
    jwt = result["data"]["authentication"]["login"]["jwt"]

    # Trigger sync
    result = gql(base_url, '''
        mutation {
            storage {
                executeAction(targetKey: "git", handler: "sync") {
                    responseResult { succeeded message }
                }
            }
        }
    ''', jwt)

    status = result["data"]["storage"]["executeAction"]["responseResult"]
    if status["succeeded"]:
        print("Sync triggered successfully.")
    else:
        print(f"Sync failed: {status['message']}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
