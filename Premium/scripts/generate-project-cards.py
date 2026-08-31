#!/usr/bin/env python3
"""
Generate the four Premium GitHub Profile README project cards.

Standard-library only.

Authentication
--------------
Preferred:
    PROFILE_REPOS_TOKEN

Fallback:
    GITHUB_TOKEN

A PROFILE_REPOS_TOKEN is required if private repositories should be
considered across the account. GitHub Actions' built-in GITHUB_TOKEN
normally only has access to the repository in which the workflow runs.

Private repository safety
-------------------------
- Public repositories may be considered automatically.
- Private repositories are considered only when they have:
      profile-showcase
- Any repository with:
      profile-hide
  is always excluded.

The script can also update project-card hrefs in Premium/README.md when
the expected linked-image structure is present.
"""

from __future__ import annotations

import base64
import html
import json
import math
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_USER = "parsashafizade"

GRAPHQL_URL = "https://api.github.com/graphql"
REST_ROOT = "https://api.github.com"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "Premium" / "assets" / "projects"
PREMIUM_README = PROJECT_ROOT / "Premium" / "README.md"

PROFILE_SHOWCASE = "profile-showcase"
PROFILE_HIDE = "profile-hide"

README_MIN_CHARS = 120
MAX_REPOSITORIES = 4

UNFINISHED_SIGNALS = {
    "wip",
    "draft",
    "sandbox",
    "temp",
    "temporary",
    "test",
    "starter",
    "boilerplate",
    "practice",
    "tutorial",
}

CONTROL_TOPICS = {
    PROFILE_SHOWCASE,
    PROFILE_HIDE,
}

# Ordered fallback levels.
#
# The first five implement the requested relaxation order. The final
# conservative floor exists only to avoid replacing mature-looking cards
# with empty slots when a repository has strong README/code signals but
# a very short Git history.
@dataclass(frozen=True)
class QualityTier:
    name: str
    min_age_days: int
    min_description_chars: int
    min_language_bytes: int
    min_commits: int


QUALITY_TIERS = (
    QualityTier("strict", 7, 15, 30_000, 5),
    QualityTier("age-relaxed", 3, 15, 30_000, 5),
    QualityTier("description-relaxed", 3, 10, 30_000, 5),
    QualityTier("code-relaxed", 3, 10, 18_000, 5),
    QualityTier("commit-relaxed", 3, 10, 18_000, 3),
    QualityTier("portfolio-floor", 3, 10, 12_000, 2),
)


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def github_token() -> str:
    token = (
        os.getenv("PROFILE_REPOS_TOKEN", "").strip()
        or os.getenv("GITHUB_TOKEN", "").strip()
    )

    if not token:
        raise RuntimeError(
            "No GitHub token found. Set PROFILE_REPOS_TOKEN or GITHUB_TOKEN."
        )

    return token


def api_request(
    url: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "parsashafizade-premium-project-card-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed: {exc.code} {url}\n{error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed: {url}\n{exc}") from exc


GRAPHQL_QUERY = """
query PremiumPortfolioRepos($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: [OWNER]
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        description
        url
        isPrivate
        isFork
        isArchived
        isTemplate
        createdAt
        pushedAt
        stargazerCount

        repositoryTopics(first: 20) {
          nodes {
            topic {
              name
            }
          }
        }

        primaryLanguage {
          name
        }

        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
            }
          }
        }

        defaultBranchRef {
          name
          target {
            ... on Commit {
              history(first: 1) {
                totalCount
              }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_repositories(token: str) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        response = api_request(
            GRAPHQL_URL,
            token,
            method="POST",
            payload={
                "query": GRAPHQL_QUERY,
                "variables": {
                    "login": GITHUB_USER,
                    "cursor": cursor,
                },
            },
        )

        if response.get("errors"):
            raise RuntimeError(
                "GitHub GraphQL returned errors:\n"
                + json.dumps(response["errors"], indent=2)
            )

        user = response.get("data", {}).get("user")
        if not user:
            raise RuntimeError(f"GitHub user {GITHUB_USER!r} was not found.")

        connection = user["repositories"]

        for repo in connection["nodes"]:
            if repo:
                repositories.append(repo)

        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break

        cursor = page_info["endCursor"]

    return repositories


def fetch_readme(token: str, repo_name: str) -> str:
    url = f"{REST_ROOT}/repos/{GITHUB_USER}/{repo_name}/readme"

    try:
        data = api_request(url, token)
    except RuntimeError as exc:
        # A missing README is an expected quality-filter failure.
        if "404" in str(exc):
            return ""
        raise

    encoded = data.get("content", "")
    if not encoded:
        return ""

    try:
        return base64.b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Repository normalization
# ---------------------------------------------------------------------------

def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def repo_topics(repo: dict[str, Any]) -> list[str]:
    topics: list[str] = []

    for node in repo.get("repositoryTopics", {}).get("nodes", []):
        try:
            topic = node["topic"]["name"].strip().lower()
        except (KeyError, TypeError, AttributeError):
            continue

        if topic:
            topics.append(topic)

    return topics


def repo_languages(repo: dict[str, Any]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []

    for edge in repo.get("languages", {}).get("edges", []):
        try:
            name = str(edge["node"]["name"]).strip()
            size = int(edge["size"])
        except (KeyError, TypeError, ValueError):
            continue

        if name and size > 0:
            result.append((name, size))

    return result


def total_language_bytes(repo: dict[str, Any]) -> int:
    return sum(size for _, size in repo_languages(repo))


def commit_count(repo: dict[str, Any]) -> int:
    try:
        return int(
            repo["defaultBranchRef"]["target"]["history"]["totalCount"]
        )
    except (KeyError, TypeError, ValueError):
        return 0


def strip_markdown_noise(markdown: str) -> str:
    text = markdown

    # Remove fenced-code delimiters while retaining surrounding prose.
    text = re.sub(r"```[\w+-]*", " ", text)
    text = text.replace("```", " ")

    # Images contribute no meaningful README prose.
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)

    # Keep link labels but remove destinations.
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)

    # Remove raw URLs and HTML.
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)

    # Strip common Markdown formatting noise.
    text = re.sub(r"[#>*_`~|=]+", " ", text)
    text = re.sub(r"[-]{2,}", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def explicit_showcase(repo: dict[str, Any]) -> bool:
    return PROFILE_SHOWCASE in repo_topics(repo)


def has_unfinished_signal(repo: dict[str, Any]) -> bool:
    if explicit_showcase(repo):
        return False

    name_tokens = set(
        token
        for token in re.split(r"[^a-z0-9]+", repo["name"].lower())
        if token
    )
    topic_tokens = set(repo_topics(repo))

    return bool(
        name_tokens.intersection(UNFINISHED_SIGNALS)
        or topic_tokens.intersection(UNFINISHED_SIGNALS)
    )


def looks_like_placeholder_readme(clean_readme: str) -> bool:
    if not clean_readme:
        return True

    lower = clean_readme.lower()

    obvious_placeholder_phrases = (
        "coming soon",
        "work in progress",
        "under construction",
        "todo add",
        "placeholder repository",
    )

    return (
        len(clean_readme) < 350
        and any(phrase in lower for phrase in obvious_placeholder_phrases)
    )


# ---------------------------------------------------------------------------
# Safety and eligibility
# ---------------------------------------------------------------------------

def passes_hard_safety(repo: dict[str, Any]) -> tuple[bool, str]:
    topics = set(repo_topics(repo))

    if repo.get("isArchived"):
        return False, "archived"

    if repo.get("isFork"):
        return False, "fork"

    if repo.get("isTemplate"):
        return False, "template"

    if PROFILE_HIDE in topics:
        return False, "profile-hide"

    if repo.get("isPrivate") and PROFILE_SHOWCASE not in topics:
        return False, "private-without-profile-showcase"

    if not repo.get("defaultBranchRef"):
        return False, "no-default-branch"

    return True, ""


def eligible_for_tier(
    repo: dict[str, Any],
    tier: QualityTier,
    *,
    now: datetime,
) -> tuple[bool, str]:
    safe, reason = passes_hard_safety(repo)
    if not safe:
        return False, reason

    description = (repo.get("description") or "").strip()
    if len(description) < tier.min_description_chars:
        return False, "description-too-short"

    created_at = parse_date(repo.get("createdAt"))
    age_days = max(0, int((now - created_at).total_seconds() // 86_400))
    if age_days < tier.min_age_days:
        return False, "too-new"

    clean_readme = repo.get("_clean_readme", "")
    if len(clean_readme) < README_MIN_CHARS:
        return False, "readme-too-small"

    if looks_like_placeholder_readme(clean_readme) and not explicit_showcase(repo):
        return False, "placeholder-readme"

    language_bytes = total_language_bytes(repo)
    if language_bytes < tier.min_language_bytes:
        return False, "not-enough-code"

    commits = commit_count(repo)
    if commits < tier.min_commits:
        return False, "not-enough-commits"

    if has_unfinished_signal(repo):
        return False, "unfinished-signal"

    return True, ""


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def maturity_score(repo: dict[str, Any]) -> float:
    description = (repo.get("description") or "").strip()
    readme_length = len(repo.get("_clean_readme", ""))
    languages = total_language_bytes(repo)
    commits = commit_count(repo)
    topics = [
        topic
        for topic in repo_topics(repo)
        if topic not in CONTROL_TOPICS
    ]
    stars = int(repo.get("stargazerCount") or 0)

    score = 0.0

    score += min(len(description), 120) * 0.15
    score += min(readme_length, 4_000) / 120.0
    score += min(math.log10(max(languages, 1)) * 8.0, 48.0)
    score += min(commits, 40) * 1.25
    score += min(len(topics), 8) * 1.5
    score += min(stars, 20) * 0.75

    if explicit_showcase(repo):
        score += 3.0

    return score


def ranking_key(repo: dict[str, Any]) -> tuple[float, float, str]:
    # pushedAt is intentionally the primary ordering signal.
    pushed = parse_date(repo.get("pushedAt")).timestamp()

    return (
        pushed,
        maturity_score(repo),
        repo["name"].lower(),
    )


# README-derived description fallback
#
# GitHub's repository description is useful metadata, but it should not
# disqualify an otherwise mature repository. When the description field
# is empty, use the first meaningful README sentence/line instead.
def description_from_readme(repo_name: str, clean_readme: str) -> str:
    if not clean_readme:
        return ""

    def normalize(value: str) -> str:
        return " ".join(
            value.lower()
            .replace("-", " ")
            .replace("_", " ")
            .replace("#", " ")
            .replace(":", " ")
            .split()
        )

    normalized_repo_name = normalize(repo_name)

    ignored_headings = {
        "about",
        "overview",
        "features",
        "installation",
        "getting started",
        "usage",
        "requirements",
        "tech stack",
        "technology",
        "technologies",
        "screenshots",
        "demo",
        "license",
        "contributing",
    }

    for raw_line in clean_readme.splitlines():
        line = raw_line.strip(" \t#*-–—|>`")

        if len(line) < 25:
            continue

        normalized_line = normalize(line)

        if not normalized_line:
            continue

        if normalized_line == normalized_repo_name:
            continue

        if normalized_line in ignored_headings:
            continue

        lower_line = line.lower()

        if lower_line.startswith("http://") or lower_line.startswith("https://"):
            continue

        if len(line) > 180:
            line = line[:177].rstrip() + "..."

        return line

    # Some README cleaners collapse prose into one block.
    compact = " ".join(clean_readme.split()).strip()

    if len(compact) < 25:
        return ""

    if normalize(compact).startswith(normalized_repo_name):
        words = compact.split()

        if words and normalize(words[0]) == normalized_repo_name:
            compact = " ".join(words[1:]).strip(" :-–—")

    if len(compact) > 180:
        compact = compact[:177].rstrip() + "..."

    return compact


def enrich_repositories(
    token: str,
    repositories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []

    for repo in repositories:
        safe, safety_reason = passes_hard_safety(repo)
        if not safe:
            print(
                f"  - {repo.get('name', 'unknown')}: "
                f"REJECTED [hard:{safety_reason}]"
            )
            continue

        readme = fetch_readme(token, repo["name"])

        cloned = dict(repo)
        cloned["_readme"] = readme

        clean_readme = strip_markdown_noise(readme)
        cloned["_clean_readme"] = clean_readme

        # A missing GitHub description alone should not hide a mature repo.
        # Use real README prose as the display/quality description fallback.
        if not (cloned.get("description") or "").strip():
            fallback_description = description_from_readme(
                cloned["name"],
                clean_readme,
            )

            if fallback_description:
                cloned["description"] = fallback_description
                cloned["_description_source"] = "readme"
            else:
                cloned["_description_source"] = "missing"
        else:
            cloned["_description_source"] = "github"

        enriched.append(cloned)

    return enriched


def select_repositories(
    repositories: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], QualityTier]:
    now = datetime.now(timezone.utc)

    # DEBUG: repository diagnostics
    print("\nRepository quality diagnostics:")
    print("-" * 100)

    diagnostic_repositories = sorted(
        repositories,
        key=lambda item: parse_date(item.get("pushedAt")),
        reverse=True,
    )

    for repo in diagnostic_repositories:
        repo_name = repo.get("name", "unknown")
        description_length = len((repo.get("description") or "").strip())
        readme_length = len(repo.get("_clean_readme", ""))
        language_bytes = total_language_bytes(repo)
        commits = commit_count(repo)

        created_at = parse_date(repo.get("createdAt"))
        age_days = max(
            0,
            int((now - created_at).total_seconds() // 86_400),
        )

        qualified_tier = None
        final_reason = ""

        for diagnostic_tier in QUALITY_TIERS:
            passed, reason = eligible_for_tier(
                repo,
                diagnostic_tier,
                now=now,
            )

            if passed:
                qualified_tier = diagnostic_tier.name
                break

            final_reason = reason

        pushed_at = repo.get("pushedAt") or "unknown"

        if qualified_tier:
            print(
                f"{repo_name}: QUALIFIED [{qualified_tier}] | "
                f"age={age_days}d | "
                f"description={description_length} chars | "
                f"readme={readme_length} chars | "
                f"language_bytes={language_bytes} | "
                f"commits={commits} | "
                f"pushed={pushed_at}"
            )
        else:
            print(
                f"{repo_name}: REJECTED [{final_reason}] | "
                f"age={age_days}d | "
                f"description={description_length} chars | "
                f"readme={readme_length} chars | "
                f"language_bytes={language_bytes} | "
                f"commits={commits} | "
                f"pushed={pushed_at}"
            )

    print("-" * 100)

    final_eligible: list[dict[str, Any]] = []
    final_tier = QUALITY_TIERS[-1]

    for tier in QUALITY_TIERS:
        eligible = [
            repo
            for repo in repositories
            if eligible_for_tier(repo, tier, now=now)[0]
        ]

        eligible.sort(key=ranking_key, reverse=True)

        final_eligible = eligible
        final_tier = tier

        if len(eligible) >= MAX_REPOSITORIES:
            break

    return final_eligible[:MAX_REPOSITORIES], final_tier


# ---------------------------------------------------------------------------
# Display normalization
# ---------------------------------------------------------------------------

def shorten(text: str, maximum: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= maximum:
        return text

    return text[: maximum - 1].rstrip(" .,:;-") + "…"


def display_repo_name(name: str) -> str:
    return shorten(name, 34)


def display_description(description: str) -> list[str]:
    clean = shorten(description, 102)

    lines = textwrap.wrap(
        clean,
        width=52,
        break_long_words=False,
        break_on_hyphens=False,
    )

    if not lines:
        return ["Repository description unavailable."]

    if len(lines) > 2:
        lines = lines[:2]
        lines[-1] = shorten(lines[-1], 50)

    return lines


def topic_display_name(topic: str) -> str:
    aliases = {
        "ai": "AI",
        "api": "API",
        "dbms": "DBMS",
        "ui": "UI",
        "ux": "UX",
        "rtl": "RTL",
        "aspnet": "ASP.NET",
        "asp-net-core": "ASP.NET Core",
        "postgresql": "PostgreSQL",
        "typescript": "TypeScript",
        "javascript": "JavaScript",
    }

    if topic.lower() in aliases:
        return aliases[topic.lower()]

    return topic.replace("-", " ").replace("_", " ").title()


def choose_tags(repo: dict[str, Any]) -> list[str]:
    result: list[str] = []

    topics = [
        topic
        for topic in repo_topics(repo)
        if topic not in CONTROL_TOPICS
        and topic not in UNFINISHED_SIGNALS
    ]

    # Topics generally communicate product/framework context better than
    # languages, so take a couple first.
    for topic in topics:
        display = topic_display_name(topic)

        if display.lower() not in {x.lower() for x in result}:
            result.append(display)

        if len(result) >= 2:
            break

    for language, _ in repo_languages(repo):
        if language.lower() not in {x.lower() for x in result}:
            result.append(language)

        if len(result) >= 4:
            break

    primary = repo.get("primaryLanguage")
    if primary and len(result) < 2:
        name = primary.get("name")
        if name and name.lower() not in {x.lower() for x in result}:
            result.append(name)

    return result[:4]


def formatted_update_date(repo: dict[str, Any]) -> str:
    pushed = parse_date(repo.get("pushedAt"))
    return pushed.strftime("%b %d, %Y").upper()


def category_label(repo: dict[str, Any]) -> str:
    if repo.get("isPrivate"):
        return "APPROVED SHOWCASE · PRIVATE"

    primary = repo.get("primaryLanguage")
    if primary and primary.get("name"):
        return f"RECENT PROJECT · {primary['name'].upper()}"

    return "RECENT PROJECT · REPOSITORY"


def xml(value: str) -> str:
    return html.escape(value, quote=True)


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------

VARIANTS = (
    {
        "accent": "#22D3EE",
        "accent2": "#38BDF8",
        "support": "#3B82F6",
    },
    {
        "accent": "#38BDF8",
        "accent2": "#22D3EE",
        "support": "#60A5FA",
    },
    {
        "accent": "#22D3EE",
        "accent2": "#60A5FA",
        "support": "#6366F1",
    },
    {
        "accent": "#60A5FA",
        "accent2": "#38BDF8",
        "support": "#818CF8",
    },
)


def render_visual(index: int, accent: str, accent2: str) -> str:
    if index == 0:
        return f"""
        <rect x="0" y="0" width="92" height="67" rx="11" fill="#0B1626" stroke="#334155"/>
        <rect x="11" y="11" width="31" height="45" rx="7" fill="#111C2D" stroke="{accent}" stroke-opacity=".40"/>
        <rect x="15" y="16" width="23" height="31" rx="4" fill="#0F172A"/>
        <circle cx="26.5" cy="27" r="4.8" fill="{accent}" fill-opacity=".18"/>
        <circle cx="24.8" cy="26" r="1.4" fill="{accent2}" class="pulse"/>
        <circle cx="29.2" cy="26" r="1.4" fill="{accent2}" class="pulse"/>
        <path class="flow" d="M43 26H56C62 26 65 31 65 36V44C65 48 69 51 74 51H82" stroke="{accent2}" stroke-opacity=".56" stroke-width="1.2"/>
        <circle cx="59" cy="26" r="2.5" fill="{accent}" class="pulse"/>
        <circle cx="80" cy="51" r="2.5" fill="{accent2}" class="pulse"/>
        """

    if index == 1:
        return f"""
        <rect x="0" y="0" width="92" height="67" rx="11" fill="#0B1626" stroke="#334155"/>
        <rect x="10" y="10" width="30" height="20" rx="4" fill="#142239" stroke="{accent}" stroke-opacity=".40"/>
        <rect x="47" y="10" width="34" height="20" rx="4" fill="#142239" stroke="#334155"/>
        <rect x="10" y="37" width="30" height="20" rx="4" fill="#142239" stroke="#334155"/>
        <rect x="47" y="37" width="34" height="20" rx="4" fill="#142239" stroke="{accent2}" stroke-opacity=".34"/>
        <path d="M16 24L22 18L28 22L34 16" stroke="{accent}" stroke-opacity=".72" stroke-width="1.1"/>
        <path d="M53 51L59 44L65 48L74 42" stroke="{accent2}" stroke-opacity=".62" stroke-width="1.1"/>
        <rect class="scan" x="14" y="12" width="13" height="4" rx="2" fill="{accent}" fill-opacity=".40"/>
        """

    if index == 2:
        return f"""
        <rect x="0" y="0" width="92" height="67" rx="11" fill="#0B1626" stroke="#334155"/>
        <rect x="11" y="10" width="29" height="12" rx="4" fill="#142239" stroke="{accent}" stroke-opacity=".38"/>
        <rect x="11" y="28" width="29" height="12" rx="4" fill="#142239" stroke="#334155"/>
        <rect x="11" y="46" width="29" height="12" rx="4" fill="#142239" stroke="#334155"/>
        <circle cx="18" cy="16" r="1.8" fill="{accent}" class="pulse"/>
        <circle cx="18" cy="34" r="1.8" fill="{accent2}" class="pulse"/>
        <circle cx="18" cy="52" r="1.8" fill="{accent}" class="pulse"/>
        <path class="flow" d="M41 16H53C60 16 63 21 63 27V43C63 49 67 52 73 52H82" stroke="{accent2}" stroke-opacity=".55" stroke-width="1.2"/>
        <rect x="68" y="14" width="13" height="27" rx="4" fill="#111C2D" stroke="{accent2}" stroke-opacity=".32"/>
        <path d="M71 21H78M71 26H78M71 31H76" stroke="#94A3B8" stroke-opacity=".60"/>
        """

    return f"""
        <rect x="0" y="0" width="92" height="67" rx="11" fill="#0B1626" stroke="#334155"/>
        <ellipse cx="25" cy="17" rx="12" ry="5" fill="#142239" stroke="{accent}" stroke-opacity=".45"/>
        <path d="M13 17V43C13 46 18 49 25 49C32 49 37 46 37 43V17" stroke="{accent}" stroke-opacity=".44"/>
        <path d="M13 29C13 32 18 35 25 35C32 35 37 32 37 29" stroke="{accent}" stroke-opacity=".34"/>
        <rect x="58" y="13" width="23" height="10" rx="3" fill="#152238" stroke="{accent2}" stroke-opacity=".36"/>
        <rect x="58" y="31" width="23" height="10" rx="3" fill="#152238" stroke="#334155"/>
        <rect x="58" y="49" width="23" height="8" rx="3" fill="#152238" stroke="#334155"/>
        <path class="flow" d="M38 24H50C55 24 57 20 57 18M38 35H57M38 44H50C55 44 57 49 57 53" stroke="{accent2}" stroke-opacity=".50" stroke-width="1.1"/>
        """


def render_tags(tags: list[str]) -> str:
    if not tags:
        return ""

    x = 20.0
    parts: list[str] = []

    for tag in tags[:4]:
        visible = shorten(tag, 15)
        width = max(36.0, min(82.0, 18.0 + len(visible) * 5.7))

        if x + width > 280:
            break

        parts.append(
            f"""
            <rect x="{x:.1f}" y="114" width="{width:.1f}" height="20" rx="7"
                  fill="#101C2E" stroke="#334155"/>
            <text x="{x + 10:.1f}" y="127" fill="#BAE6FD"
                  font-size="7.5" font-weight="700">{xml(visible)}</text>
            """
        )

        x += width + 6.0

    return "\n".join(parts)


def render_card(repo: dict[str, Any], index: int) -> str:
    variant = VARIANTS[index % len(VARIANTS)]
    accent = variant["accent"]
    accent2 = variant["accent2"]

    name = display_repo_name(repo["name"])
    description_lines = display_description(repo.get("description") or "")
    tags = choose_tags(repo)
    updated = formatted_update_date(repo)
    category = shorten(category_label(repo), 35)

    second_line = description_lines[1] if len(description_lines) > 1 else ""

    visual = render_visual(index, accent, accent2)
    tag_markup = render_tags(tags)

    private_label = (
        '<text x="390" y="26.5" text-anchor="end" fill="#818CF8" '
        'font-size="7.2" font-weight="700">SHOWCASE</text>'
        if repo.get("isPrivate")
        else ""
    )

    return f"""<svg width="430" height="180" viewBox="0 0 430 180" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{xml(repo["name"])}</title>
  <desc id="desc">{xml(repo.get("description") or repo["name"])}</desc>

  <defs>
    <linearGradient id="bg" x1="12" y1="7" x2="418" y2="176">
      <stop stop-color="#0B1120"/>
      <stop offset=".56" stop-color="#0D1627"/>
      <stop offset="1" stop-color="#0F172A"/>
    </linearGradient>

    <linearGradient id="edge" x1="0" y1="0" x2="430" y2="180">
      <stop stop-color="{accent}" stop-opacity=".40"/>
      <stop offset=".55" stop-color="#334155" stop-opacity=".58"/>
      <stop offset="1" stop-color="{accent2}" stop-opacity=".18"/>
    </linearGradient>

    <pattern id="grid" width="22" height="22" patternUnits="userSpaceOnUse">
      <path d="M22 0H0V22" stroke="#94A3B8" stroke-opacity=".043"/>
      <circle cx="1" cy="1" r=".65" fill="{accent}" fill-opacity=".045"/>
    </pattern>

    <clipPath id="clip">
      <rect x=".5" y=".5" width="429" height="179" rx="18"/>
    </clipPath>
  </defs>

  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}

    .reveal {{
      opacity: 0;
      transform: translateY(5px);
      animation: reveal .65s cubic-bezier(.2,.8,.2,1) forwards;
    }}

    .d2 {{ animation-delay: .09s; }}
    .d3 {{ animation-delay: .18s; }}

    .pulse {{ animation: pulse 4.1s ease-in-out infinite 1.1s; }}

    .flow {{
      stroke-dasharray: 8 7;
      animation: flow 7s linear infinite;
    }}

    .scan {{
      animation: scan 7.2s ease-in-out infinite 1.3s;
    }}

    @keyframes reveal {{
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    @keyframes pulse {{
      0%,100% {{ opacity: .38; }}
      50% {{ opacity: 1; }}
    }}

    @keyframes flow {{
      to {{ stroke-dashoffset: -60; }}
    }}

    @keyframes scan {{
      0%,22% {{ transform: translateX(0); opacity: 0; }}
      34% {{ opacity: .72; }}
      72% {{ opacity: .24; }}
      82%,100% {{ transform: translateX(46px); opacity: 0; }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .reveal, .pulse, .flow, .scan {{
        animation: none !important;
        opacity: 1 !important;
        transform: none !important;
      }}
    }}
  </style>

  <rect x=".5" y=".5" width="429" height="179" rx="18" fill="url(#bg)"/>

  <g clip-path="url(#clip)">
    <rect width="430" height="180" fill="url(#grid)"/>
    <circle cx="365" cy="78" r="87" fill="{accent}" fill-opacity=".026"/>
  </g>

  <rect x=".5" y=".5" width="429" height="179" rx="18" stroke="url(#edge)"/>

  <g class="sans reveal">
    <circle cx="23" cy="23" r="3.2" fill="{accent}" class="pulse"/>
    <text x="34" y="26.5" fill="#64748B" font-size="8.2"
          font-weight="700" letter-spacing="1.15">{xml(category)}</text>
    {private_label}

    <text x="20" y="56" fill="#F8FAFC" font-size="16.6"
          font-weight="760">{xml(name)}</text>

    <text x="20" y="79" fill="#CBD5E1" font-size="10.7">
      {xml(description_lines[0])}
    </text>

    <text x="20" y="94" fill="#94A3B8" font-size="10.7">
      {xml(second_line)}
    </text>
  </g>

  <!-- Keep positioning transform separate from animated transform.
       CSS transform on .reveal would otherwise override translate(302 38). -->
  <g transform="translate(302 38)">
    <g class="reveal d2">
      {visual}
    </g>
  </g>

  <g class="mono reveal d2">
    {tag_markup}
  </g>

  <line x1="20" y1="147" x2="410" y2="147" stroke="#1E293B"/>

  <g class="mono reveal d3">
    <text x="20" y="165" fill="#64748B" font-size="7.8"
          letter-spacing=".55">UPDATED {xml(updated)}</text>

    <text x="326" y="165" fill="#7DD3FC" font-size="8.3"
          font-weight="700">View Repository ↗</text>
  </g>
</svg>
"""


def render_empty_card(index: int) -> str:
    variant = VARIANTS[index % len(VARIANTS)]
    accent = variant["accent"]

    return f"""<svg width="430" height="180" viewBox="0 0 430 180" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Protected showcase slot</title>
  <desc id="desc">No repository currently passes the portfolio quality and safety gates for this showcase slot.</desc>

  <defs>
    <linearGradient id="bg" x1="12" y1="7" x2="418" y2="176">
      <stop stop-color="#0B1120"/>
      <stop offset="1" stop-color="#0F172A"/>
    </linearGradient>

    <pattern id="grid" width="22" height="22" patternUnits="userSpaceOnUse">
      <path d="M22 0H0V22" stroke="#94A3B8" stroke-opacity=".04"/>
    </pattern>
  </defs>

  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .pulse {{ animation: pulse 4.8s ease-in-out infinite; }}

    @keyframes pulse {{
      0%,100% {{ opacity: .28; }}
      50% {{ opacity: .7; }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .pulse {{ animation: none !important; opacity: .6 !important; }}
    }}
  </style>

  <rect x=".5" y=".5" width="429" height="179" rx="18" fill="url(#bg)" stroke="#334155"/>
  <rect x="1" y="1" width="428" height="178" rx="17" fill="url(#grid)"/>

  <circle cx="23" cy="23" r="3.2" fill="{accent}" class="pulse"/>

  <text class="mono" x="34" y="26.5" fill="#64748B" font-size="8.2"
        font-weight="700" letter-spacing="1.2">PORTFOLIO QUALITY GATE</text>

  <text class="sans" x="20" y="63" fill="#E2E8F0" font-size="17"
        font-weight="740">Showcase slot protected</text>

  <text class="sans" x="20" y="87" fill="#94A3B8" font-size="10.7">
    No additional repository currently passes the
  </text>

  <text class="sans" x="20" y="102" fill="#64748B" font-size="10.7">
    maturity and public-showcase safety requirements.
  </text>

  <line x1="20" y1="147" x2="410" y2="147" stroke="#1E293B"/>

  <text class="mono" x="20" y="165" fill="#475569" font-size="7.8">
    WAITING FOR A QUALIFIED REPOSITORY
  </text>
</svg>
"""


# ---------------------------------------------------------------------------
# README link synchronization
# ---------------------------------------------------------------------------

def sync_readme_links(selected: list[dict[str, Any]]) -> bool:
    if not PREMIUM_README.exists():
        return False

    content = PREMIUM_README.read_text(encoding="utf-8")
    original = content

    for index in range(MAX_REPOSITORIES):
        slot = index + 1

        if index < len(selected):
            destination = selected[index]["url"]
        else:
            destination = f"https://github.com/{GITHUB_USER}?tab=repositories"

        asset = rf"\./assets/projects/project-{slot:02d}\.svg"

        pattern = re.compile(
            rf'(<a\s+href=")[^"]*'
            rf'(">\s*<img\b[^>]*\bsrc="{asset}")',
            flags=re.IGNORECASE | re.DOTALL,
        )

        content = pattern.sub(
            lambda match: match.group(1) + destination + match.group(2),
            content,
            count=1,
        )

    if content == original:
        return False

    PREMIUM_README.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    token = github_token()

    print(f"Fetching repositories for {GITHUB_USER}...")
    repositories = fetch_repositories(token)

    print(f"Found {len(repositories)} owned repositories accessible to the token.")

    enriched = enrich_repositories(token, repositories)
    selected, tier = select_repositories(enriched)

    print(f"Selection tier: {tier.name}")
    print(f"Qualified repositories: {len(selected)}")

    for repo in selected:
        visibility = "private showcase" if repo.get("isPrivate") else "public"
        print(
            f"  - {repo['name']} "
            f"[{visibility}; commits={commit_count(repo)}; "
            f"language_bytes={total_language_bytes(repo)}]"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for index in range(MAX_REPOSITORIES):
        output_path = OUTPUT_DIR / f"project-{index + 1:02d}.svg"

        if index < len(selected):
            svg = render_card(selected[index], index)
        else:
            svg = render_empty_card(index)

        output_path.write_text(svg, encoding="utf-8")
        print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")

    if sync_readme_links(selected):
        print("Updated Premium/README.md project links.")
    else:
        print("Premium/README.md links unchanged or README not present.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)