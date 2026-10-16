"""Generate a GitHub profile dashboard and live public repository directory.

Only public metadata is used. No third-party image service or credentials are
embedded. Pushes to the generated catalog/profile are excluded from activity
metrics to prevent a display-update feedback loop.
"""
import collections
import datetime as dt
import html
import json
import logging
import re
from zoneinfo import ZoneInfo

from star_importer import public_owned_repositories, markdown_text

LOG = logging.getLogger("profile-sync")
PARIS = ZoneInfo("Europe/Paris")


def collect_activity(api, owner, repositories, profile_repo, catalog_repo, today=None):
    today = today or dt.datetime.now(PARIS).date()
    days = [(today - dt.timedelta(days=29 - i)).isoformat() for i in range(30)]
    series = {name: [0] * 30 for name in ["events", "issues_opened", "issues_closed", "prs_opened", "prs_closed", "pushes"]}
    owned_names = {r["full_name"].lower() for r in repositories}
    generated_repos = {profile_repo.lower(), catalog_repo.lower()}
    seen = set()
    fetched = 0
    for page in range(1, 4):
        rows = api.call(f"/users/{owner}/events/public?per_page=100&page={page}")
        fetched += len(rows)
        for event in rows:
            if event.get("public") is not True or event.get("id") in seen:
                continue
            seen.add(event.get("id"))
            name = event.get("repo", {}).get("name", "").lower()
            if name not in owned_names:
                continue
            day = dt.datetime.fromisoformat(event["created_at"].replace("Z", "+00:00")).astimezone(PARIS).date().isoformat()
            if day not in days:
                continue
            kind = event["type"]
            if kind == "PushEvent" and name in generated_repos:
                continue
            index = days.index(day)
            series["events"][index] += 1
            action = event.get("payload", {}).get("action")
            if kind == "PushEvent":
                series["pushes"][index] += 1
            if kind == "IssuesEvent" and action in {"opened", "closed"}:
                series["issues_" + action][index] += 1
            if kind == "PullRequestEvent" and action in {"opened", "closed"}:
                series["prs_" + action][index] += 1
        if len(rows) < 100:
            break
    contributors = collections.Counter()
    for repo in repositories:
        if repo.get("fork") or repo["full_name"].lower() in generated_repos:
            continue
        rows = api.call(f'/repos/{repo["full_name"]}/contributors?per_page=100', missing=True) or []
        for person in rows:
            if person.get("login"):
                contributors[person["login"]] += person.get("contributions", 0)
    return {"date": today.isoformat(), "days": days, "series": series,
            "totals": {name: sum(values) for name, values in series.items()},
            "event_limit_reached": fetched >= 300,
            "contributors": [{"login": name, "commits": count} for name, count in contributors.most_common(3)]}


def dashboard_svg(activity, repo_count):
    esc = lambda value: html.escape(str(value), quote=True)
    totals = activity["totals"]
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="470" viewBox="0 0 960 470" role="img" aria-labelledby="title desc">',
             '<title id="title">Public project activity dashboard</title>',
             '<desc id="desc">Thirty days of public GitHub activity, repository counts, issue and pull request events, pushes, and all-time contributors.</desc>',
             '<style>text{font-family:Segoe UI,Arial,sans-serif}.label{font-size:12px;fill:#9ca3af}.value{font-size:25px;font-weight:700;fill:#f3f4f6}.title{font-size:14px;font-weight:600}.small{font-size:11px;fill:#9ca3af}</style>',
             '<rect width="960" height="470" rx="14" fill="#0d0e12"/>']
    def rect(x, y, w, h, fill="#15161c", stroke="#30313c", radius=8):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>')
    def text(x, y, value, cls="label", fill=None):
        parts.append(f'<text x="{x}" y="{y}" class="{cls}"' + (f' style="fill:{fill}"' if fill else '') + f'>{esc(value)}</text>')
    rect(12, 12, 936, 64)
    text(30, 38, f'{totals["events"]} public events · last 30 days', "title", "#ff5268")
    text(30, 59, f'{repo_count} public repositories · real activity from GitHub')
    values = activity["series"]["events"]; peak = max(max(values), 1)
    for i, value in enumerate(values):
        opacity = .18 + .82 * value / peak
        parts.append(f'<rect x="{550+i*12}" y="34" width="10" height="16" rx="2" fill="#ff5268" opacity="{opacity:.2f}"/>')
    cards = [("Issue events", f'{totals["issues_opened"]} opened / {totals["issues_closed"]} closed', "#55adff"),
             ("Pull request events", f'{totals["prs_opened"]} opened / {totals["prs_closed"]} closed', "#bf83ff"),
             ("Push events", str(totals["pushes"]), "#ff7950")]
    for i, (label, value, color) in enumerate(cards):
        x = 12 + i*316; rect(x, 88, 304, 72)
        text(x+16, 111, label, "title", color)
        text(x+16, 143, value, "value" if i == 2 else "title", "#f3f4f6")
    charts = [("Issues", "issues_opened", "issues_closed", "#55adff"), ("Pull requests", "prs_opened", "prs_closed", "#bf83ff"), ("Pushes", "pushes", None, "#ff7950")]
    for i, (label, key, secondary, color) in enumerate(charts):
        x = 12 + i*316; rect(x, 172, 304, 172)
        text(x+16, 197, label, "title", color)
        if secondary:
            text(x+16, 214, "Opened · Closed events", "small")
        maximum = max(max(activity["series"][key]), max(activity["series"][secondary]) if secondary else 0, 1)
        parts.append(f'<path d="M{x+16},318 H{x+288}" stroke="#30313c"/>')
        for j, value in enumerate(activity["series"][key]):
            height = 82*value/maximum
            parts.append(f'<rect x="{x+17+j*9}" y="{318-height:.1f}" width="{4 if secondary else 7}" height="{height:.1f}" fill="{color}"/>')
            if secondary:
                height = 82*activity["series"][secondary][j]/maximum
                parts.append(f'<rect x="{x+21+j*9}" y="{318-height:.1f}" width="4" height="{height:.1f}" fill="{color}" opacity=".4"/>')
        text(x+16, 334, "30 days ago", "small"); text(x+260, 334, "Today", "small")
    rect(12, 356, 936, 68)
    text(28, 381, "Top contributors", "title", "#ff5268")
    text(28, 402, "Public originals · all time", "small")
    for i, person in enumerate(activity["contributors"]):
        x = 250 + i*230
        parts.append(f'<a href="https://github.com/{esc(person["login"])}">')
        text(x, 381, person["login"][:28], "title", "#d1d5db")
        text(x, 402, f'{person["commits"]} commits', "small"); parts.append('</a>')
    note = "Latest 300 public events; GitHub may delay events. Generated display pushes excluded."
    text(18, 445, note, "small")
    text(18, 461, f'Updated {activity["date"]} · Europe/Paris · no private repository data', "small")
    parts.append('</svg>')
    return "".join(parts)


def profile_readme(readme, repositories, profile_repo, catalog_repo):
    owner = profile_repo.split('/')[0]
    rows = []
    for repo in sorted(repositories, key=lambda r: (bool(r.get("fork")), r["name"].lower())):
        flags = " · Fork" if repo.get("fork") else ""
        if repo.get("archived"):
            flags += " · Archived"
        description = " ".join((repo.get("description") or "Public project repository.").split())[:180]
        rows.append(f'| [{repo["name"]}]({repo["html_url"]}){flags} | {markdown_text(description).replace("|", "&#124;")} | {markdown_text(repo.get("language") or "—")} |')
    block = '\n'.join(['<!-- PUBLIC-PROJECTS:START -->', '## Public activity & projects', '',
        '<p align="center"><img src="assets/project-activity.svg" alt="Public project activity over the last 30 days" width="960" /></p>', '',
        f'**{len(repositories)} public repositories**, synchronized automatically. New public projects appear here and in [Awesome Toolbox](https://github.com/{catalog_repo}).', '',
        '| Project | What it does | Language |', '| --- | --- | --- |', *rows, '',
        'Activity charts use GitHub’s public event timeline (up to 300 events over 30 days). Event delivery can be delayed. Pushes to the generated profile and catalog are excluded to prevent display-update loops. Contributor totals cover public non-fork project repositories and are all-time, not a 30-day count.', '',
        '<!-- PUBLIC-PROJECTS:END -->'])
    if '<!-- PUBLIC-PROJECTS:START -->' in readme:
        return re.sub(r'<!-- PUBLIC-PROJECTS:START -->[\s\S]*?<!-- PUBLIC-PROJECTS:END -->', lambda _: block, readme)
    marker = '## Featured projects'
    if marker in readme:
        return readme.replace(marker, block + '\n\n' + marker, 1)
    return readme.rstrip() + '\n\n' + block + '\n'


def sync_profile(api, owner, profile_repo, catalog_repo, branch="main"):
    if api.call('/repos/' + profile_repo).get('private'):
        raise ValueError('Profile repository must be public')
    repositories = public_owned_repositories(api, owner)
    base = api.call(f'/repos/{profile_repo}/git/ref/heads/{branch}')["object"]["sha"]
    readme = api.content(profile_repo, 'README.md', base)
    activity = collect_activity(api, owner, repositories, profile_repo, catalog_repo)
    directory = [{"name": r["full_name"], "url": r["html_url"], "description": r.get("description") or "", "language": r.get("language"), "fork": bool(r.get("fork")), "archived": bool(r.get("archived"))} for r in repositories]
    files = {'README.md': profile_readme(readme, repositories, profile_repo, catalog_repo),
             'assets/project-activity.svg': dashboard_svg(activity, len(repositories)),
             'assets/public-projects.json': json.dumps({"repositories": directory, "activity": activity}, indent=2, ensure_ascii=False) + '\n'}
    unchanged = files['README.md'] == readme
    for name in ['assets/project-activity.svg', 'assets/public-projects.json']:
        entry = api.call(f'/repos/{profile_repo}/contents/{name}?ref={base}', missing=True)
        if entry is None:
            unchanged = False
        else:
            from star_importer import blob_sha
            unchanged = unchanged and entry['sha'] == blob_sha(files[name])
    if unchanged:
        LOG.info('Profile directory and activity already current')
        return {"repositories": len(repositories), "updated": False}
    api.publish(profile_repo, branch, base, files)
    api.verify(profile_repo, branch, files)
    LOG.info('Profile synchronized: %s public repositories', len(repositories))
    return {"repositories": len(repositories), "updated": True}
