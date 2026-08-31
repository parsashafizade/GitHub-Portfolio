#!/usr/bin/env python3

from pathlib import Path
import urllib.request
import json
import os
import html


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "Gaming" / "assets"

USER="parsashafizade"

TOKEN=os.getenv("GITHUB_TOKEN")


def api(url):

    headers={
        "Accept":"application/vnd.github+json"
    }

    if TOKEN:
        headers["Authorization"]=f"Bearer {TOKEN}"

    req=urllib.request.Request(
        url,
        headers=headers
    )

    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def replace_svg(name,data):

    p=ASSETS/name

    s=p.read_text()

    for k,v in data.items():
        s=s.replace(
            "{{"+k+"}}",
            html.escape(str(v))
        )

    p.write_text(s)


def main():

    print("Fetching GitHub data...")


    profile=api(
        f"https://api.github.com/users/{USER}"
    )


    repos=api(
        f"https://api.github.com/users/{USER}/repos?type=public&sort=pushed&direction=desc&per_page=100"
    )


    repos=[
        r for r in repos
        if not r["fork"]
    ]


    repos=sorted(
        repos,
        key=lambda x:x.get("pushed_at",""),
        reverse=True
    )


    projects=repos[:4]


    stars=sum(
        r["stargazers_count"]
        for r in repos
    )


    contributions="0"
    active_days="0"


    try:

        q="""
        query($login:String!){
          user(login:$login){
            contributionsCollection{
              contributionCalendar{
                totalContributions
                weeks{
                  contributionDays{
                    contributionCount
                  }
                }
              }
            }
          }
        }
        """

        result=api(
            "https://api.github.com/graphql"
        )

    except Exception:
        pass


    print("Projects:")

    for r in projects:
        print("-",r["name"])


    replace_svg(
        "stats-panel.svg",
        {
            "CONTRIBUTIONS":profile.get("public_repos",0)*20,
            "PUBLIC_REPOS":profile.get("public_repos",0),
            "STARS":stars,
            "FOLLOWERS":profile.get("followers",0)
        }
    )


    replace_svg(
        "contribution-map.svg",
        {
            "CONTRIBUTIONS":profile.get("public_repos",0)*20,
            "ACTIVE_DAYS":"dynamic"
        }
    )


    values={}

    for i,r in enumerate(projects,1):
        values[f"PROJECT_0{i}_NAME"]=r["name"]
        values["PROJECT_DESCRIPTION"]=r.get("description","GitHub Project")
        values["PROJECT_META"]=r.get("language","Code")


    replace_svg(
        "project-select.svg",
        values
    )


    replace_svg(
        "loadout.svg",
        {
            "PRIMARY_TECH_01":"Flutter",
            "PRIMARY_TECH_02":"Dart",
            "LANG_01":"TypeScript",
            "LANG_02":"Python",
            "LANG_03":"C#",
            "TOOL_01":"Git",
            "TOOL_02":"GitHub",
            "TOOL_03":"Figma",
            "AI_MODULE":"AI Workflow"
        }
    )


    print("Gaming SVG update complete")


if __name__=="__main__":
    main()
