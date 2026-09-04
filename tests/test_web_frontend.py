from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        cls.compact_app = "".join(cls.app.split())
        cls.compact_css = "".join(cls.css.split())
        cls.server = (ROOT / "frontend" / "server.mjs").read_text(encoding="utf-8")
        cls.startup = (ROOT / "start_demo.py").read_text(encoding="utf-8")

    def test_streamlit_frontend_is_removed(self):
        self.assertFalse((ROOT / "app.py").exists())
        self.assertFalse((ROOT / "ui_chrome.py").exists())
        self.assertFalse(list((ROOT / "views").glob("*.py")))
        self.assertNotIn("streamlit", (ROOT / "requirements.txt").read_text(encoding="utf-8").lower())

    def test_browser_never_receives_api_token(self):
        self.assertIn("process.env.DRIVEMATE_API_TOKEN", self.server)
        self.assertIn("authorization: `Bearer ${token}`", self.server)
        self.assertNotIn("DRIVEMATE_API_TOKEN", self.app)

    def test_core_interactions_are_present(self):
        for term in ("Enter", "SpeechRecognition", "speechSynthesis", "pending_tools", "api.confirm", "api.cancel", "api.audit", "state_diff"):
            self.assertIn(term, self.compact_app)

    def test_target_desktop_is_single_screen(self):
        self.assertIn("height:100dvh", self.compact_css)
        self.assertIn("grid-template-columns:30fr45fr25fr", self.compact_css)
        self.assertIn("overflow:hidden", self.compact_css)

    def test_startup_uses_web_frontend_only(self):
        self.assertIn("npm", self.startup)
        self.assertIn("server.mjs", self.startup)
        self.assertNotIn("streamlit", self.startup.lower())


if __name__ == "__main__":
    unittest.main()
