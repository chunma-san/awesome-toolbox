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
from taxonomy import RULES, CATEGORIES


def classify(repo, readme, categories):
    """Use specific project families first, then weighted public metadata."""
    full_name = repo["full_name"].lower()
    name = repo["name"].lower()
    if full_name.split('/')[0] == name and "GitHub profiles & README tools" in categories and ("profile" in (repo.get("description") or "").lower() or "readme-profile" in repo.get("topics", [])):
        return "GitHub profiles & README tools", "Repository name matches its owner: a GitHub profile README repository."
    if full_name.startswith("grapheneos/"):
        if name in {"appstore", "camera", "pdfviewer", "vanadium", "auditor", "gmscompat", "info"}:
            category = "GrapheneOS apps & browsers"
        elif ".grapheneos.org" in name or name == "grapheneos.org":
            category = "GrapheneOS infrastructure & services"
        else:
            category = "GrapheneOS & Android operating systems"
        if category in categories:
            return category, "Categorized by the official GrapheneOS repository family and component."
    curated = "Curated lists & learning resources"
    if curated in categories and (name.startswith("awesome-") or "awesome-list" in repo.get("topics", [])):
        return curated, "Categorized as a curated collection from its name or awesome-list topic."
    normalize = lambda value: re.sub(r"[-_./]+", " ", value.lower())
    primary = normalize(name + " " + (repo.get("description") or "") + " " + " ".join(repo.get("topics", [])))
    if "Android app patching & modding" in categories and any(word in primary for word in ["revanced", "revancify", "enhancify", "morphe"]):
        return "Android app patching & modding", "Categorized from its Android app patching project family."
    secondary = normalize(readme[:100000])
    scores, evidence = [], {}
    for category, phrases in RULES.items():
        if category not in categories or not phrases:
            continue
        matches = [phrase for phrase in phrases if re.search(r"(?<!\w)" + re.escape(normalize(phrase)) + r"(?!\w)", primary)]
        score = sum(4 + min(4, len(phrase.split()) - 1) for phrase in matches)
        score += min(2, sum(bool(re.search(r"(?<!\w)" + re.escape(normalize(phrase)) + r"(?!\w)", secondary)) for phrase in phrases))
        scores.append((score, category)); evidence[category] = matches
    scores.sort(reverse=True)
    if not scores or scores[0][0] < 4:
        return "Other software & utilities", "No specific category had enough evidence; stored in general utilities."
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 2:
        leaders = scores[:2]
        specific = [(max((len(p.split()) for p in evidence[c]), default=0), c) for _, c in leaders]
        specific.sort(reverse=True)
        if specific[0][0] > specific[1][0]:
            category = specific[0][1]
            return category, "Categorized from the more specific metadata phrase: " + ", ".join(evidence[category]) + "."
        return "Other software & utilities", "Overlapping signals; stored in general utilities without inventing a specific classification."
    category = scores[0][1]
    return category, "Automatically categorized from public metadata and documentation; matched: " + ", ".join(evidence[category]) + "."


def summarize(repo, category):
    description = " ".join((repo.get("description") or "").split())[:500]
    # Keep the public catalog in English without sending source data to a translator.
    letters = [c for c in description if c.isalpha()]
    if description and letters and sum(c.isascii() for c in letters) / len(letters) >= .85:
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
        if not rows:
            continue
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
            # Log the API's short diagnostic message only, never credentials or raw responses.
            try:
                detail = str(json.loads(error.read()).get("message", ""))[:160]
            except (ValueError, UnicodeError):
                detail = "Request rejected"
            if self.token in detail:
                detail = "Request rejected"
            raise RuntimeError(f"GitHub API {method} {path} returned HTTP {error.code}: {detail}; stars retained for any unverified entries") from None

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
        commit = self.call(root + "/git/commits", "POST", {"message": "Synchronize generated public project data", "tree": tree["sha"], "parents": [base]})
        self.call(root + "/git/refs/heads/" + branch, "PATCH", {"sha": commit["sha"], "force": False})
        return commit["sha"]

    def verify(self, target, branch, expected):
        head = self.call(f"/repos/{target}/git/ref/heads/{branch}")["object"]["sha"]
        commit = self.call(f"/repos/{target}/git/commits/{head}")
        tree = self.call(f'/repos/{target}/git/trees/{commit["tree"]["sha"]}?recursive=1')
        if tree.get("truncated"):
            raise RuntimeError("Remote verification tree is incomplete")
        actual = {p["path"]: p["sha"] for p in tree["tree"] if p["type"] == "blob"}
        if any(actual.get(name) != blob_sha(content) for name, content in expected.items()):
            raise RuntimeError("Published file verification failed; stars retained")


def public_owned_repositories(api, owner):
    repositories = []
    for page in range(1, 101):
        rows = api.call(f"/users/{owner}/repos?type=owner&sort=full_name&per_page=100&page={page}")
        repositories.extend(r for r in rows if not r.get("private", True) and r.get("owner", {}).get("login", "").lower() == owner.lower())
        if len(rows) < 100:
            return repositories
    raise RuntimeError("Owned repository pagination limit reached")


def read_project(api, repo, categories):
    repo = api.call("/repos/" + repo["full_name"])
    if repo.get("private", True):
        raise ValueError("Repository is no longer public; import stopped")
    entry = api.call("/repos/" + repo["full_name"] + "/readme", missing=True)
    if entry and entry.get("encoding") != "base64":
        raise ValueError("README could not be retrieved; star retained")
    readme = base64.b64decode(entry["content"]).decode("utf-8", errors="replace") if entry else ""
    return project(repo, readme, categories)


def run(api, owner, target, branch="main", limit=25, dry_run=False, only_repository=None, sync_owned=False):
    if api.call("/user")["login"].lower() != owner.lower():
        raise ValueError("Authenticated account does not match configured star owner")
    if api.call("/repos/" + target).get("private"):
        raise ValueError("This importer is intended for a public catalog")
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
    if only_repository:
        public = [r for r in public if r["full_name"].lower() == only_repository.lower()]
        sync_owned = False
    owned = public_owned_repositories(api, owner) if sync_owned else []
    if not public and not sync_owned:
        LOG.info("No public stars to import")
        return {"added": 0, "unstarred": 0}
    base = api.call(f"/repos/{target}/git/ref/heads/{branch}")["object"]["sha"]
    originals = {name: api.content(target, name, base) for name in FILES}
    template = api.content(target, "catalog.template.html", base)
    db = json.loads(originals["catalog.json"])
    changed = False
    if sync_owned:
        categories = list(dict.fromkeys(CATEGORIES + [p["category"] for p in db["projects"] if p["category"] != "Needs review"]))
        changed = db["categories"] != categories
        db["categories"] = categories
    known = {p["name"].lower(): p for p in db["projects"]}
    owned_names = {r["full_name"].lower() for r in owned}
    selected = public[:limit]
    added = 0
    for repo in list({r["full_name"].lower(): r for r in owned + selected}.values()):
        name = repo["full_name"].lower()
        if name in known:
            if name in owned_names and not known[name].get("owned"):
                known[name]["owned"] = True; changed = True
            continue
        p = read_project(api, repo, db["categories"])
        p["number"] = max((r["number"] for r in db["projects"]), default=0) + 1
        if name in owned_names:
            p["owned"] = True
        db["projects"].append(p); known[name] = p
        added += 1; changed = True
        LOG.info("Prepared %s in %s", p["name"], p["category"])
    if sync_owned:
        for p in db["projects"]:
            if p["category"] == "Needs review" or (p["name"].lower().startswith("grapheneos/") and not p["category"].startswith("GrapheneOS")):
                fresh = read_project(api, {"full_name": p["name"]}, db["categories"])
                p["category"] = fresh["category"]; p["summary"] = fresh["summary"]; p["notes"] = fresh["notes"]
                changed = True
    if dry_run:
        LOG.info("Dry run: %s additions; no writes or star changes", added)
        return {"added": added, "unstarred": 0}
    if changed:
        db["snapshot"] = dt.datetime.now(dt.timezone.utc).date().isoformat()
        files = render(db, template, originals["README.md"])
        api.publish(target, branch, base, files)
    else:
        files = originals
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
        raise RuntimeError("Some removals did not persist; retry next run")
    result = {"added": added, "unstarred": removed, "remaining": len(remaining)}
    LOG.info("Completed: %s", json.dumps(result))
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="Process only this owner/repository (useful for a controlled test)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = json.loads(args.config.read_text())
    token = Path(config["token_file"]).read_text().strip()
    result = run(GitHub(token), config["owner"], config["repository"], config.get("branch", "main"), config.get("batch_size", 25), args.dry_run, args.only, config.get("sync_owned", False))
    if config.get("profile_repository") and not args.dry_run and not args.only:
        from profile_sync import sync_profile
        sync_profile(GitHub(token), config["owner"], config["profile_repository"], config["repository"])
    return result


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        LOG.error("Import failed: %s", error)
        raise SystemExit(1)
