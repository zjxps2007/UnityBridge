from __future__ import annotations

from email.message import Message
from io import BytesIO
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.request
import urllib.response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity_bridge._cli import updates
from unity_bridge.client import DiscoveryError


class GitHubTransport(urllib.request.HTTPSHandler):
    """Exercise urllib redirects without making network requests."""

    def __init__(self, redirect: str | None = None):
        super().__init__()
        self.redirect = redirect
        self.requests = []

    def https_open(self, request):
        self.requests.append(request)
        headers = Message()
        headers["Content-Type"] = "text/plain"
        code = 200
        if self.redirect and len(self.requests) == 1:
            headers["Location"] = self.redirect
            code = 302
        response = urllib.response.addinfourl(
            BytesIO(b'[project]\nversion = "1.2.3"\n'), headers, request.full_url, code
        )
        response.msg = "Found" if code == 302 else "OK"
        return response


class UpdateAuthenticationTests(unittest.TestCase):
    def read_version(self, transport, repo="https://github.com/owner/repo.git"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), transport)
        with patch.object(updates.urllib.request, "urlopen", side_effect=opener.open):
            return updates._remote_python_version(repo, "v1.2.3")

    def test_authentication_is_explicit_and_optional(self):
        for token in ("", "  test-update-token  "):
            with self.subTest(token_configured=bool(token)), patch.dict(os.environ, {
                "UNITY_BRIDGE_GITHUB_TOKEN": token,
                "GITHUB_TOKEN": "unrelated-ambient-token",
                "GH_TOKEN": "another-ambient-token",
            }):
                transport = GitHubTransport()
                self.assertEqual(self.read_version(transport), "1.2.3")
                self.assertEqual(len(transport.requests), 1)
                request = transport.requests[0]
                self.assertEqual(request.host, "api.github.com")
                self.assertEqual(request.get_header("Authorization"),
                                 "Bearer test-update-token" if token else None)
                self.assertNotIn("token", request.full_url)

    def test_redirects_do_not_receive_the_token(self):
        for target in ("https://api.github.com/renamed/repository",
                       "https://raw.githubusercontent.com/owner/repo/v1.2.3/pyproject.toml"):
            with self.subTest(target=target), patch.dict(os.environ, {
                "UNITY_BRIDGE_GITHUB_TOKEN": "test-update-token",
            }):
                transport = GitHubTransport(redirect=target)
                self.assertEqual(self.read_version(transport), "1.2.3")
                self.assertEqual(len(transport.requests), 2)
                self.assertEqual(transport.requests[0].get_header("Authorization"),
                                 "Bearer test-update-token")
                self.assertIsNone(transport.requests[1].get_header("Authorization"))

    def test_non_github_repository_is_rejected_before_authentication(self):
        with patch.dict(os.environ, {"UNITY_BRIDGE_GITHUB_TOKEN": "test-update-token"}):
            transport = GitHubTransport()
            with self.assertRaises(DiscoveryError):
                self.read_version(transport, "https://example.test/owner/repo.git")
            self.assertEqual(transport.requests, [])

    def test_invalid_header_is_rejected_without_exposing_the_token(self):
        token = "private-test-token\nsecond-line"
        with patch.dict(os.environ, {"UNITY_BRIDGE_GITHUB_TOKEN": token}):
            transport = GitHubTransport()
            with self.assertRaises(DiscoveryError) as caught:
                self.read_version(transport)
            self.assertNotIn("private-test-token", str(caught.exception))
            self.assertEqual(transport.requests, [])
