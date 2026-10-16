"""Pure desktop-origin policy tests; real Qt observations are recorded separately."""

import json
import shutil
import subprocess
import unittest

from studio.desktop.app import bootstrap_script, trusted_navigation


class DesktopOriginTests(unittest.TestCase):
    def test_only_exact_launch_origin_is_allowed(self):
        origin = "http://127.0.0.1:8771"
        for url in (origin, origin + "/?project=abc", origin + "/api/projects", origin + "/#help"):
            self.assertTrue(trusted_navigation(url, origin), url)
        for url in (
            "http://127.0.0.1:8770/", "http://localhost:8771/", "https://127.0.0.1:8771/",
            "http://127.0.0.1:8771.evil/", "http://127.0.0.1.evil:8771/", "http://[::1]:8771/",
            "http://user@127.0.0.1:8771/", "http://127.0.0.1:8771@evil.test/",
            "file:///tmp/untrusted.html", "data:text/html,test", "javascript:alert(1)",
            "about:blank", "blob:http://127.0.0.1:8771/id", "/relative", "http://[broken", "http://127.0.0.1:bad/",
        ):
            self.assertFalse(trusted_navigation(url, origin), url)

    @unittest.skipUnless(shutil.which("node"), "Node is required to execute bootstrap JavaScript")
    def test_bootstrap_does_not_publish_secrets_or_channel_to_foreign_documents(self):
        script = bootstrap_script("http://127.0.0.1:8771", "fixture-token-not-a-secret",
                                  "globalThis.channelLibraryLoaded=true; function QWebChannel(t, cb) {cb({objects:{m4ml:{}}});}")
        harness = """
const vm = require('node:vm');
const script = JSON.parse(process.argv[1]);
for (const origin of ['http://127.0.0.1:8771', 'http://127.0.0.1:8770', 'null', 'https://example.test']) {
 const window = {location:{origin}};
 const ctx = vm.createContext({window, qt:{webChannelTransport:{}}});
 vm.runInContext(script, ctx);
 const trusted = origin === 'http://127.0.0.1:8771';
 if (!!window.__M4ML_TOKEN__ !== trusted || !!window.m4mlReady !== trusted || !!ctx.channelLibraryLoaded !== trusted) process.exit(1);
}
"""
        subprocess.run([shutil.which("node"), "-e", harness, json.dumps(script)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
