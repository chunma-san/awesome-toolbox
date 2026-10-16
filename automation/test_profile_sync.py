import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from profile_sync import collect_activity, dashboard_svg, profile_readme


class ProfileTests(unittest.TestCase):
    def test_private_and_generated_activity_is_not_counted(self):
        event = {"id": "1", "type": "PushEvent", "public": True,
                 "repo": {"name": "example/app"}, "created_at": "2026-10-16T12:00:00Z", "payload": {}}
        events = [event, dict(event, id="2", public=False),
                  dict(event, id="3", repo={"name": "example/profile"}),
                  dict(event, id="4", repo={"name": "someone/other"})]
        class API:
            def call(self, path, **kwargs):
                if "/events/public?" in path:
                    return events
                return [{"login": "public-author", "contributions": 5}]
        repos = [{"full_name": "example/app", "fork": False}, {"full_name": "example/profile", "fork": False}]
        result = collect_activity(API(), "example", repos, "example/profile", "example/catalog", dt.date(2026, 10, 16))
        self.assertEqual(result["totals"]["pushes"], 1)
        self.assertEqual(result["totals"]["events"], 1)
        self.assertEqual(result["contributors"], [{"login": "public-author", "commits": 5}])

    def test_existing_profile_artwork_is_preserved_without_duplicate_sections(self):
        old = '<img src="assets/portrait.jpg" />\nDiscord profile card\n\n## Featured projects\nKeep this text'
        repos = [{"name": "app", "full_name": "example/app", "html_url": "https://github.com/example/app", "description": "A useful app", "language": "Python"}]
        first = profile_readme(old, repos, "example/profile", "example/catalog")
        second = profile_readme(first, repos, "example/profile", "example/catalog")
        self.assertEqual(first, second)
        self.assertIn('assets/portrait.jpg', second)
        self.assertIn('Discord profile card', second)
        self.assertIn('Keep this text', second)
        self.assertEqual(second.count('<!-- PUBLIC-PROJECTS:START -->'), 1)

    def test_svg_escapes_public_contributor_text(self):
        series = {key: [0] * 30 for key in ["events", "issues_opened", "issues_closed", "prs_opened", "prs_closed", "pushes"]}
        data = {"date": "2026-10-16", "series": series, "totals": {key: 0 for key in series}, "contributors": [{"login": '<unsafe>&"', "commits": 1}]}
        svg = dashboard_svg(data, 1)
        ET.fromstring(svg)
        self.assertNotIn('<unsafe>', svg)
        self.assertIn('GitHub may delay events', svg)


if __name__ == "__main__":
    unittest.main()
