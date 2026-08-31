#!/usr/bin/env python3
"""Generate local Premium GitHub Activity SVGs for parsashafizade.

Standard-library only.

Rendered data intentionally comes from public GitHub endpoints so an
authenticated token cannot accidentally expose private repositories,
private language data, or private activity in a public README.

Token preference:
    PROFILE_REPOS_TOKEN
    GITHUB_TOKEN
    unauthenticated fallback

Generated files:
    Premium/assets/activity/stats.svg
    Premium/assets/activity/languages.svg
    Premium/assets/activity/contributions.svg
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


USER = "parsashafizade"
API = "https://api.github.com"

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Premium" / "assets" / "activity"

# Rolling public-activity window.
DAYS = 84

LANG_COLORS = (
    "#22D3EE",
    "#38BDF8",
    "#3B82F6",
    "#60A5FA",
    "#818CF8",
    "#14B8A6",
)


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def token() -> str:
    return (
        os.getenv("PROFILE_REPOS_TOKEN", "").strip()
        or os.getenv("GITHUB_TOKEN", "").strip()
    )


def get(path: str, auth: str, **params: Any) -> Any:
    url = path if path.startswith("http") else API + path

    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "parsashafizade-premium-activity",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if auth:
        headers["Authorization"] = f"Bearer {auth}"

    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API {exc.code}: {url}\n{body}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"GitHub request failed: {url}\n{exc}"
        ) from exc


def pages(
    path: str,
    auth: str,
    max_pages: int = 10,
    **params: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        batch = get(
            path,
            auth,
            per_page=100,
            page=page,
            **params,
        )

        if not isinstance(batch, list):
            raise RuntimeError(f"Expected list from {path}")

        result.extend(
            item for item in batch
            if isinstance(item, dict)
        )

        if len(batch) < 100:
            break

    return result


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def fetch_data(auth: str) -> dict[str, Any]:
    user = get(f"/users/{USER}", auth)

    # Intentionally use the public user-repository endpoint.
    # Even PROFILE_REPOS_TOKEN cannot cause private repo data to leak.
    repos = pages(
        f"/users/{USER}/repos",
        auth,
        type="owner",
        sort="pushed",
        direction="desc",
    )

    repos = [
        repo
        for repo in repos
        if repo.get("owner", {}).get("login", "").lower() == USER
        and not repo.get("private")
    ]

    # Forks and archived repositories should not inflate personal portfolio
    # stars, forks, or language footprint.
    portfolio = [
        repo
        for repo in repos
        if not repo.get("fork")
        and not repo.get("archived")
    ]

    # Aggregate real GitHub language byte counts.
    languages: Counter[str] = Counter()

    for repo in portfolio:
        try:
            mix = get(
                f"/repos/{USER}/{urllib.parse.quote(repo['name'])}/languages",
                auth,
            )
        except RuntimeError as exc:
            print(
                f"warning: language endpoint failed for "
                f"{repo['name']}: {exc}",
                file=sys.stderr,
            )
            continue

        if not isinstance(mix, dict):
            continue

        for name, size in mix.items():
            try:
                languages[str(name)] += max(0, int(size))
            except (TypeError, ValueError):
                continue

    language_mode = "byte-weighted public code"

    # Honest fallback if the language-byte endpoints are unavailable.
    if not languages:
        language_mode = "primary-language fallback"

        for repo in portfolio:
            if repo.get("language"):
                languages[str(repo["language"])] += 1

    # Explicitly public events only.
    # This prevents a powerful token from leaking private contribution data.
    events = pages(
        f"/users/{USER}/events/public",
        auth,
        max_pages=3,
    )

    now = datetime.now(timezone.utc)
    today = now.date()
    start = today - timedelta(days=DAYS - 1)

    daily_signal: defaultdict[date, int] = defaultdict(int)
    daily_events: defaultdict[date, int] = defaultdict(int)

    meaningful_event_types = {
        "PullRequestEvent",
        "PullRequestReviewEvent",
        "PullRequestReviewCommentEvent",
        "IssuesEvent",
        "IssueCommentEvent",
        "CreateEvent",
        "ReleaseEvent",
        "CommitCommentEvent",
    }

    for event in events:
        created = parse_datetime(event.get("created_at"))

        if not created:
            continue

        event_day = created.astimezone(timezone.utc).date()

        if not start <= event_day <= today:
            continue

        event_type = event.get("type")
        strength = 0

        if event_type == "PushEvent":
            # GitHub exposes the push size in the public event payload.
            # This is used only as a visualization intensity signal.
            try:
                strength = max(
                    1,
                    int(
                        (event.get("payload") or {})
                        .get("size", 1)
                    ),
                )
            except (TypeError, ValueError):
                strength = 1

        elif event_type in meaningful_event_types:
            strength = 1

        if strength:
            daily_signal[event_day] += strength
            daily_events[event_day] += 1

    return {
        "user": user,
        "repos": repos,
        "portfolio": portfolio,
        "languages": languages,
        "language_mode": language_mode,
        "daily_signal": dict(daily_signal),
        "daily_events": dict(daily_events),
        "now": now,
    }


# ---------------------------------------------------------------------------
# Shared SVG helpers
# ---------------------------------------------------------------------------

def latest_push(
    repos: list[dict[str, Any]],
) -> datetime | None:
    values = [
        pushed
        for repo in repos
        if (
            pushed := parse_datetime(
                repo.get("pushed_at")
            )
        )
    ]

    return max(values, default=None)


def compact_defs(
    prefix: str,
    accent: str,
) -> str:
    return f"""
<defs>
  <linearGradient id="{prefix}-bg" x1="12" y1="8" x2="418" y2="174">
    <stop stop-color="#0B1120"/>
    <stop offset=".56" stop-color="#0D1627"/>
    <stop offset="1" stop-color="#0F172A"/>
  </linearGradient>

  <linearGradient id="{prefix}-edge" x1="0" y1="0" x2="430" y2="180">
    <stop stop-color="{accent}" stop-opacity=".42"/>
    <stop offset=".55" stop-color="#334155" stop-opacity=".58"/>
    <stop offset="1" stop-color="#22D3EE" stop-opacity=".17"/>
  </linearGradient>

  <pattern id="{prefix}-grid" width="22" height="22" patternUnits="userSpaceOnUse">
    <path d="M22 0H0V22" stroke="#94A3B8" stroke-opacity=".043"/>
    <circle cx="1" cy="1" r=".65" fill="#22D3EE" fill-opacity=".045"/>
  </pattern>

  <clipPath id="{prefix}-clip">
    <rect x=".5" y=".5" width="429" height="179" rx="18"/>
  </clipPath>
</defs>
"""


COMPACT_STYLE = """
<style>
  .sans {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  }

  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }

  .reveal {
    opacity: 0;
    transform: translateY(5px);
    animation: reveal .65s cubic-bezier(.2,.8,.2,1) forwards;
  }

  .d2 { animation-delay: .09s; }
  .d3 { animation-delay: .18s; }

  .pulse {
    animation: pulse 4.2s ease-in-out infinite 1.1s;
  }

  .scan {
    animation: scan 7.4s ease-in-out infinite 1.3s;
  }

  .trace {
    stroke-dasharray: 160;
    stroke-dashoffset: 160;
    animation: trace 1.2s cubic-bezier(.4,0,.2,1) .28s forwards;
  }

  @keyframes reveal {
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @keyframes pulse {
    0%,100% { opacity: .38; }
    50% { opacity: 1; }
  }

  @keyframes scan {
    0%,22% {
      transform: translateX(0);
      opacity: 0;
    }

    34% { opacity: .72; }
    72% { opacity: .24; }

    82%,100% {
      transform: translateX(52px);
      opacity: 0;
    }
  }

  @keyframes trace {
    to { stroke-dashoffset: 0; }
  }

  @media (prefers-reduced-motion: reduce) {
    .reveal,
    .pulse,
    .scan,
    .trace {
      animation: none !important;
      opacity: 1 !important;
      transform: none !important;
      stroke-dashoffset: 0 !important;
    }
  }
</style>
"""


# ---------------------------------------------------------------------------
# stats.svg
# ---------------------------------------------------------------------------

def render_stats(data: dict[str, Any]) -> str:
    repos = data["repos"]
    portfolio = data["portfolio"]

    stars = sum(
        int(repo.get("stargazers_count") or 0)
        for repo in portfolio
    )

    forks = sum(
        int(repo.get("forks_count") or 0)
        for repo in portfolio
    )

    recent = sum(
        1
        for repo in portfolio
        if (
            pushed := parse_datetime(
                repo.get("pushed_at")
            )
        )
        and pushed >= data["now"] - timedelta(days=30)
    )

    pushed = latest_push(portfolio)

    pushed_label = (
        pushed.strftime("%b %d").upper()
        if pushed
        else "NO DATA"
    )

    updated = (
        data["now"]
        .strftime("UPDATED %b %d, %Y · UTC")
        .upper()
    )

    return f"""<svg width="430" height="180" viewBox="0 0 430 180" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
<title id="title">Parsa Shafizade GitHub Snapshot</title>
<desc id="desc">Local public GitHub summary: {len(repos)} repositories, {stars} stars, {forks} forks, and {recent} repositories pushed in the last 30 days.</desc>

{compact_defs("stats", "#38BDF8")}
{COMPACT_STYLE}

<rect x=".5" y=".5" width="429" height="179" rx="18" fill="url(#stats-bg)"/>

<g clip-path="url(#stats-clip)">
  <rect width="430" height="180" fill="url(#stats-grid)"/>
  <circle cx="360" cy="69" r="84" fill="#38BDF8" fill-opacity=".027"/>
</g>

<rect x=".5" y=".5" width="429" height="179" rx="18" stroke="url(#stats-edge)"/>

<g class="sans reveal">
  <circle cx="407" cy="23" r="3.2" fill="#22D3EE" class="pulse"/>
  <text x="396" y="26.5" text-anchor="end" fill="#64748B" font-size="8.2" font-weight="700" letter-spacing="1.2">GITHUB SNAPSHOT · PUBLIC SIGNAL</text>
  <text x="20" y="56" fill="#F8FAFC" font-size="17" font-weight="760">GitHub Signal</text>
  <text x="20" y="74" fill="#94A3B8" font-size="9.5">Current public repository activity, generated locally.</text>
</g>

<g class="sans reveal d2">
  <text x="20" y="111" fill="#F8FAFC" font-size="23" font-weight="800">{len(repos)}</text>
  <text x="20" y="125" fill="#64748B" font-size="7.6" font-weight="700">PUBLIC REPOS</text>

  <line x1="99" y1="94" x2="99" y2="130" stroke="#243247"/>

  <text x="118" y="111" fill="#E2E8F0" font-size="17" font-weight="760">{stars}</text>
  <text x="118" y="125" fill="#64748B" font-size="7.4" font-weight="700">STARS</text>

  <text x="180" y="111" fill="#E2E8F0" font-size="17" font-weight="760">{forks}</text>
  <text x="180" y="125" fill="#64748B" font-size="7.4" font-weight="700">FORKS</text>

  <text x="242" y="111" fill="#E2E8F0" font-size="17" font-weight="760">{recent}</text>
  <text x="242" y="125" fill="#64748B" font-size="7.4" font-weight="700">PUSHED / 30D</text>
</g>

<g transform="translate(319 48)">
  <g class="reveal d2">
    <rect width="89" height="80" rx="12" fill="#0B1626" stroke="#334155"/>

    <text class="mono" x="12" y="18" fill="#64748B" font-size="6.8">LAST PUSH</text>
    <text class="mono" x="12" y="34" fill="#BAE6FD" font-size="10" font-weight="700">{escape(pushed_label)}</text>

    <path class="trace" d="M12 57H29L37 48L48 61L60 52L77 52" stroke="#38BDF8" stroke-opacity=".68" stroke-width="1.2"/>

    <circle cx="77" cy="52" r="2.7" fill="#22D3EE" class="pulse"/>

    <rect x="12" y="69" width="62" height="4" rx="2" fill="#111C2D"/>
    <rect class="scan" x="12" y="69" width="20" height="4" rx="2" fill="#22D3EE" fill-opacity=".30"/>
  </g>
</g>

<line x1="20" y1="144" x2="410" y2="144" stroke="#1E293B"/>

<g class="mono reveal d3">
  <text x="20" y="163" fill="#475569" font-size="7.4">{escape(updated)}</text>
  <text x="320" y="163" fill="#7DD3FC" font-size="7.6" font-weight="700">LOCAL · AUTO-SYNCED</text>
</g>
</svg>"""


# ---------------------------------------------------------------------------
# languages.svg
# ---------------------------------------------------------------------------

def render_languages(data: dict[str, Any]) -> str:
    items = data["languages"].most_common(5)

    # Percentages use the total across every detected language,
    # not only the five rendered rows.
    total = sum(data["languages"].values())

    rows: list[str] = []

    for index, (name, value) in enumerate(items):
        y = 58 + index * 20

        pct = (
            value * 100 / total
            if total
            else 0
        )

        width = max(
            3,
            194 * pct / 100,
        )

        color = LANG_COLORS[index]

        rows.append(
            f"""
<g class="reveal d2">
  <text class="sans" x="20" y="{y}" fill="#CBD5E1" font-size="9.2" font-weight="650">{escape(name)}</text>
  <text class="mono" x="397" y="{y}" text-anchor="end" fill="#64748B" font-size="7.6">{pct:.1f}%</text>

  <rect x="126" y="{y - 7}" width="194" height="6" rx="3" fill="#111C2D"/>
  <rect x="126" y="{y - 7}" width="{width:.1f}" height="6" rx="3" fill="{color}" fill-opacity=".72"/>

  <circle cx="334" cy="{y - 4}" r="2.4" fill="{color}" class="pulse"/>
</g>
"""
        )

    if not rows:
        rows.append(
            """
<text class="sans reveal d2" x="20" y="86" fill="#94A3B8" font-size="10.5">
  No public language data is currently available.
</text>
"""
        )

    mode = data["language_mode"].upper()

    return f"""<svg width="430" height="180" viewBox="0 0 430 180" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
<title id="title">Parsa Shafizade Language Mix</title>
<desc id="desc">Top public repository languages using {escape(data["language_mode"])}.</desc>

{compact_defs("lang", "#22D3EE")}
{COMPACT_STYLE}

<rect x=".5" y=".5" width="429" height="179" rx="18" fill="url(#lang-bg)"/>

<g clip-path="url(#lang-clip)">
  <rect width="430" height="180" fill="url(#lang-grid)"/>
  <path d="M287 -20L451 87" stroke="#3B82F6" stroke-opacity=".03" stroke-width="64"/>
</g>

<rect x=".5" y=".5" width="429" height="179" rx="18" stroke="url(#lang-edge)"/>

<g class="sans reveal">
  <circle cx="23" cy="23" r="3.2" fill="#38BDF8" class="pulse"/>
  <text x="396" y="26.5" text-anchor="end" fill="#64748B" font-size="8.2" font-weight="700" letter-spacing="1.2">LANGUAGE MIX · PUBLIC REPOSITORIES</text>
  <text x="20" y="43" fill="#F8FAFC" font-size="15.5" font-weight="760">Development Stack</text>
</g>

{"".join(rows)}

<line x1="20" y1="155" x2="410" y2="155" stroke="#1E293B"/>

<g class="mono reveal d3">
  <text x="20" y="171" fill="#475569" font-size="6.9">{escape(mode)}</text>
  <text x="410" y="171" text-anchor="end" fill="#64748B" font-size="6.9">TOP {len(items)}</text>
</g>
</svg>"""


# ---------------------------------------------------------------------------
# contributions.svg
# ---------------------------------------------------------------------------

def intensity_level(
    value: int,
    maximum: int,
) -> int:
    if not value or not maximum:
        return 0

    ratio = value / maximum

    if ratio <= 0.20:
        return 1

    if ratio <= 0.45:
        return 2

    if ratio <= 0.70:
        return 3

    return 4


def render_contributions(data: dict[str, Any]) -> str:
    today = data["now"].date()
    start = today - timedelta(days=DAYS - 1)

    signal = data["daily_signal"]

    maximum = max(
        signal.values(),
        default=0,
    )

    colors = (
        "#111827",
        "#12304A",
        "#15506B",
        "#167896",
        "#22D3EE",
    )

    cells: list[str] = []

    x0 = 244
    y0 = 70

    for offset in range(DAYS):
        current_day = start + timedelta(days=offset)

        week, row = divmod(
            offset,
            7,
        )

        color = colors[
            intensity_level(
                signal.get(current_day, 0),
                maximum,
            )
        ]

        cells.append(
            f'<rect '
            f'x="{x0 + week * 44}" '
            f'y="{y0 + row * 15}" '
            f'width="18" height="10" rx="3" '
            f'fill="{color}" fill-opacity=".92"/>'
        )

    labels: list[str] = []

    for week in (0, 3, 6, 9, 11):
        label_day = (
            start
            + timedelta(days=week * 7)
        )

        labels.append(
            f'<text '
            f'x="{x0 + week * 44}" '
            f'y="188" '
            f'fill="#475569" '
            f'font-size="7" '
            f'class="mono">'
            f'{label_day.strftime("%b %d").upper()}'
            f'</text>'
        )

    events = sum(
        data["daily_events"].values()
    )

    active = sum(
        1
        for value in signal.values()
        if value > 0
    )

    peak = max(
        signal.values(),
        default=0,
    )

    updated = (
        data["now"]
        .strftime("UPDATED %b %d, %Y · UTC")
        .upper()
    )

    return f"""<svg width="100%" viewBox="0 0 900 230" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
<title id="title">Parsa Shafizade Public GitHub Activity</title>
<desc id="desc">Twelve-week local public GitHub activity view with {active} active days and {events} meaningful public events.</desc>

<defs>
  <linearGradient id="bg" x1="28" y1="10" x2="872" y2="220">
    <stop stop-color="#0B1120"/>
    <stop offset=".55" stop-color="#0D1627"/>
    <stop offset="1" stop-color="#0F172A"/>
  </linearGradient>

  <linearGradient id="edge" x1="0" y1="0" x2="900" y2="230">
    <stop stop-color="#38BDF8" stop-opacity=".38"/>
    <stop offset=".52" stop-color="#334155" stop-opacity=".54"/>
    <stop offset="1" stop-color="#22D3EE" stop-opacity=".18"/>
  </linearGradient>

  <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
    <path d="M28 0H0V28" stroke="#94A3B8" stroke-opacity=".04"/>
    <circle cx="1" cy="1" r=".7" fill="#22D3EE" fill-opacity=".045"/>
  </pattern>

  <clipPath id="clip">
    <rect x=".5" y=".5" width="899" height="229" rx="22"/>
  </clipPath>
</defs>

<style>
  .sans {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  }}

  .mono {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }}

  .reveal {{
    opacity: 0;
    transform: translateY(5px);
    animation: reveal .7s cubic-bezier(.2,.8,.2,1) forwards;
  }}

  .d2 {{ animation-delay: .1s; }}
  .d3 {{ animation-delay: .2s; }}

  .pulse {{
    animation: pulse 4.2s ease-in-out infinite 1.2s;
  }}

  .runner {{
    animation: runner 8.6s ease-in-out infinite 1.6s;
  }}

  @keyframes reveal {{
    to {{
      opacity: 1;
      transform: translateY(0);
    }}
  }}

  @keyframes pulse {{
    0%,100% {{ opacity: .35; }}
    50% {{ opacity: 1; }}
  }}

  @keyframes runner {{
    0%,18% {{
      transform: translateX(0);
      opacity: 0;
    }}

    30% {{ opacity: .9; }}
    78% {{ opacity: .38; }}

    88%,100% {{
      transform: translateX(182px);
      opacity: 0;
    }}
  }}

  @media (prefers-reduced-motion: reduce) {{
    .reveal,
    .pulse,
    .runner {{
      animation: none !important;
      opacity: 1 !important;
      transform: none !important;
    }}
  }}
</style>

<rect x=".5" y=".5" width="899" height="229" rx="22" fill="url(#bg)"/>

<g clip-path="url(#clip)">
  <rect width="900" height="230" fill="url(#grid)"/>
  <circle cx="667" cy="103" r="188" fill="#38BDF8" fill-opacity=".025"/>
</g>

<rect x=".5" y=".5" width="899" height="229" rx="22" stroke="url(#edge)"/>

<g class="sans reveal">
  <circle cx="38" cy="33" r="3.2" fill="#22D3EE" class="pulse"/>

  <text x="50" y="36" fill="#64748B" font-size="8.4" font-weight="700" letter-spacing="1.35">
    PUBLIC ACTIVITY · LAST 12 WEEKS
  </text>

  <text x="38" y="72" fill="#F8FAFC" font-size="21" font-weight="780">
    Build Rhythm
  </text>

  <text x="38" y="92" fill="#94A3B8" font-size="10.5">
    Recent public engineering activity, generated locally.
  </text>
</g>

<g class="sans reveal d2">
  <text x="38" y="128" fill="#E2E8F0" font-size="20" font-weight="760">{active}</text>
  <text x="38" y="142" fill="#64748B" font-size="7.5" font-weight="700">ACTIVE DAYS</text>

  <text x="104" y="128" fill="#E2E8F0" font-size="20" font-weight="760">{events}</text>
  <text x="104" y="142" fill="#64748B" font-size="7.5" font-weight="700">PUBLIC EVENTS</text>

  <text x="176" y="128" fill="#E2E8F0" font-size="20" font-weight="760">{peak}</text>
  <text x="176" y="142" fill="#64748B" font-size="7.5" font-weight="700">PEAK SIGNAL</text>
</g>

<g class="reveal d2">
  <rect x="226" y="50" width="632" height="149" rx="16" fill="#0A1422" fill-opacity=".62" stroke="#1E293B"/>

  <text class="mono" x="244" y="62" fill="#475569" font-size="7.2" letter-spacing="1.05">
    PUBLIC EVENT INTENSITY
  </text>

  {"".join(cells)}

  {"".join(labels)}

  <g transform="translate(696 183)">
    <text class="mono" x="0" y="7" fill="#475569" font-size="6.8">QUIET</text>

    <rect x="39" y="0" width="8" height="8" rx="2" fill="#111827"/>
    <rect x="51" y="0" width="8" height="8" rx="2" fill="#12304A"/>
    <rect x="63" y="0" width="8" height="8" rx="2" fill="#15506B"/>
    <rect x="75" y="0" width="8" height="8" rx="2" fill="#167896"/>
    <rect x="87" y="0" width="8" height="8" rx="2" fill="#22D3EE"/>

    <text class="mono" x="102" y="7" fill="#475569" font-size="6.8">ACTIVE</text>
  </g>
</g>

<g class="reveal d3">
  <path d="M38 171H69L79 163L91 175L105 166L128 166L139 158L153 170L204 170" stroke="#38BDF8" stroke-opacity=".34" stroke-width="1.2"/>

  <circle cx="204" cy="170" r="2.6" fill="#22D3EE" class="pulse"/>
  <circle cx="43" cy="171" r="2.3" fill="#7DD3FC" class="runner"/>
</g>

<line x1="38" y1="207" x2="862" y2="207" stroke="#1E293B"/>

<g class="mono reveal d3">
  <text x="38" y="221" fill="#475569" font-size="6.8">
    SOURCE: GITHUB PUBLIC EVENTS · PRIVATE ACTIVITY EXCLUDED
  </text>

  <text x="862" y="221" text-anchor="end" fill="#64748B" font-size="6.8">
    {escape(updated)}
  </text>
</g>
</svg>"""


# ---------------------------------------------------------------------------
# Write generated files
# ---------------------------------------------------------------------------

def write_file(
    path: Path,
    content: str,
) -> bool:
    content = content.rstrip() + "\n"

    if (
        path.exists()
        and path.read_text(encoding="utf-8") == content
    ):
        return False

    path.write_text(
        content,
        encoding="utf-8",
    )

    return True


def main() -> int:
    auth = token()

    if not auth:
        print(
            "warning: running without GitHub token; "
            "unauthenticated rate limits are lower",
            file=sys.stderr,
        )

    data = fetch_data(auth)

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = {
        OUT / "stats.svg":
            render_stats(data),

        OUT / "languages.svg":
            render_languages(data),

        OUT / "contributions.svg":
            render_contributions(data),
    }

    changed = 0

    for path, content in outputs.items():
        if write_file(path, content):
            changed += 1
            print(
                f"updated "
                f"{path.relative_to(ROOT)}"
            )
        else:
            print(
                f"unchanged "
                f"{path.relative_to(ROOT)}"
            )

    print(
        f"done: {changed} file(s) changed"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1)
