"""Archive public GitHub stars, verify the published files, then unstar.

Python 3.10+, standard library only. Credentials stay outside the repository.
Repository documentation is data: this importer never executes project code.
"""
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

LOG = logging.getLogger("star-importer")
FILES = ("catalog.json", "index.html", "catalog.csv", "README.md")
RULES = {
    "Anime, streaming & tracking": ["anime", "anilist", "myanimelist", "seanime", "stremio"],
    "Manga, novels & reading": ["manga", "manhwa", "manhua", "novel", "ebook", "epub", "reading server"],
    "Music, podcasts & media players": ["music", "spotify", "podcast", "audio player", "music player"],
    "Video downloads & media capture": ["video downloader", "yt-dlp", "screen recorder", "video download"],
    "Discord & TeamSpeak": ["discord", "teamspeak", "vencord", "betterdiscord"],
    "Twitch & livestream tools": ["twitch", "livestream"],
    "Steam, game libraries & achievements": ["steam", "achievement", "game launcher", "game library"],
    "PlayStation & emulation": ["playstation", "ps5", "ps4", "emulator", "emulation", "shadps4"],
    "AION 2 & Where Winds Meet": ["aion2", "aion 2", "where winds meet"],
    "Game mods & automation": ["game mod", "game automation", "mod manager"],
    "Windows maintenance & installation": ["windows debloat", "windows installation", "windows update", "windows maintenance"],
    "Desktop, hardware & customization": ["wallpaper", "glazewm", "yasb", "desktop customization", "status bar"],
    "Android apps & launchers": ["android", "android launcher"],
    "Android root, patches & stores": ["magisk", "revanced", "lsposed", "android root", "f-droid"],
    "Browsers & web extensions": ["browser extension", "webextension", "chrome extension", "firefox addon", "browser"],
    "Privacy, DNS & security": ["privacy", "dns", "adblock", "password manager", "encryption"],
    "Messaging & file sharing": ["messenger", "file sharing", "file transfer", "messaging"],
    "Networking, virtualization & remote access": ["vpn", "remote desktop", "virtualization", "networking", "wireguard"],
    "Self-hosting, feeds & infrastructure": ["self-hosted", "selfhosted", "rss", "homelab", "reverse proxy"],
    "Development, AI & security research": ["developer tool", "coding agent", "code editor", "development framework", "llm", "penetration testing"],
    "Creative tools, documents & translation": ["photo editor", "image editor", "translation", "subtitle", "pdf editor", "video editor"],
    "Account tools, activation & verification": ["activation", "account verification"],
    "Curated lists & learning resources": ["awesome list", "curated list", "learning resources"],
    "TV & channel catalogs": ["iptv", "tv channel"],
}


def classify(repo, readme, categories):
    """Prefer explicit metadata evidence; ambiguous matches need human review."""
    description = repo.get("description") or ""
    primary = (repo["name"] + " " + description + " " + " ".join(repo.get("topics", []))).lower()
    secondary = readme[:100000].lower()
    scores = []
    evidence = {}
    for category, phrases in RULES.items():
        if category not in categories:
            continue
        matches = [p for p in phrases if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", primary)]
        score = sum(5 if " " in p else 4 for p in matches)
        score += min(2, sum(bool(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", secondary)) for p in phrases))
        scores.append((score, category))
        evidence[category] = matches
    scores.sort(reverse=True)
    if not scores or scores[0][0] < 4 or (len(scores) > 1 and scores[0][0] - scores[1][0] < 2):
        return "Needs review", "Automatic classification was inconclusive; review this category."
    category = scores[0][1]
    return category, "Automatically categorized from documentation and metadata; matched: " + ", ".join(evidence[category]) + "."


def summarize(repo, category):
    description = " ".join((repo.get("description") or "").split())[:500]
    # Keep the public catalog in English without sending source data to a translator.
    if description and all(ord(c) < 128 for c in description):
        return description
    return "A project related to " + (category.lower() if category != "Needs review" else "tools and software") + "; see its official documentation for details."


def project(repo, readme, categories):
    category, reason = classify(repo, readme, categories)
    text = ((repo.get("description") or "") + " " + " ".join(repo.get("topics", [])) + " " + readme[:100000]).lower()
    platforms = [label for label, pattern in [("Windows", r"\bwindows\b"), ("Linux", r"\blinux\b"), ("macOS", r"\bmacos\b"), ("Android", r"\bandroid\b"), ("Docker", r"\bdocker\b"), ("Self-hosted", r"self.hosted")]
                 if re.search(pattern, text)]
    notes = [reason, "Descriptive import only; no software was installed, executed or security-audited."]
    if repo.get("archived"):
        notes.append("The upstream repository is archived.")
    if not readme:
        notes.append("No README was available; this entry uses repository metadata.")
    return {"number": 0, "name": repo["full_name"], "url": repo["html_url"], "category": category,
            "summary": summarize(repo, category), "purpose": "Read the official project documentation to check its features and requirements.",
            "platforms": platforms, "language": repo.get("language") or "Not specified", "archived": bool(repo.get("archived")),
            "fork": bool(repo.get("fork")), "pushed": repo.get("pushed_at") or "", "stars": repo.get("stargazers_count", 0),
            "license": (repo.get("license") or {}).get("spdx_id") or "Not specified",
            "readmeStatus": "retrieved" if readme else "unavailable", "readmeUrl": repo["html_url"] + "#readme" if readme else "", "notes": notes}


def markdown_text(value):
    return str(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("<", "&lt;").replace(">", "&gt;")


def render(db, template, readme):
    db["total"] = len(db["projects"])
    db["readmes"] = sum(p["readmeStatus"] == "retrieved" for p in db["projects"])
    if len({p["name"].lower() for p in db["projects"]}) != db["total"]:
        raise ValueError("Duplicate project identities")
    categories = list(dict.fromkeys(p["category"] for p in db["projects"]))
    db["categories"] = list(dict.fromkeys(db["categories"] + categories))
    html = template.replace("__CATALOG_DATA__", json.dumps(db, ensure_ascii=True).replace("<", "\\u003c"))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(["Project", "Category", "Summary", "Platforms", "Archived", "Fork", "Last push", "README review", "URL"])
    for p in db["projects"]:
        writer.writerow([p["name"], p["category"], p["summary"], ", ".join(p["platforms"]), p["archived"], p["fork"], p["pushed"], p["readmeStatus"], p["url"]])
    toc, sections = [], []
    for category in db["categories"]:
        rows = [p for p in db["projects"] if p["category"] == category]
        anchor = re.sub(r"[^a-z0-9\s-]", "", category.lower()).replace(" ", "-")
        toc.append(f"- [{category}](#{anchor}) ({len(rows)})")
        sections.append("## " + category + "\n\n" + "\n".join(f'- [{p["name"]}]({p["url"]}) — {markdown_text(p["summary"])}' for p in rows))
    if "<!-- CATALOG:START -->" not in readme or "<!-- CATALOG:END -->" not in readme:
        raise ValueError("README catalog markers missing")
    block = "<!-- CATALOG:START -->\n\n## Contents\n\n" + "\n".join(toc) + "\n\n" + "\n\n".join(sections) + "\n\n<!-- CATALOG:END -->"
    readme = re.sub(r"<!-- CATALOG:START -->[\s\S]*?<!-- CATALOG:END -->", lambda _: block, readme)
    readme = re.sub(r"- \d+ projects organized into \d+ categories\.", f'- {db["total"]} projects organized into {len(db["categories"])} categories.', readme)
    readme = re.sub(r"<!-- STATS:START -->[\s\S]*?<!-- STATS:END -->", f'<!-- STATS:START -->\nCatalog updated: {db["snapshot"]}. {db["readmes"]} entries have available README documentation. Metadata can become outdated.\n<!-- STATS:END -->', readme)
    return {"catalog.json": json.dumps(db, indent=2, ensure_ascii=False) + "\n", "index.html": html, "catalog.csv": stream.getvalue(), "README.md": readme}


def blob_sha(content):
    data = content.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class GitHub:
    def __init__(self, token):
        self.token = token

    def call(self, path, method="GET", data=None, missing=False):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Only GitHub API paths are accepted")
        request = urllib.request.Request("https://api.github.com" + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "User-Agent": "awesome-toolbox-importer", "Content-Type": "application/json", "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            # Never include credentials, raw response bodies, or private metadata in logs.
            raise RuntimeError(f"GitHub API returned HTTP {error.code}; stars retained for any unverified entries") from None

    def content(self, repo, name, ref):
        entry = self.call(f"/repos/{repo}/contents/{name}?ref={ref}")
        if entry.get("encoding") != "base64":
            raise ValueError("Unsupported catalog file encoding")
        return base64.b64decode(entry["content"]).decode("utf-8")

    def publish(self, target, branch, base, files):
        root = f"/repos/{target}"
        tree = []
        for name, content in files.items():
            blob = self.call(root + "/git/blobs", "POST", {"content": content, "encoding": "utf-8"})
            tree.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        parent = self.call(root + "/git/commits/" + base)
        tree = self.call(root + "/git/trees", "POST", {"base_tree": parent["tree"]["sha"], "tree": tree})
        commit = self.call(root + "/git/commits", "POST", {"message": "Import starred projects into the categorized catalog", "tree": tree["sha"], "parents": [base]})
        self.call(root + "/git/refs/heads/" + branch, "PATCH", {"sha": commit["sha"], "force": False})
        return commit["sha"]

    def verify(self, target, branch, expected):
        head = self.call(f"/repos/{target}/git/ref/heads/{branch}")["object"]["sha"]
        commit = self.call(f"/repos/{target}/git/commits/{head}")
        tree = self.call(f'/repos/{target}/git/trees/{commit["tree"]["sha"]}')
        actual = {p["path"]: p["sha"] for p in tree["tree"] if p["type"] == "blob"}
        if any(actual.get(name) != blob_sha(content) for name, content in expected.items()):
            raise RuntimeError("Published file verification failed; stars retained")


def run(api, owner, target, branch="main", limit=25, dry_run=False):
    user = api.call("/user")
    if user["login"].lower() != owner.lower():
        raise ValueError("Authenticated account does not match configured star owner")
    target_info = api.call("/repos/" + target)
    if target_info.get("private"):
        raise ValueError("This importer is intended for a public catalog")
    # Snapshot pagination before changing stars: deletion must not shift unread pages.
    stars = []
    for page in range(1, 101):
        rows = api.call(f"/user/starred?per_page=100&page={page}")
        stars.extend(rows)
        if len(rows) < 100:
            break
    else:
        raise RuntimeError("Star pagination limit reached; no changes made")
    public = [r for r in stars if not r.get("private", True)]
    if len(public) != len(stars):
        LOG.warning("Private repositories skipped and left starred")
    if not public:
        LOG.info("No public stars to import")
        return {"added": 0, "unstarred": 0}
    base = api.call(f"/repos/{target}/git/ref/heads/{branch}")["object"]["sha"]
    originals = {name: api.content(target, name, base) for name in FILES}
    template = api.content(target, "catalog.template.html", base)
    db = json.loads(originals["catalog.json"])
    known = {p["name"].lower(): p for p in db["projects"]}
    selected = public[:limit]
    added = 0
    for repo in selected:
        if repo["full_name"].lower() in known:
            continue
        # Refetch current visibility immediately before importing public metadata.
        repo = api.call("/repos/" + repo["full_name"])
        if repo.get("private", True):
            raise ValueError("Repository visibility changed; stars retained")
        entry = api.call("/repos/" + repo["full_name"] + "/readme", missing=True)
        if entry and entry.get("encoding") != "base64":
            raise ValueError("README could not be retrieved; star retained")
        readme = base64.b64decode(entry["content"]).decode("utf-8", errors="replace") if entry else ""
        p = project(repo, readme, db["categories"])
        p["number"] = max((r["number"] for r in db["projects"]), default=0) + 1
        db["projects"].append(p)
        known[p["name"].lower()] = p
        added += 1
        LOG.info("Prepared %s in %s", p["name"], p["category"])
    if dry_run:
        LOG.info("Dry run: %s new projects; no publication or star changes", added)
        return {"added": added, "unstarred": 0}
    if added:
        db["snapshot"] = dt.date.today().isoformat()
        files = render(db, template, originals["README.md"])
        api.publish(target, branch, base, files)
    else:
        files = originals
    # Exact Git blob hashes for all four files are checked on the remote branch.
    api.verify(target, branch, files)
    embedded = json.loads(re.search(r'<script id="catalog-data" type="application/json">([\s\S]*?)</script>', files["index.html"])[1])
    embedded_names = {p["name"].lower() for p in embedded["projects"]}
    removed = 0
    for repo in selected:
        name = repo["full_name"]
        entry = known[name.lower()]
        if name.lower() not in embedded_names or entry["url"] not in files["README.md"] or entry["url"] not in files["catalog.csv"]:
            raise RuntimeError("Catalog entry missing from a published format; star retained")
        api.call("/user/starred/" + name, "DELETE")
        removed += 1
        LOG.info("Verified publication and removed star: %s", name)
    remaining = []
    for page in range(1, 101):
        rows = api.call(f"/user/starred?per_page=100&page={page}")
        remaining.extend(r["full_name"].lower() for r in rows)
        if len(rows) < 100:
            break
    if any(r["full_name"].lower() in remaining for r in selected):
        raise RuntimeError("Some star removals did not persist; retry next run")
    result = {"added": added, "unstarred": removed, "remaining": len(remaining)}
    LOG.info("Completed: %s", json.dumps(result))
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = json.loads(args.config.read_text())
    token = Path(config["token_file"]).read_text().strip()
    return run(GitHub(token), config["owner"], config["repository"], config.get("branch", "main"), config.get("batch_size", 25), args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        LOG.error("Import failed: %s", error)
        raise SystemExit(1)
