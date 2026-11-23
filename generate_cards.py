#!/usr/bin/env python3
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parent
API_URL = "https://api.github.com/graphql"

THEMES = {
    "dark": {
        "output": "dark_mode.svg",
        "background": "#0d1117",
        "panel": "#161b22",
        "border": "#30363d",
        "foreground": "#f0f6fc",
        "muted": "#8b949e",
        "accent": "#7ee787",
        "blue": "#58a6ff",
    },
    "light": {
        "output": "light_mode.svg",
        "background": "#ffffff",
        "panel": "#f6f8fa",
        "border": "#d0d7de",
        "foreground": "#1f2328",
        "muted": "#656d76",
        "accent": "#1a7f37",
        "blue": "#0969da",
    },
}

STATS_QUERY = """
query UserStats($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    followers {
      totalCount
    }
    repositories(
      first: 100
      after: $after
      privacy: PUBLIC
      ownerAffiliations: OWNER
      isFork: false
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      totalCount
      nodes {
        stargazerCount
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

COMMITS_QUERY = """
query UserCommits($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
    }
  }
}
"""


def graphql(token, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-card-generator",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed ({error.code}): {detail}") from error
    if payload.get("errors"):
        messages = "; ".join(item.get("message", "Unknown error") for item in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL API error: {messages}")
    return payload["data"]


def load_stats(token, username):
    after = None
    repositories = 0
    stars = 0
    followers = 0
    created_at = None
    while True:
        data = graphql(token, STATS_QUERY, {"login": username, "after": after})
        user = data.get("user")
        if user is None:
            raise RuntimeError(f"GitHub user '{username}' was not found")
        created_at = created_at or user["createdAt"]
        followers = user["followers"]["totalCount"]
        page = user["repositories"]
        repositories = page["totalCount"]
        stars += sum(repo["stargazerCount"] for repo in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    first_year = int(created_at[:4])
    current_year = dt.datetime.now(dt.timezone.utc).year
    commits = 0
    for year in range(first_year, current_year + 1):
        start = f"{year}-01-01T00:00:00Z"
        end = (
            dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            if year == current_year
            else f"{year}-12-31T23:59:59Z"
        )
        data = graphql(
            token,
            COMMITS_QUERY,
            {"login": username, "from": start, "to": end},
        )
        commits += data["user"]["contributionsCollection"]["totalCommitContributions"]

    return {
        "Repos": repositories,
        "Stars": stars,
        "Commits": commits,
        "Followers": followers,
    }


def dotted_line(label, value, width=48):
    available = max(3, width - len(label) - len(value))
    return f"{label} {'.' * available} {value}"


def text_element(x, y, text, css_class, size=18):
    return (
        f'<text x="{x}" y="{y}" class="{css_class}" font-size="{size}">'
        f"{escape(str(text))}</text>"
    )


def render_svg(config, stats, theme_name):
    theme = THEMES[theme_name]
    current_year = dt.datetime.now(dt.timezone.utc).year
    uptime = max(0, current_year - int(config["career_start_year"]))
    portrait_path = ROOT / config["portrait"][theme_name]
    portrait_lines = [
        line.rstrip() for line in portrait_path.read_text(encoding="utf-8").splitlines()
    ]
    if len(portrait_lines) > 28 or any(len(line) > 36 for line in portrait_lines):
        raise ValueError(f"{portrait_path.name} must fit within 36 x 28 characters")

    fields = [
        ("Role", config["role"]),
        ("Uptime", f"{uptime} years"),
        ("Host", config["host"]),
        ("Base", config["base"]),
        ("Focus", config["focus"]),
        ("Stack", config["stack"]),
        ("Languages", config["languages"]),
        ("Contact", config["contact"]),
    ]
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    display_name = escape(str(config["display_name"]))
    username = escape(str(config["username"]))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="600" '
        'viewBox="0 0 1120 600" role="img" '
        f'aria-labelledby="title desc" data-theme="{theme_name}">',
        f"<title id=\"title\">{display_name}'s GitHub profile terminal card</title>",
        '<desc id="desc">ASCII portrait, profile details, and live GitHub statistics.</desc>',
        "<style>",
        "text { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
        "'Liberation Mono', 'Courier New', monospace; white-space: pre; }",
        f".fg {{ fill: {theme['foreground']}; }}",
        f".muted {{ fill: {theme['muted']}; }}",
        f".accent {{ fill: {theme['accent']}; font-weight: 700; }}",
        f".blue {{ fill: {theme['blue']}; font-weight: 700; }}",
        "</style>",
        f'<rect width="1120" height="600" rx="22" fill="{theme["background"]}"/>',
        f'<rect x="16" y="16" width="1088" height="568" rx="16" '
        f'fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>',
        f'<circle cx="42" cy="44" r="6" fill="#ff5f56"/>',
        f'<circle cx="64" cy="44" r="6" fill="#ffbd2e"/>',
        f'<circle cx="86" cy="44" r="6" fill="#27c93f"/>',
        text_element(112, 51, f"{username}@github:~", "muted", 16),
        f'<line x1="310" y1="76" x2="310" y2="552" '
        f'stroke="{theme["border"]}" stroke-width="2"/>',
        text_element(34, 98, "$ whoami", "accent", 15),
    ]

    portrait_y = 125
    for index, line in enumerate(portrait_lines):
        parts.append(text_element(34, portrait_y + index * 15, line, "fg", 12))

    parts.append(text_element(346, 103, f"@{username}", "blue", 25))
    field_y = 145
    for index, (label, value) in enumerate(fields):
        parts.append(text_element(346, field_y + index * 36, dotted_line(label, value), "fg", 18))

    parts.append(
        f'<rect x="336" y="446" width="730" height="104" rx="10" '
        f'fill="{theme["background"]}" stroke="{theme["border"]}"/>'
    )
    parts.append(text_element(358, 474, "GitHub Stats", "accent", 17))
    stats_x = 358
    for index, (label, value) in enumerate(stats.items()):
        x = stats_x + index * 172
        parts.append(text_element(x, 511, label.upper(), "muted", 14))
        parts.append(text_element(x, 538, value, "blue", 23))

    parts.append(text_element(346, 571, f"Updated {generated}  ·  generated by GitHub Actions", "muted", 12))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("Set GITHUB_TOKEN or GH_TOKEN before running this script")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    stats = load_stats(token, config["username"])
    for theme_name in THEMES:
        output = ROOT / THEMES[theme_name]["output"]
        output.write_text(render_svg(config, stats, theme_name), encoding="utf-8")
        print(f"Wrote {output.name}: {json.dumps(stats, sort_keys=True)}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
