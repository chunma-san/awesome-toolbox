# Automatic star inbox

The optional importer turns public GitHub stars into catalog entries. It runs on your own server with Python 3.10 or later and the standard library. The website itself needs no credentials.

## Processing rules

1. Check the authenticated account and snapshot all pages of starred repositories.
2. Skip private repositories, leaving their stars untouched.
3. Retrieve current public metadata and available README text. README text is never executed or interpreted as instructions.
4. Match explicit topic and description keywords to existing categories. Ambiguous entries go to **Needs review**. Classification is heuristic and is not a full code analysis.
5. Commit updated JSON, CSV, Markdown and HTML together, without force-pushing.
6. Verify every published file by its Git blob hash on the remote branch. Check that every entry appears in all catalog formats.
7. Remove the corresponding stars and verify the remaining star list.

If publication or verification fails, unverified stars are retained. If removal fails after publication, the next run recognizes existing entries without duplicating them. New stars arriving during a run are picked up on a later run. Re-starring an existing entry acknowledges the saved entry and removes its star again. The importer processes up to 25 public stars per run by default. Missing README files are identified in the entry; transient API errors stop processing and retain stars. Private entries are never exported.

Metadata, descriptions and documentation may be incomplete or misleading. Check **Needs review** for ambiguous classifications. Non-ASCII descriptions receive a short English category-based summary; no external translation or AI service is used. Listed software is not installed or tested.

## Configuration

Store credentials outside this repository, in a private directory with mode `700`; make the token and configuration files mode `600`. Use a GitHub credential authorized to read the user's stars, remove stars, and write only the intended catalog wherever your authentication method supports that restriction. Never commit credentials or pass them as command-line arguments.

Example configuration (replace the sample values):

```json
{
  "owner": "YOUR_GITHUB_LOGIN",
  "repository": "YOUR_GITHUB_LOGIN/awesome-toolbox",
  "branch": "main",
  "token_file": "/absolute/private/path/github-token",
  "batch_size": 25
}
```

Run a preview with `python3 star_importer.py --config /path/to/config.json --dry-run`. Remove `--dry-run` to enable publication and star removal. A dry run does not write to GitHub. For continuous operation, use a systemd user timer every ten minutes with a oneshot service; systemd prevents overlapping starts of the same service. Enable user lingering if it must run while logged out. A typical service uses `UMask=0077`, `NoNewPrivileges=yes`, `PrivateTmp=yes` and `ProtectSystem=strict`.

Revoke or replace the credential if needed; a failed authorization leaves new stars untouched. Inspect service logs for failures. GitHub Pages deployment happens after a commit and may take additional time; remote source verification precedes removal of stars.

## Tests

Run `python3 -m unittest discover -s automation -p 'test_*.py'`. Tests cover publication failure, verification failure, private repositories, ambiguous classification, duplicate imports, and retrying an already published project.
