from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.views = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "views").glob("*.py"))
        )
        cls.ui_source = cls.app + "\n" + cls.views
        style_root = ROOT / "assets" / "figma-hmi" / "styles"
        cls.css = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(style_root.glob("*.css"))
        )

    def test_three_columns_are_bounded_to_the_desktop_viewport(self) -> None:
        self.assertIn("height: calc(100dvh - 86px) !important;", self.css)
        self.assertIn("flex: 0 0 calc(100dvh - 86px) !important;", self.css)
        self.assertIn("height: 100% !important;", self.css)
        self.assertIn("overflow-y: auto;", self.css)
        self.assertIn("overflow-y: hidden;", self.css)

    def test_quick_actions_are_two_rows_of_three(self) -> None:
        self.assertIn('quick_columns = st.columns(3, gap="small")', self.ui_source)
        self.assertEqual(self.app.count("OWNER_QUICK_ACTIONS = ["), 1)
        self.assertIn("flex: 0 0 auto;", self.css)

    def test_chat_bubbles_keep_user_right_and_assistant_left(self) -> None:
        self.assertIn('img[alt="user avatar"]', self.css)
        self.assertIn('img[alt="assistant avatar"]', self.css)
        self.assertIn("flex-direction: row-reverse;", self.css)
        self.assertIn("margin-left: auto;", self.css)

    def test_composer_is_last_and_anchored_to_the_bottom(self) -> None:
        bridge = self.ui_source.index("render_voice_bridge(")
        composer = self.ui_source.index('with st.container(key="agent_composer"')
        self.assertLess(bridge, composer)
        self.assertIn("margin-top: auto;", self.css)
        self.assertIn("st.columns([1.05, 1.0]", self.ui_source)
        self.assertIn('key="chat_model_picker"', self.ui_source)

    def test_narrow_controls_wrap_without_leaking_into_parent_grids(self) -> None:
        self.assertNotIn(
            'div[data-testid="stHorizontalBlock"]:has(.dm-control-marker)',
            self.css,
        )
        self.assertIn(
            'div[data-testid="stColumn"]:has(.center-pane-marker)\n'
            '    div[data-testid="stButtonGroup"]\n'
            '    > [role="radiogroup"]',
            self.css,
        )
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", self.css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", self.css)


if __name__ == "__main__":
    unittest.main()
