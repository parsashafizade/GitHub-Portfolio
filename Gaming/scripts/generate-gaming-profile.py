#!/usr/bin/env python3

"""
NEXUS ENGINEERING COMMAND OS
Gaming Profile SVG Generator

Generates:
- hero.svg
- player-card.svg
- project-select.svg
- contribution-map.svg

using GitHub API data.
"""

from pathlib import Path
from datetime import datetime
import os
import requests
import re


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets"

USERNAME = os.getenv("GITHUB_USERNAME", "parsashafizade")

TOKEN = (
    os.getenv("PROFILE_REPOS_TOKEN")
    or os.getenv("GITHUB_TOKEN")
)


HEADERS = {
    "Authorization": f"Bearer {TOKEN}"
} if TOKEN else {}


def github_graphql(query, variables=None):
    response = requests.post(
        "https://api.github.com/graphql",
        json={
            "query": query,
            "variables": variables or {}
        },
        headers=HEADERS,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()["data"]


def github_rest(endpoint):
    response = requests.get(
        f"https://api.github.com{endpoint}",
        headers=HEADERS,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


def clean_text(value, limit=70):
    if not value:
        return "Engineering module"

    value = re.sub(r"\s+", " ", value)

    return value[:limit]


def fetch_profile():

    query = """
    query($login:String!){
      user(login:$login){
        name
        login
        followers{
          totalCount
        }
        repositories(first:100){
          totalCount
        }
      }
    }
    """

    return github_graphql(
        query,
        {
            "login": USERNAME
        }
    )["user"]


def fetch_repositories():

    repos = github_rest(
        f"/users/{USERNAME}/repos?per_page=100&sort=pushed"
    )

    result = []

    for repo in repos:

        topics = []

        if repo.get("topics"):
            topics = repo["topics"]


        if "profile-hide" in topics:
            continue


        if repo["archived"]:
            continue


        if repo["fork"]:
            continue


        if repo.get("is_template"):
            continue


        name = repo["name"].lower()

        banned = [
            "test",
            "draft",
            "temp",
            "wip",
            "sandbox",
            "starter"
        ]

        if any(x in name for x in banned):
            continue


        result.append(repo)


    return sorted(
        result,
        key=lambda x: (
            x.get("stargazers_count",0) * 10
            + x.get("forks_count",0)
        ),
        reverse=True
    )[:4]


def fetch_contributions():

    query = """
    query($login:String!){
      user(login:$login){
        contributionsCollection{
          contributionCalendar{
            totalContributions
            weeks{
              contributionDays{
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """

    data = github_graphql(
        query,
        {
            "login": USERNAME
        }
    )

    return data["user"]["contributionsCollection"]["contributionCalendar"]


def build_grid(calendar):

    cells = []

    x = 340
    y = 170

    weeks = calendar["weeks"]

    for week in weeks:

        for day in week["contributionDays"]:

            count = day["contributionCount"]

            if count == 0:
                color = "#101A35"

            elif count < 3:
                color = "#00E5FF"

            elif count < 7:
                color = "#A855F7"

            else:
                color = "#FFE66D"


            cells.append(
                f"""
                <rect
                x="{x}"
                y="{y}"
                width="8"
                height="8"
                rx="2"
                fill="{color}"
                />
                """
            )

            y += 12

            if y > 250:
                y = 170
                x += 12


    return "".join(cells)



def replace_svg(path, values):

    content = path.read_text(
        encoding="utf-8"
    )

    for key,value in values.items():

        content = content.replace(
            "{{" + key + "}}",
            str(value)
        )


    path.write_text(
        content,
        encoding="utf-8"
    )



def main():

    profile = fetch_profile()

    repos = fetch_repositories()

    calendar = fetch_contributions()


    projects = {}

    for index,repo in enumerate(repos,1):

        projects[f"PROJECT_{index:02}_NAME"] = repo["name"]

        projects[f"PROJECT_{index:02}_DESCRIPTION"] = clean_text(
            repo.get("description")
        )

        projects[f"PROJECT_{index:02}_LANGUAGE"] = (
            repo.get("language")
            or "Software"
        )

        projects[f"PROJECT_{index:02}_STATUS"] = (
            "ACTIVE"
        )


    while len(projects) < 16:
        projects[f"PROJECT_{len(projects)//4+1:02}_NAME"] = "CLASSIFIED"


    values = {

        "PLAYER_NAME":
            profile.get("name")
            or USERNAME,

        "USERNAME":
            USERNAME,

        "ROLE":
            "Mobile Application Developer",

        "LEVEL":
            "ENGINEER",

        "RANK":
            "PRODUCT BUILDER",

        "STATUS":
            "ONLINE",

        "XP_PROGRESS":
            calendar["totalContributions"],

        "XP_BAR_WIDTH":
            min(
                180,
                calendar["totalContributions"] // 2
            ),

        "PRIMARY_SPECIALIZATION":
            "Flutter / AI Assisted Development",

        "PLAYER_CLASS":
            "Software Engineer",

        "MISSION_STATUS":
            "ACTIVE",

        "SYSTEM_VERSION":
            "NEXUS-1.0",

        "ENERGY_LEVEL":
            "100",

        "CURRENT_MODULE":
            "GitHub Activity",

        "CONTRIBUTIONS":
            calendar["totalContributions"],

        "ACTIVE_DAYS":
            sum(
                1
                for week in calendar["weeks"]
                for day in week["contributionDays"]
                if day["contributionCount"] > 0
            ),

        "PUBLIC_REPOS":
            profile["repositories"]["totalCount"],

        "STARS":
            sum(
                repo["stargazers_count"]
                for repo in repos
            ),

        "FOLLOWERS":
            profile["followers"]["totalCount"],

        "CURRENT_YEAR":
            datetime.now().year,

        "CONTRIBUTION_GRID":
            build_grid(calendar),

        **projects
    }


    for svg in [
        "hero.svg",
        "player-card.svg",
        "project-select.svg",
        "contribution-map.svg"
    ]:

        replace_svg(
            ASSET_DIR / svg,
            values
        )


if __name__ == "__main__":
    main()