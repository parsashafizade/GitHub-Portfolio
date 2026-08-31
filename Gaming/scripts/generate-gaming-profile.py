#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime, timezone, date
import urllib.request
import json
import os
import html


ROOT = Path(__file__).resolve().parents[2]

ASSETS = ROOT / "Gaming" / "assets"

USERNAME = "parsashafizade"

TOKEN = os.getenv("GITHUB_TOKEN")


def request(url, payload=None):

    headers = {
        "Accept": "application/vnd.github+json"
    }

    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    if payload:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url,
        headers=headers,
        data=json.dumps(payload).encode()
        if payload else None
    )

    with urllib.request.urlopen(req) as r:
        return json.loads(
            r.read()
        )


def rest(path):

    return request(
        "https://api.github.com" + path
    )


def graphql(query, variables):

    return request(
        "https://api.github.com/graphql",
        {
            "query": query,
            "variables": variables
        }
    )


def escape(value):

    return html.escape(
        str(value)
    )


def replace_svg(file, values):

    path = ASSETS / file

    text = path.read_text(
        encoding="utf-8"
    )

    for key,value in values.items():

        text = text.replace(
            "{{" + key + "}}",
            escape(value)
        )

    path.write_text(
        text,
        encoding="utf-8"
    )


def get_profile():

    return rest(
        f"/users/{USERNAME}"
    )


def get_repositories():

    repos = rest(
        f"/users/{USERNAME}/repos?type=public&sort=pushed&direction=desc&per_page=100"
    )

    return [
        r for r in repos
        if not r["fork"]
    ]


def repo_quality(repo):

    score = 0


    if repo.get("description"):
        score += 20


    if repo.get("size",0) > 1000:
        score += 20


    if repo.get("stargazers_count",0):
        score += 10


    pushed = datetime.fromisoformat(
        repo["pushed_at"].replace(
            "Z",
            "+00:00"
        )
    )


    age = (
        datetime.now(timezone.utc)
        -
        datetime.fromisoformat(
            repo["created_at"].replace(
                "Z",
                "+00:00"
            )
        )
    ).days


    if age >= 7:
        score += 20


    if repo.get("language"):
        score += 20


    return score


def select_projects(repos):

    blocked = [
        "test",
        "demo",
        "temp",
        "draft",
        "practice"
    ]

    clean=[]

    for repo in repos:

        name = repo["name"].lower()

        if any(
            x in name
            for x in blocked
        ):
            continue


        if repo["size"] < 50:
            continue


        clean.append(repo)


    clean.sort(
        key=repo_quality,
        reverse=True
    )


    return clean[:4]


def get_contributions():

    query = """
    query(
      $login:String!,
      $from:DateTime!,
      $to:DateTime!
    ){
      user(login:$login){
        contributionsCollection(
          from:$from,
          to:$to
        ){
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


    year_start = datetime(
        datetime.now().year,
        1,
        1,
        tzinfo=timezone.utc
    )


    result = graphql(
        query,
        {
            "login":USERNAME,
            "from":year_start.isoformat(),
            "to":datetime.now(timezone.utc).isoformat()
        }
    )


    calendar = (
        result["data"]
        ["user"]
        ["contributionsCollection"]
        ["contributionCalendar"]
    )


    days = []

    for week in calendar["weeks"]:

        for d in week["contributionDays"]:

            days.append(d)


    active = sum(
        1 for d in days
        if d["contributionCount"] > 0
    )


    return (
        calendar["totalContributions"],
        active
    )


def main():

    print("Fetching Gaming profile data...")


    profile = get_profile()

    repos = get_repositories()

    projects = select_projects(
        repos
    )


    contributions, active = get_contributions()


    stars = sum(
        r["stargazers_count"]
        for r in repos
    )


    print(
        f"Contributions: {contributions}"
    )

    print(
        f"Active days: {active}"
    )


    print(
        "Projects:"
    )

    for p in projects:
        print(
            "-",
            p["name"]
        )


    replace_svg(
        "stats-panel.svg",
        {
            "CONTRIBUTIONS": contributions,
            "PUBLIC_REPOS": profile["public_repos"],
            "STARS": stars,
            "FOLLOWERS": profile["followers"]
        }
    )


    replace_svg(
        "contribution-map.svg",
        {
            "CONTRIBUTIONS": contributions,
            "ACTIVE_DAYS": active
        }
    )


    data={}


    for i in range(1,5):

        if i <= len(projects):

            repo=projects[i-1]

            data[
                f"PROJECT_{i:02d}_NAME"
            ] = repo["name"]

            data[
                "PROJECT_DESCRIPTION"
            ] = repo["description"] or ""

            data[
                "PROJECT_META"
            ] = repo["language"] or "CODE"


        else:

            data[
                f"PROJECT_{i:02d}_NAME"
            ]="LOCKED"

            data[
                "PROJECT_DESCRIPTION"
            ]="EMPTY"

            data[
                "PROJECT_META"
            ]=""


    replace_svg(
        "project-select.svg",
        data
    )


    print(
        "Gaming SVG update complete."
    )


if __name__=="__main__":
    main()
