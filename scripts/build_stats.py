#!/usr/bin/env python3
"""Generate the README stats cards from the GitHub and LeetCode APIs.

Writes assets/stats-<card>-<theme>.svg. Uses only the standard library, and runs
daily from .github/workflows/stats.yml. Run it locally with:

    GITHUB_TOKEN=$(gh auth token) python3 scripts/build_stats.py
"""
import calendar as cal
import datetime as dt
import html
import json
import os
import pathlib
import urllib.request

GITHUB_LOGIN = "aaryan-codes56"
LEETCODE_USER = "DIpiow8PMa"
ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"
LEETCODE_CACHE = ASSETS / "leetcode.json"

SANS = 'ui-sans-serif, -apple-system, &quot;Segoe UI&quot;, Helvetica, Arial, sans-serif'
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
WIDTH, HEIGHT = 400, 210
LEFT, RIGHT = 20, 380

THEMES = {
    "dark": {
        "panel": "#161b22", "border": "#30363d", "text": "#e6edf3", "muted": "#9198a1",
        "track": "#30363d", "accent": "#e3b341",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"], "other": "#656c76",
    },
    "light": {
        "panel": "#f6f8fa", "border": "#d1d9e0", "text": "#1f2328", "muted": "#59636e",
        "track": "#d1d9e0", "accent": "#9a6700",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"], "other": "#8c959f",
    },
}
# Each language keeps its color whatever its rank, so colors stay stable over time.
LANGUAGE_SLOTS = ["JavaScript", "Python", "TypeScript", "CSS", "HTML"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
      commitContributionsByRepository(maxRepositories: 12) {
        repository { name isPrivate }
        contributions { totalCount }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      nodes { languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } } }
    }
  }
}"""

LEETCODE_QUERY = """
query($u: String!) {
  allQuestionsCount { difficulty count }
  matchedUser(username: $u) { submitStats { acSubmissionNum { difficulty count } } }
}"""


def post_json(url, payload, headers):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "profile-stats", **headers},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_github():
    result = post_json(
        "https://api.github.com/graphql",
        {"query": QUERY, "variables": {"login": GITHUB_LOGIN}},
        {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"},
    )
    if result.get("errors"):
        raise RuntimeError(result["errors"])
    return result["data"]["user"]


def fetch_leetcode():
    """Return solved and total counts, falling back to the last good values if LeetCode refuses."""
    try:
        data = post_json(
            "https://leetcode.com/graphql",
            {"query": LEETCODE_QUERY, "variables": {"u": LEETCODE_USER}},
            {"Referer": "https://leetcode.com"},
        )["data"]
        stats = {
            "solved": {r["difficulty"]: r["count"] for r in data["matchedUser"]["submitStats"]["acSubmissionNum"]},
            "total": {r["difficulty"]: r["count"] for r in data["allQuestionsCount"]},
        }
    except Exception as error:  # LeetCode sometimes blocks CI runners.
        print(f"LeetCode fetch failed ({error}); using cached values")
        return json.loads(LEETCODE_CACHE.read_text())
    LEETCODE_CACHE.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    return stats


def longest_streak(days):
    longest = run = 0
    for day in days:
        run = run + 1 if day["contributionCount"] else 0
        longest = max(longest, run)
    return longest


def language_shares(user):
    totals = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"] if edge["node"]["name"] in LANGUAGE_SLOTS else "Other"
            totals[name] = totals.get(name, 0) + edge["size"]
    grand_total = sum(totals.values()) or 1
    return sorted(((name, size / grand_total) for name, size in totals.items()), key=lambda item: -item[1])


def rounded_top(x, y, width, baseline):
    radius = min(3, width / 2, baseline - y)
    return (
        f"M{x:.1f} {baseline}V{y + radius:.1f}Q{x:.1f} {y:.1f} {x + radius:.1f} {y:.1f}"
        f"H{x + width - radius:.1f}Q{x + width:.1f} {y:.1f} {x + width:.1f} {y + radius:.1f}V{baseline}Z"
    )


def vertical_bars(values, labels):
    top, baseline = 66, 172
    peak = max(values) or 1
    step = (RIGHT - LEFT) / len(values)
    width = min(step - 6, 24)
    out = [f'<line class="rail" x1="{LEFT}" y1="{baseline}" x2="{RIGHT}" y2="{baseline}"/>']
    peak_drawn = False
    for index, (value, label) in enumerate(zip(values, labels)):
        center = LEFT + step * (index + 0.5)
        out.append(f'<text class="tick" x="{center:.1f}" y="{baseline + 20}" text-anchor="middle">{label}</text>')
        if not value:
            continue
        bar_top = baseline - max(value / peak * (baseline - top), 3)
        out.append(
            f'<path class="bar grow" style="animation-delay:{index * 35}ms" '
            f'd="{rounded_top(center - width / 2, bar_top, width, baseline)}"/>'
        )
        if value == peak and not peak_drawn:
            peak_drawn = True
            out.append(f'<text class="small" x="{center:.1f}" y="{bar_top - 7:.1f}" text-anchor="middle">{value}</text>')
    return out


def rows(items, top, row_height):
    """Draw labelled progress rows. items: (label, value_text, fraction, css fill)."""
    out = []
    for index, (label, value, fraction, fill) in enumerate(items):
        y = top + index * row_height
        length = max(fraction * (RIGHT - LEFT), 3)
        out.append(f'<text class="small" x="{LEFT}" y="{y}">{html.escape(label)}</text>')
        out.append(f'<text class="small" x="{RIGHT}" y="{y}" text-anchor="end">{value}</text>')
        out.append(f'<rect class="track" x="{LEFT}" y="{y + 6}" width="{RIGHT - LEFT}" height="6" rx="3"/>')
        out.append(
            f'<rect class="fill" style="animation-delay:{index * 70}ms" x="{LEFT}" y="{y + 6}" '
            f'width="{length:.1f}" height="6" rx="3" fill="{fill}"/>'
        )
    return out


def svg(palette, title, body, summary, note=""):
    p = palette
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{html.escape(summary)}">',
        "<style>",
        f'.title {{ font: 600 11px {MONO}; fill: {p["muted"]}; letter-spacing: 1px; }}',
        f'.value {{ font: 650 25px {SANS}; fill: {p["text"]}; letter-spacing: -.4px; }}',
        f'.small {{ font: 400 12px {SANS}; fill: {p["text"]}; }}',
        f'.muted {{ font: 400 12px {SANS}; fill: {p["muted"]}; }}',
        f'.tick {{ font: 400 10.5px {MONO}; fill: {p["muted"]}; }}',
        f'.rail {{ stroke: {p["track"]}; stroke-width: 1; }}',
        f'.track {{ fill: {p["track"]}; opacity: .55; }}',
        f'.bar {{ fill: {p["accent"]}; }}',
        ".grow { transform-box: fill-box; transform-origin: bottom; animation: grow .7s cubic-bezier(.2,.7,.2,1) both; }",
        ".fill { transform-box: fill-box; transform-origin: left; animation: fill .8s cubic-bezier(.2,.7,.2,1) both; }",
        "@keyframes grow { from { transform: scaleY(0); } }",
        "@keyframes fill { from { transform: scaleX(0); } }",
        "@media (prefers-reduced-motion: reduce) { .grow, .fill { animation: none; } }",
        "</style>",
        f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="10" fill="{p["panel"]}" stroke="{p["border"]}"/>',
        f'<text class="title" x="{LEFT}" y="32">{title}</text>',
        f'<text class="title" x="{RIGHT}" y="32" text-anchor="end">{note}</text>' if note else "",
        *body,
        "</svg>",
        "",
    ])


def overview_card(palette, user):
    collection = user["contributionsCollection"]
    calendar = collection["contributionCalendar"]
    days = [day for week in calendar["weeks"] for day in week["contributionDays"]]
    active_days = sum(1 for day in days if day["contributionCount"])
    active_weeks = sum(1 for week in calendar["weeks"] if any(d["contributionCount"] for d in week["contributionDays"]))
    tiles = [
        (calendar["totalContributions"], "contributions"),
        (collection["totalCommitContributions"], "commits"),
        (collection["totalPullRequestContributions"], "pull requests"),
        (active_days, "active days"),
        (active_weeks, "active weeks"),
        (longest_streak(days), "best streak, days"),
    ]
    body = []
    for index, (value, label) in enumerate(tiles):
        x = LEFT + 124 * (index % 3)
        y = 86 + 76 * (index // 3)
        body.append(f'<text class="value" x="{x}" y="{y}">{value}</text>')
        body.append(f'<text class="muted" x="{x + 1}" y="{y + 20}">{label}</text>')
    return svg(palette, "GITHUB", body, f'{calendar["totalContributions"]} contributions in the past 12 months.', "12 MONTHS")


def monthly_card(palette, user):
    totals = {}
    for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            totals[day["date"][:7]] = totals.get(day["date"][:7], 0) + day["contributionCount"]
    months = sorted(totals)
    labels = [cal.month_abbr[int(month[5:])] for month in months]
    return svg(palette, "MONTHLY ACTIVITY", vertical_bars([totals[m] for m in months], labels), "Contributions per month.")


def weekday_card(palette, user):
    totals = [0] * 7
    for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            totals[dt.date.fromisoformat(day["date"]).weekday()] += day["contributionCount"]
    return svg(palette, "BY WEEKDAY", vertical_bars(totals, [cal.day_abbr[i] for i in range(7)]), "Contributions by weekday.")


def repos_card(palette, user):
    repos = [
        (entry["repository"]["name"], entry["contributions"]["totalCount"])
        for entry in user["contributionsCollection"]["commitContributionsByRepository"]
        if not entry["repository"]["isPrivate"] and entry["repository"]["name"] != GITHUB_LOGIN
    ]
    repos = sorted(repos, key=lambda item: -item[1])[:5]
    peak = max((count for _, count in repos), default=1)
    items = [(name, count, count / peak, palette["accent"]) for name, count in repos]
    return svg(palette, "TOP REPOS", rows(items, 62, 29), "Public repositories with the most commits.", "COMMITS")


def languages_card(palette, user):
    shares = language_shares(user)[:6]
    items = []
    for name, share in shares:
        color = palette["other"] if name == "Other" else palette["series"][LANGUAGE_SLOTS.index(name)]
        percent = f"{share * 100:.0f}%" if share >= 0.005 else "&lt;1%"
        items.append((name, percent, share, color))
    return svg(palette, "LANGUAGES", rows(items, 58, 27), "Languages used across public repositories.", "PUBLIC REPOS")


def leetcode_card(palette, stats):
    solved, total = stats["solved"], stats["total"]
    body = [
        f'<text class="value" x="{LEFT}" y="76">{solved["All"]}</text>',
        f'<text class="muted" x="{LEFT + 16 * len(str(solved["All"])) + 6}" y="76">problems solved</text>',
    ]
    items = [
        (level, f"{solved[level]} / {total[level]}", solved[level] / (total[level] or 1), palette["accent"])
        for level in ("Easy", "Medium", "Hard")
    ]
    body += rows(items, 110, 34)
    return svg(palette, "LEETCODE", body, f'{solved["All"]} LeetCode problems solved.')


def main():
    user = fetch_github()
    leetcode = fetch_leetcode()
    for theme, palette in THEMES.items():
        cards = {
            "overview": overview_card(palette, user),
            "monthly": monthly_card(palette, user),
            "weekday": weekday_card(palette, user),
            "repos": repos_card(palette, user),
            "languages": languages_card(palette, user),
            "leetcode": leetcode_card(palette, leetcode),
        }
        for name, content in cards.items():
            (ASSETS / f"stats-{name}-{theme}.svg").write_text(content)


if __name__ == "__main__":
    main()
