#!/usr/bin/env python3

"""
NEXUS GAMING PROFILE GENERATOR

Safe REST-only GitHub generator.

Features:
- No GraphQL dependency
- Safe GitHub API fallback
- Text overflow protection
- SVG generation
- GitHub Actions compatible
"""

from pathlib import Path
from datetime import datetime
import os
import re
import requests


ROOT = Path(__file__).resolve().parents[2]

TEMPLATE_DIR = ROOT / "Gaming" / "templates"
OUTPUT_DIR = ROOT / "Gaming" / "assets"

USERNAME = os.getenv(
    "GITHUB_USERNAME",
    "parsashafizade"
)

TOKEN = (
    os.getenv("PROFILE_REPOS_TOKEN")
    or os.getenv("GITHUB_TOKEN")
)


HEADERS = {
    "Accept": "application/vnd.github+json"
}

if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def safe_text(value, limit=32):
    if not value:
        return ""

    value = re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()

    if len(value) <= limit:
        return value

    return value[:limit-3] + "..."


def github_get(url):
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception as e:
        print(
            "GitHub API failed:",
            e
        )
        return None


def fetch_user():

    data = github_get(
        f"https://api.github.com/users/{USERNAME}"
    )

    if not data:
        return {}

    return data


def fetch_repositories():

    data = github_get(
        f"https://api.github.com/users/{USERNAME}/repos?per_page=100&sort=pushed"
    )

    if not data:
        return []

    return data


def select_projects(repos):

    result = []

    blocked = [
        "wip",
        "draft",
        "test",
        "temp",
        "sandbox"
    ]

    for repo in repos:

        name = repo.get(
            "name",
            ""
        ).lower()

        if any(
            x in name
            for x in blocked
        ):
            continue


        if repo.get(
            "fork"
        ):
            continue


        if repo.get(
            "archived"
        ):
            continue


        result.append(repo)


        if len(result) == 4:
            break


    while len(result) < 4:

        result.append(
            {
                "name":"PROJECT SLOT",
                "description":"Engineering project",
                "language":""
            }
        )

    return result


def fetch_contribution():

    return {
        "active_days":"--",
        "contributions":"--",
        "grid":""
    }


def build_values():

    user = fetch_user()

    repos = select_projects(
        fetch_repositories()
    )

    projects = {}

    for i, repo in enumerate(
        repos[:4],
        start=1
    ):

        projects[
            f"PROJECT_{i}_NAME"
        ] = safe_text(
            repo.get(
                "name",
                "PROJECT"
            ),
            22
        )

        projects[
            f"PROJECT_{i}_DESCRIPTION"
        ] = safe_text(
            repo.get(
                "description",
                ""
            ),
            42
        )

        projects[
            f"PROJECT_{i}_LANGUAGE"
        ] = safe_text(
            repo.get(
                "language",
                ""
            ),
            15
        )


    values = {

        "PLAYER_NAME":
            user.get(
                "name"
            )
            or USERNAME,

        "USERNAME":
            USERNAME,

        "ROLE":
            "Mobile Application Developer",

        "STATUS":
            "ONLINE",

        "PLAYER_CLASS":
            "PRODUCT BUILDER",

        "RANK":
            "ENGINEER",

        "LEVEL":
            "01",

        "PRIMARY_SPECIALIZATION":
            "Flutter / AI Assisted Development",

        "XP_PROGRESS":
            "75",

        "XP_BAR_WIDTH":
            "240",

        "CURRENT_MODULE":
            "GitHub Activity",

        "ENERGY_LEVEL":
            "ACTIVE",

        "SYSTEM_VERSION":
            "NEXUS v1.0",

        **projects

    }

    return values


def generate():

    values = build_values()


    files = [
        "hero.svg",
        "player-card.svg",
        "project-select.svg",
        "contribution-map.svg"
    ]


    for file in files:

        source = (
            TEMPLATE_DIR /
            file
        )

        target = (
            OUTPUT_DIR /
            file
        )


        content = source.read_text(
            encoding="utf-8"
        )


        for key,value in values.items():

            content = content.replace(
                "{{"+key+"}}",
                str(value)
            )


        target.write_text(
            content,
            encoding="utf-8"
        )


        print(
            "Generated:",
            target
        )


if __name__ == "__main__":

    generate()
