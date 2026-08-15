"""Prove the hand-rolled OAuth 1.0a signing against the published test vector.

ops/announce.py has never successfully posted; its signing was unverified code.
The percent-encoding and HMAC-SHA1 base string are exactly where a silent 401
lives, so they are asserted here against the worked example X publishes in
"Creating a signature" — known keys, known nonce, known timestamp, known
signature. If these pass, the signing math is right and only server-side state
(token permissions, app settings) can still 401.

Run:  python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "announce", os.path.join(ROOT, "ops", "announce.py"))
an = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(an)


class TestPercentEncoding(unittest.TestCase):
    """The exact table from the OAuth spec / X docs."""

    CASES = [
        ("Ladies + Gentlemen", "Ladies%20%2B%20Gentlemen"),
        ("An encoded string!", "An%20encoded%20string%21"),
        ("Dogs, Cats & Mice", "Dogs%2C%20Cats%20%26%20Mice"),
        ("☃", "%E2%98%83"),
        ("-._~", "-._~"),                       # the only safe punctuation
        ("a/b?c=d&e", "a%2Fb%3Fc%3Dd%26e"),     # reserved chars all encode
    ]

    def test_vectors(self):
        for raw, want in self.CASES:
            self.assertEqual(an._q(raw), want)


class TestSignatureVector(unittest.TestCase):
    """X's documented worked example, end to end."""

    CK = "xvz1evFS4wEEPTGEFPHBog"
    CS = "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw"
    TOK = "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb"
    TS = "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"
    URL = "https://api.twitter.com/1.1/statuses/update.json"
    EXTRA = {
        "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
        "include_entities": "true",
    }
    NONCE = "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg"
    STAMP = "1318622958"
    WANT_SIG = "hCtSmYh+iHYCEqBWrE7C7hYmtUk="
    WANT_BASE = (
        "POST&https%3A%2F%2Fapi.twitter.com%2F1.1%2Fstatuses%2Fupdate.json&"
        "include_entities%3Dtrue%26oauth_consumer_key%3Dxvz1evFS4wEEPTGEFPHBog%26"
        "oauth_nonce%3DkYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg%26"
        "oauth_signature_method%3DHMAC-SHA1%26oauth_timestamp%3D1318622958%26"
        "oauth_token%3D370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb%26"
        "oauth_version%3D1.0%26"
        "status%3DHello%2520Ladies%2520%252B%2520Gentlemen%252C%2520a%2520signed%2520OAuth%2520request%2521"
    )

    def creds(self):
        return (self.CK, self.CS, self.TOK, self.TS)

    def test_base_string_matches_documented_example(self):
        base = an._base_string("POST", self.URL, dict(
            an._oauth_params(self.creds(), nonce=self.NONCE, stamp=self.STAMP),
            **self.EXTRA))
        self.assertEqual(base, self.WANT_BASE)

    def test_signature_matches_documented_example(self):
        hdr = an._auth_header("POST", self.URL, self.creds(),
                              extra_params=self.EXTRA,
                              nonce=self.NONCE, stamp=self.STAMP)
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', hdr)
        self.assertTrue(hdr.startswith("OAuth "))

    def test_v2_no_body_base_has_only_oauth_params(self):
        """The JSON body is deliberately excluded for /2/tweets — the base
        string must contain exactly the six oauth_* params and nothing else."""
        base = an._base_string("POST", "https://api.x.com/2/tweets",
                               an._oauth_params(self.creds(),
                                                nonce=self.NONCE, stamp=self.STAMP))
        method, url, params = base.split("&", 2)
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https%3A%2F%2Fapi.x.com%2F2%2Ftweets")
        keys = [p.split("%3D")[0] for p in params.split("%26")]
        self.assertEqual(keys, ["oauth_consumer_key", "oauth_nonce",
                                "oauth_signature_method", "oauth_timestamp",
                                "oauth_token", "oauth_version"])

    def test_query_string_in_url_is_refused(self):
        """Signing silently ignores query params today — better to refuse loudly
        than to sign wrong when someone points this at a parameterized URL."""
        with self.assertRaises(ValueError):
            an._auth_header("POST", "https://api.x.com/2/tweets?foo=1", self.creds())


class TestComposeAndClamp(unittest.TestCase):
    def run_announce(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "ops", "announce.py"),
                               *args], capture_output=True, text=True)

    def test_dry_run_exits_zero_and_does_not_send(self):
        r = self.run_announce("text", "hello world")
        self.assertEqual(r.returncode, 0)
        self.assertIn("dry run", r.stdout)

    def test_overlong_text_refused_with_exit_one(self):
        r = self.run_announce("text", "x" * 281)
        self.assertEqual(r.returncode, 1)
        self.assertIn("too long", r.stderr + r.stdout)

    def test_post_without_creds_fails_closed(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OMNIGAUGE_X_")}
        r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "announce.py"),
                            "text", "hello", "--post"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing", r.stderr)


if __name__ == "__main__":
    unittest.main()
