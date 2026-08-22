"""Prove the hand-rolled OAuth 1.0a signing against the published test vector.

The percent-encoding and HMAC-SHA1 base string are exactly where a silent 401
lives, so they are asserted here against the worked example X publishes in
"Creating a signature" - known keys, known nonce, known timestamp, known
signature. If these pass, the signing math is right and only server-side state
(token permissions, app settings) can still 401.

Verified end-to-end against the live API on 2026-08-16 as @OmniGauge: a post, a
reply chained under it (confirmed server-side by `referenced_tweets` and a
shared `conversation_id`), a media upload with alt text read back at
1079x536 - then all of it deleted. Signing, threading and media are proven
paths, not plausible ones.

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
        """The JSON body is deliberately excluded for /2/tweets - the base
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
        """Signing silently ignores query params today - better to refuse loudly
        than to sign wrong when someone points this at a parameterized URL."""
        with self.assertRaises(ValueError):
            an._auth_header("POST", "https://api.x.com/2/tweets?foo=1", self.creds())


class TestDraft(unittest.TestCase):
    def test_candidates_split_clamp_dedupe(self):
        text = ('First post about the tool.\n---\n"Second, quoted."\n---\n'
                'First post about the tool.\n---\n' + 'x' * 300 + '\n---\n  ')
        got, dropped = an._candidates(text)
        self.assertEqual(got, ["First post about the tool.", "Second, quoted."])
        self.assertEqual(dropped, 1)

    def test_x_len_counts_urls_as_23(self):
        self.assertEqual(an.x_len("https://github.com/omnigauge/omnigauge"), 23)
        self.assertEqual(an.x_len("read this: https://omnigauge.dev now"), 11 + 23 + 4)
        self.assertEqual(an.x_len("no links here"), 13)

    def test_legal_link_post_survives_clamp(self):
        # 270 raw chars of text + a 40-char URL = 310 raw, 293... keep under:
        body = "y" * 250
        post = body + " https://github.com/omnigauge/omnigauge"
        self.assertGreater(len(post), an.LIMIT)          # raw len would refuse it
        self.assertLessEqual(an.x_len(post), an.LIMIT)   # X accepts it
        got, dropped = an._candidates(post)
        self.assertEqual((len(got), dropped), (1, 0))

    def test_endpoint_resolution_order(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("OMNIGAUGE_DRAFT", "AI_GATEWAY", "OPENAI"))}
        # nothing set -> no key
        with SwapEnv(env):
            self.assertIsNone(an._draft_endpoint()[1])
        with SwapEnv(dict(env, AI_GATEWAY_API_KEY="g")):
            base, key, model = an._draft_endpoint()
            self.assertIn("ai-gateway", base); self.assertEqual(key, "g")
        with SwapEnv(dict(env, OPENAI_API_KEY="o")):
            base, key, model = an._draft_endpoint()
            self.assertIn("api.openai.com", base); self.assertEqual(key, "o")
        with SwapEnv(dict(env, AI_GATEWAY_API_KEY="g", OPENAI_API_KEY="o")):
            self.assertEqual(an._draft_endpoint()[1], "o")   # funded direct wins

    def test_draft_without_keys_fails_closed(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("OMNIGAUGE_DRAFT", "AI_GATEWAY", "OPENAI"))}
        r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "announce.py"),
                            "draft", "anything"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)


class SwapEnv:
    def __init__(self, env): self.env = env
    def __enter__(self):
        self.old = dict(os.environ)
        os.environ.clear(); os.environ.update(self.env)
    def __exit__(self, *a):
        os.environ.clear(); os.environ.update(self.old)


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


# ── threads: text, images and alt text all live in the draft file ───────────

def _tmp(tmpdir, name, size=64):
    p = os.path.join(tmpdir, name)
    with open(p, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + b"\0" * size)
    return p


class TestSplitThreadParsesImages(unittest.TestCase):
    """An @image: line belongs to its post and must not survive into the text -
    a path published as body copy is a wrong post, not a cosmetic slip."""

    def test_image_line_is_extracted_not_posted(self):
        posts, media = an.split_thread(
            "first post\n@image: /tmp/a.png | a description\n---\nsecond post")
        self.assertEqual(posts, ["first post", "second post"])
        self.assertEqual(media, [[("/tmp/a.png", "a description")], []])

    def test_alt_is_optional_at_parse_time_and_caught_at_check_time(self):
        posts, media = an.split_thread("p\n@image: /tmp/a.png")
        self.assertEqual(media, [[("/tmp/a.png", "")]])

    def test_tilde_is_expanded(self):
        _, media = an.split_thread("p\n@image: ~/x.png | alt")
        self.assertTrue(media[0][0][0].startswith(os.path.expanduser("~")))

    def test_media_list_is_parallel_to_posts(self):
        posts, media = an.split_thread("a\n---\nb\n---\nc")
        self.assertEqual(len(posts), len(media))


class TestCheckThreadRefusesBadImagesBeforeSending(unittest.TestCase):
    """post() refuses to send a post whose image failed to upload, so an
    unreadable path would abort mid-thread leaving earlier posts published.
    Every image problem therefore has to surface before the first send."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()

    def test_missing_file_is_refused(self):
        p = [["only post"]][0]
        probs = an.check_thread(p, an.PREMIUM_LIMIT,
                                [[(os.path.join(self.d, "nope.png"), "alt")]])
        self.assertTrue(any("nope.png" in x for x in probs), probs)

    def test_more_than_four_images_is_refused(self):
        imgs = [(_tmp(self.d, f"{i}.png"), "alt") for i in range(5)]
        probs = an.check_thread(["p"], an.PREMIUM_LIMIT, [imgs])
        self.assertTrue(any("at most 4" in x for x in probs), probs)

    def test_missing_alt_text_is_refused(self):
        probs = an.check_thread(["p"], an.PREMIUM_LIMIT,
                                [[(_tmp(self.d, "a.png"), "")]])
        self.assertTrue(any("no alt text" in x for x in probs), probs)

    def test_unsupported_type_is_refused(self):
        probs = an.check_thread(["p"], an.PREMIUM_LIMIT,
                                [[(_tmp(self.d, "a.bmp"), "alt")]])
        self.assertTrue(any("unsupported type" in x for x in probs), probs)

    def test_a_clean_thread_has_no_problems(self):
        self.assertEqual(
            an.check_thread(["p"], an.PREMIUM_LIMIT,
                            [[(_tmp(self.d, "a.png"), "alt")]]), [])


class TestPerImageAltText(unittest.TestCase):
    """Four panels sharing one description is three panels with none. post()
    must accept a list of alts positionally matched to the media paths."""

    def _alts_seen(self, alt):
        """Drive post() far enough to see what each upload was asked for, with
        the real credentials swapped out - a test that leaves fake keys in the
        environment breaks whichever test runs next, which is exactly the class
        of silent failure this suite exists to catch."""
        seen = []
        real, sent = an.upload_media, an.post
        an.upload_media = lambda p, c, alt="": (seen.append((p, alt)) or "1")
        try:
            with SwapEnv(dict(os.environ, **{k: "x" for k in an.ENV})):
                an.post("t", media_paths=["/a.png", "/b.png"], alt=alt)
        finally:
            an.upload_media = real
        return seen

    def test_each_image_gets_its_own_alt(self):
        self.assertEqual(self._alts_seen(["A", "B"]),
                         [("/a.png", "A"), ("/b.png", "B")])

    def test_a_single_string_still_applies_to_every_image(self):
        self.assertEqual([a for _, a in self._alts_seen("same")], ["same", "same"])

    def test_too_few_alts_does_not_shift_them_onto_the_wrong_images(self):
        """Positional pairing must pad, never recycle: image 2 getting image 1's
        description is a wrong caption, which is worse than no caption."""
        self.assertEqual(self._alts_seen(["only-one"]),
                         [("/a.png", "only-one"), ("/b.png", "")])
