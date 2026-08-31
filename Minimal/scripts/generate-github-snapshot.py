#!/usr/bin/env python3
"""
Generate Minimal/assets/github-snapshot.svg from real GitHub profile data.

Data sources:
- GitHub REST API:
    profile, public repository count, avatar, repository stars
- GitHub GraphQL API:
    current-year contribution calendar and daily contribution counts

Requirements:
- Python standard library only
- GITHUB_TOKEN must be available for the GraphQL request

The generated SVG embeds the GitHub avatar as a base64 data URI so the final
card is self-contained.
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from string import Template
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape as xml_escape


USERNAME = "parsashafizade"
DISPLAY_NAME = "Parsa Shafizade"

REST_ROOT = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

MINIMAL_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = MINIMAL_ROOT / "assets" / "github-snapshot.svg"

MAX_AVATAR_BYTES = 2_000_000
ACTIVITY_DAYS = 28


SVG_TEMPLATE = Template(
    r'''<svg xmlns="http://www.w3.org/2000/svg"
     width="100%"
     height="220"
     viewBox="0 0 900 220"
     fill="none"
     role="img"
     aria-labelledby="title desc">

  <title id="title">${display_name} — GitHub Activity</title>
  <desc id="desc">${description}</desc>

  <defs>
    <!-- BACKGROUND -->
    <linearGradient id="bg"
                    x1="10"
                    y1="10"
                    x2="890"
                    y2="210"
                    gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#0B1120"/>
      <stop offset="0.56" stop-color="#0D1525"/>
      <stop offset="1" stop-color="#0F172A"/>
    </linearGradient>

    <radialGradient id="haze"
                    cx="0"
                    cy="0"
                    r="1"
                    gradientUnits="userSpaceOnUse"
                    gradientTransform="translate(665 108) scale(360 190)">
      <stop stop-color="#38BDF8" stop-opacity="0.075"/>
      <stop offset="0.65" stop-color="#22D3EE" stop-opacity="0.02"/>
      <stop offset="1" stop-color="#22D3EE" stop-opacity="0"/>
    </radialGradient>

    <linearGradient id="accent-line"
                    x1="300"
                    y1="0"
                    x2="840"
                    y2="0"
                    gradientUnits="userSpaceOnUse">
      <stop stop-color="#38BDF8" stop-opacity="0.16"/>
      <stop offset="0.5" stop-color="#38BDF8" stop-opacity="0.72"/>
      <stop offset="1" stop-color="#22D3EE" stop-opacity="0.14"/>
    </linearGradient>

    <pattern id="grid"
             width="24"
             height="24"
             patternUnits="userSpaceOnUse">
      <path d="M24 0H0V24"
            stroke="#94A3B8"
            stroke-width="0.65"
            opacity="0.06"/>
    </pattern>

    <clipPath id="panel-clip">
      <rect x="10" y="10" width="880" height="200" rx="22"/>
    </clipPath>

    <clipPath id="avatar-clip">
      <circle cx="76" cy="79" r="28"/>
    </clipPath>

    <clipPath id="activity-clip">
      <rect x="292" y="160" width="548" height="32" rx="5"/>
    </clipPath>

    <filter id="micro-glow"
            x="-180%"
            y="-180%"
            width="460%"
            height="460%"
            color-interpolation-filters="sRGB">
      <feGaussianBlur stdDeviation="1.8" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <style>
      .ui {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      }

      .mono {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      }

      .reveal {
        opacity: 0;
        animation: reveal .95s cubic-bezier(.2,.72,.2,1) .08s forwards;
      }

      .accent-draw {
        stroke-dasharray: 540;
        stroke-dashoffset: 540;
        animation: draw 1.3s cubic-bezier(.25,.7,.2,1) .4s forwards;
      }

      .activity-scan {
        animation: scan 7s ease-in-out infinite;
      }

      .activity-pulse {
        animation: pulse 5.6s ease-in-out infinite;
      }

      @keyframes reveal {
        from {
          opacity: 0;
          transform: translateY(6px);
        }

        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      @keyframes draw {
        to {
          stroke-dashoffset: 0;
        }
      }

      @keyframes scan {
        0%, 12% {
          transform: translateX(-60px);
          opacity: 0;
        }

        25% {
          opacity: .25;
        }

        74% {
          opacity: .12;
        }

        88%, 100% {
          transform: translateX(550px);
          opacity: 0;
        }
      }

      @keyframes pulse {
        0%, 100% {
          opacity: .38;
        }

        50% {
          opacity: .95;
        }
      }

      @media (prefers-reduced-motion: reduce) {
        .reveal,
        .accent-draw,
        .activity-scan,
        .activity-pulse {
          animation: none !important;
        }

        .reveal {
          opacity: 1;
          transform: none;
        }

        .accent-draw {
          stroke-dashoffset: 0;
        }

        .travel-dot {
          display: none;
        }
      }
    </style>
  </defs>

  <!-- BACKGROUND -->
  <rect x="10"
        y="10"
        width="880"
        height="200"
        rx="22"
        fill="url(#bg)"
        stroke="#334155"
        stroke-width="1"/>

  <g clip-path="url(#panel-clip)">
    <rect x="10"
          y="10"
          width="880"
          height="200"
          fill="url(#haze)"/>

    <rect x="10"
          y="10"
          width="880"
          height="200"
          fill="url(#grid)"/>

    <path d="M260 32V188"
          stroke="#64748B"
          stroke-width="1"
          stroke-dasharray="2 8"
          opacity="0.14"/>

    <path d="M36 40H52V27"
          stroke="#64748B"
          opacity="0.22"/>

    <path d="M864 40H848V27"
          stroke="#64748B"
          opacity="0.22"/>

    <path d="M36 180H52V193"
          stroke="#64748B"
          opacity="0.22"/>

    <path d="M864 180H848V193"
          stroke="#64748B"
          opacity="0.22"/>
  </g>

  <!-- IDENTITY -->
  <g class="reveal">
    <image href="${avatar_data_uri}"
           x="48"
           y="51"
           width="56"
           height="56"
           preserveAspectRatio="xMidYMid slice"
           clip-path="url(#avatar-clip)"/>

    <circle cx="76"
            cy="79"
            r="28.5"
            fill="none"
            stroke="#475569"
            stroke-width="1"/>

    <circle cx="98"
            cy="101"
            r="4.3"
            fill="#0B1120"/>

    <circle class="activity-pulse"
            cx="98"
            cy="101"
            r="2.5"
            fill="#38BDF8"/>

    <text x="119"
          y="73"
          class="ui"
          fill="#F8FAFC"
          font-size="19"
          font-weight="700"
          letter-spacing="-0.25">
      ${display_name}
    </text>

    <text x="119"
          y="96"
          class="ui"
          fill="#94A3B8"
          font-size="11.5"
          font-weight="500">
      GitHub Activity
    </text>

    <path d="M49 128H222"
          stroke="#334155"
          stroke-width="1"/>

    <path d="M49 128H111"
          stroke="#38BDF8"
          stroke-width="1.4"
          stroke-linecap="round"
          opacity="0.72"/>

    <text x="49"
          y="151"
          class="ui"
          fill="#64748B"
          font-size="10">
      Mobile Application Developer
    </text>
  </g>

  <!-- METRICS -->
  <g class="reveal">
    <!-- Contributions -->
    <g>
      <text x="300"
            y="79"
            class="ui"
            fill="#F8FAFC"
            font-size="29"
            font-weight="720">
        ${contributions}
      </text>

      <text x="300"
            y="104"
            class="ui"
            fill="#CBD5E1"
            font-size="11"
            font-weight="600">
        Contributions
      </text>

      <text x="300"
            y="120"
            class="ui"
            fill="#64748B"
            font-size="9.5">
        this year
      </text>
    </g>

    <path d="M416 54V126"
          stroke="#334155"
          stroke-width="1"/>

    <!-- Active Days -->
    <g>
      <text x="440"
            y="79"
            class="ui"
            fill="#F8FAFC"
            font-size="29"
            font-weight="720">
        ${active_days}
      </text>

      <text x="440"
            y="104"
            class="ui"
            fill="#CBD5E1"
            font-size="11"
            font-weight="600">
        Active Days
      </text>

      <text x="440"
            y="120"
            class="ui"
            fill="#64748B"
            font-size="9.5">
        this year
      </text>
    </g>

    <path d="M556 54V126"
          stroke="#334155"
          stroke-width="1"/>

    <!-- Repositories -->
    <g>
      <text x="580"
            y="79"
            class="ui"
            fill="#F8FAFC"
            font-size="29"
            font-weight="720">
        ${repositories}
      </text>

      <text x="580"
            y="104"
            class="ui"
            fill="#CBD5E1"
            font-size="11"
            font-weight="600">
        Repositories
      </text>
    </g>

    <path d="M696 54V126"
          stroke="#334155"
          stroke-width="1"/>

    <!-- Stars -->
    <g>
      <text x="720"
            y="79"
            class="ui"
            fill="#F8FAFC"
            font-size="29"
            font-weight="720">
        ${stars}
      </text>

      <text x="720"
            y="104"
            class="ui"
            fill="#CBD5E1"
            font-size="11"
            font-weight="600">
        Stars
      </text>
    </g>

    <path class="accent-draw"
          d="M300 140H840"
          stroke="url(#accent-line)"
          stroke-width="1.2"
          stroke-linecap="round"/>

    <circle class="travel-dot"
            r="2.4"
            fill="#22D3EE"
            filter="url(#micro-glow)">
      <animateMotion dur="7.6s"
                     repeatCount="indefinite"
                     path="M300 140H840"/>

      <animate attributeName="opacity"
               values="0;0.85;0.85;0"
               keyTimes="0;0.08;0.92;1"
               dur="7.6s"
               repeatCount="indefinite"/>
    </circle>
  </g>

  <!-- RECENT ACTIVITY -->
  <g class="reveal">
    <text x="300"
          y="159"
          class="ui"
          fill="#94A3B8"
          font-size="9.5"
          font-weight="600">
      Recent activity
    </text>

    <text x="840"
          y="159"
          text-anchor="end"
          class="ui"
          fill="#475569"
          font-size="9">
      Last 28 days
    </text>

    <path d="M300 190H840"
          stroke="#334155"
          stroke-width="1"
          opacity="0.7"/>

    <g>
${activity_bars}
    </g>

    <g clip-path="url(#activity-clip)">
      <rect class="activity-scan"
            x="292"
            y="164"
            width="54"
            height="26"
            fill="#38BDF8"
            opacity="0"/>
    </g>
  </g>

  <!-- FOOTER -->
  <text x="840"
        y="202"
        text-anchor="end"
        class="ui"
        fill="#475569"
        font-size="8.5">
    Updated ${updated}
  </text>
</svg>
'''
)


class GitHubAPIError(RuntimeError):
    """Raised when GitHub data cannot be retrieved safely."""


def api_headers(*, authenticated: bool = True) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "minimal-github-activity-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if authenticated and TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    return headers


def parse_error_message(body: bytes) -> str:
    if not body:
        return ""

    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return ""

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str):
            return message.strip()

    return ""


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    authenticated: bool = True,
) -> Any:
    body = None
    headers = api_headers(authenticated=authenticated)

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read()

    except HTTPError as error:
        error_body = error.read()
        remaining = error.headers.get("X-RateLimit-Remaining")

        if error.code in (403, 429) and remaining == "0":
            reset = error.headers.get("X-RateLimit-Reset")
            reset_text = "unknown"

            if reset:
                try:
                    reset_time = datetime.fromtimestamp(
                        int(reset),
                        tz=timezone.utc,
                    )
                    reset_text = reset_time.strftime("%Y-%m-%d %H:%M UTC")
                except (TypeError, ValueError, OSError):
                    pass

            raise GitHubAPIError(
                f"GitHub API rate limit exceeded. Reset: {reset_text}."
            ) from error

        detail = parse_error_message(error_body)

        message = f"GitHub API returned HTTP {error.code}"
        if detail:
            message += f": {detail}"

        raise GitHubAPIError(message) from error

    except URLError as error:
        raise GitHubAPIError(
            f"Could not connect to GitHub: {error.reason}"
        ) from error

    except TimeoutError as error:
        raise GitHubAPIError(
            "GitHub request timed out."
        ) from error

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise GitHubAPIError(
            "GitHub returned invalid JSON."
        ) from error


def fetch_profile() -> dict[str, Any]:
    payload = request_json(
        f"{REST_ROOT}/users/{USERNAME}",
        authenticated=True,
    )

    if not isinstance(payload, dict):
        raise GitHubAPIError("Unexpected profile response.")

    return payload


def fetch_repositories() -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1

    while True:
        query = urlencode(
            {
                "type": "owner",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            }
        )

        payload = request_json(
            f"{REST_ROOT}/users/{USERNAME}/repos?{query}",
            authenticated=True,
        )

        if not isinstance(payload, list):
            raise GitHubAPIError(
                "Unexpected repository response."
            )

        batch = [
            repo
            for repo in payload
            if isinstance(repo, dict)
            and repo.get("private") is not True
        ]

        repositories.extend(batch)

        if len(payload) < 100:
            break

        page += 1

        if page > 100:
            raise GitHubAPIError(
                "Repository pagination exceeded the safety limit."
            )

    return repositories


def fetch_contribution_calendar(
    now: datetime,
) -> tuple[int, list[dict[str, Any]]]:
    if not TOKEN:
        raise GitHubAPIError(
            "GITHUB_TOKEN is required for GitHub contribution data."
        )

    year_start = datetime(
        now.year,
        1,
        1,
        0,
        0,
        0,
        tzinfo=timezone.utc,
    )

    query = """
    query GitHubActivity(
      $login: String!,
      $from: DateTime!,
      $to: DateTime!
    ) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """

    variables = {
        "login": USERNAME,
        "from": year_start.isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z"),
    }

    payload = request_json(
        GRAPHQL_URL,
        method="POST",
        payload={
            "query": query,
            "variables": variables,
        },
        authenticated=True,
    )

    if not isinstance(payload, dict):
        raise GitHubAPIError(
            "Unexpected GraphQL response."
        )

    errors = payload.get("errors")

    if isinstance(errors, list) and errors:
        messages = []

        for error in errors:
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str):
                    messages.append(message)

        detail = "; ".join(messages) or "Unknown GraphQL error."

        raise GitHubAPIError(
            f"GitHub GraphQL request failed: {detail}"
        )

    try:
        calendar = (
            payload["data"]["user"]
            ["contributionsCollection"]
            ["contributionCalendar"]
        )
    except (KeyError, TypeError) as error:
        raise GitHubAPIError(
            "Contribution calendar was missing from the GraphQL response."
        ) from error

    if not isinstance(calendar, dict):
        raise GitHubAPIError(
            "Contribution calendar had an invalid format."
        )

    total = calendar.get("totalContributions")

    if not isinstance(total, int):
        raise GitHubAPIError(
            "Contribution total was missing or invalid."
        )

    days: list[dict[str, Any]] = []

    weeks = calendar.get("weeks", [])

    if isinstance(weeks, list):
        for week in weeks:
            if not isinstance(week, dict):
                continue

            contribution_days = week.get("contributionDays", [])

            if not isinstance(contribution_days, list):
                continue

            for day in contribution_days:
                if isinstance(day, dict):
                    days.append(day)

    return total, days


def fetch_avatar_data_uri(avatar_url: str) -> str:
    if not avatar_url.startswith("https://"):
        raise GitHubAPIError(
            "GitHub profile did not provide a valid HTTPS avatar URL."
        )

    request = Request(
        avatar_url,
        headers={
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*",
            "User-Agent": "minimal-github-activity-generator",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=25) as response:
            content_type = (
                response.headers.get_content_type()
                or "application/octet-stream"
            )

            image_bytes = response.read(MAX_AVATAR_BYTES + 1)

    except HTTPError as error:
        raise GitHubAPIError(
            f"Avatar request returned HTTP {error.code}."
        ) from error

    except URLError as error:
        raise GitHubAPIError(
            f"Could not download GitHub avatar: {error.reason}"
        ) from error

    except TimeoutError as error:
        raise GitHubAPIError(
            "GitHub avatar request timed out."
        ) from error

    if len(image_bytes) > MAX_AVATAR_BYTES:
        raise GitHubAPIError(
            "GitHub avatar exceeded the allowed embedded image size."
        )

    if content_type not in {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            content_type = "image/png"
        elif image_bytes.startswith(b"\xff\xd8\xff"):
            content_type = "image/jpeg"
        elif (
            image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        ):
            content_type = "image/webp"
        elif image_bytes.startswith((b"GIF87a", b"GIF89a")):
            content_type = "image/gif"
        else:
            raise GitHubAPIError(
                f"Unsupported GitHub avatar format: {content_type}"
            )

    encoded = base64.b64encode(image_bytes).decode("ascii")

    return f"data:{content_type};base64,{encoded}"


def contribution_days_for_current_year(
    raw_days: list[dict[str, Any]],
    *,
    today: date,
) -> dict[date, int]:
    year_start = date(today.year, 1, 1)
    result: dict[date, int] = {}

    for item in raw_days:
        raw_date = item.get("date")
        raw_count = item.get("contributionCount")

        if not isinstance(raw_date, str):
            continue

        if not isinstance(raw_count, int):
            continue

        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            continue

        if year_start <= day <= today:
            result[day] = max(0, raw_count)

    return result


def recent_activity_counts(
    contribution_days: dict[date, int],
    *,
    today: date,
) -> list[int]:
    start = today - timedelta(days=ACTIVITY_DAYS - 1)

    return [
        contribution_days.get(
            start + timedelta(days=offset),
            0,
        )
        for offset in range(ACTIVITY_DAYS)
    ]


def render_activity_bars(counts: list[int]) -> str:
    if len(counts) != ACTIVITY_DAYS:
        raise ValueError(
            f"Expected {ACTIVITY_DAYS} activity values."
        )

    maximum = max(counts, default=0)

    start_x = 300
    baseline_y = 190
    width = 13
    gap = 6
    max_height = 21

    bars: list[str] = []

    for index, count in enumerate(counts):
        x = start_x + index * (width + gap)

        if count <= 0 or maximum <= 0:
            bars.append(
                f'''      <rect x="{x}"
            y="{baseline_y - 2}"
            width="{width}"
            height="2"
            rx="1"
            fill="#334155"
            opacity="0.52"/>'''
            )
            continue

        ratio = math.sqrt(count / maximum)
        height = max(
            5,
            min(
                max_height,
                round(5 + ratio * (max_height - 5)),
            ),
        )

        y = baseline_y - height
        opacity = 0.38 + ratio * 0.47

        bars.append(
            f'''      <rect x="{x}"
            y="{y}"
            width="{width}"
            height="{height}"
            rx="2.5"
            fill="#38BDF8"
            opacity="{opacity:.2f}"/>'''
        )

    return "\n".join(bars)


def format_number(value: int) -> str:
    return f"{value:,}"


def format_updated(now: datetime) -> str:
    return f"{now.strftime('%b')} {now.day}, {now.year}"


def calculate_total_stars(
    repositories: list[dict[str, Any]],
) -> int:
    total = 0

    for repository in repositories:
        stars = repository.get("stargazers_count")

        if isinstance(stars, int):
            total += max(0, stars)

    return total


def build_svg_data(
    *,
    profile: dict[str, Any],
    repositories: list[dict[str, Any]],
    contribution_total: int,
    contribution_days: dict[date, int],
    now: datetime,
) -> dict[str, str]:
    public_repositories = profile.get(
        "public_repos",
        len(repositories),
    )

    if not isinstance(public_repositories, int):
        public_repositories = len(repositories)

    active_days = sum(
        1
        for count in contribution_days.values()
        if count > 0
    )

    stars = calculate_total_stars(repositories)

    avatar_url = profile.get("avatar_url")

    if not isinstance(avatar_url, str) or not avatar_url:
        raise GitHubAPIError(
            "GitHub profile did not contain an avatar URL."
        )

    avatar_data_uri = fetch_avatar_data_uri(avatar_url)

    recent_counts = recent_activity_counts(
        contribution_days,
        today=now.date(),
    )

    activity_bars = render_activity_bars(recent_counts)

    updated = format_updated(now)

    description = (
        f"GitHub activity for {DISPLAY_NAME}: "
        f"{format_number(contribution_total)} contributions this year, "
        f"{format_number(active_days)} active days this year, "
        f"{format_number(public_repositories)} public repositories, "
        f"and {format_number(stars)} total stars. "
        f"Updated {updated}."
    )

    return {
        "display_name": xml_escape(DISPLAY_NAME),
        "description": xml_escape(description),
        "avatar_data_uri": avatar_data_uri,
        "contributions": xml_escape(
            format_number(contribution_total)
        ),
        "active_days": xml_escape(
            format_number(active_days)
        ),
        "repositories": xml_escape(
            format_number(public_repositories)
        ),
        "stars": xml_escape(
            format_number(stars)
        ),
        "activity_bars": activity_bars,
        "updated": xml_escape(updated),
    }


def render_svg(data: dict[str, str]) -> str:
    return SVG_TEMPLATE.substitute(data).strip() + "\n"


def write_atomically(content: str) -> None:
    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = OUTPUT_PATH.with_suffix(
        ".svg.tmp"
    )

    try:
        temporary_path.write_text(
            content,
            encoding="utf-8",
        )

        temporary_path.replace(
            OUTPUT_PATH
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    try:
        if not TOKEN:
            raise GitHubAPIError(
                "GITHUB_TOKEN is required. "
                "GitHub GraphQL contribution data cannot be "
                "queried anonymously."
            )

        now = datetime.now(timezone.utc)

        profile = fetch_profile()
        repositories = fetch_repositories()

        contribution_total, raw_days = (
            fetch_contribution_calendar(now)
        )

        contribution_days = (
            contribution_days_for_current_year(
                raw_days,
                today=now.date(),
            )
        )

        svg_data = build_svg_data(
            profile=profile,
            repositories=repositories,
            contribution_total=contribution_total,
            contribution_days=contribution_days,
            now=now,
        )

        svg = render_svg(svg_data)

        write_atomically(svg)

    except GitHubAPIError as error:
        print(
            f"error: {error}",
            file=sys.stderr,
        )
        return 1

    except OSError as error:
        print(
            f"error: could not write {OUTPUT_PATH}: {error}",
            file=sys.stderr,
        )
        return 1

    except Exception as error:
        print(
            f"error: unexpected failure: {error}",
            file=sys.stderr,
        )
        return 1

    print(f"Generated: {OUTPUT_PATH}")
    print(
        "Contributions:",
        svg_data["contributions"],
    )
    print(
        "Active days:",
        svg_data["active_days"],
    )
    print(
        "Repositories:",
        svg_data["repositories"],
    )
    print(
        "Stars:",
        svg_data["stars"],
    )
    print(
        "Updated:",
        svg_data["updated"],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())