"""
check_design_compliance.py
==========================
对照 docs/design.md 校验拆分后的主题样式文件。

检查项：
  1. 必需令牌是否存在（:root）
  2. var(--space-*) / var(--type-*) / var(--radius-*) 使用计数
  3. spacing 属性里是否还有硬编码 rem/px（应为 0）
  4. font-size 是否还有硬编码值（应为 0）
  5. 旧令牌别名使用情况（--cyan / --mint / --amber 保留为 alias 是允许的）

用法：python scripts/check_design_compliance.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE_ROOT = ROOT / "assets" / "figma-hmi" / "styles"
CSS_FILES = sorted(STYLE_ROOT.glob("*.css"))

REQUIRED_TOKENS = {
    "spacing":  ["--space-1", "--space-2", "--space-3", "--space-4", "--space-6"],
    "type":     ["--type-label", "--type-note", "--type-body",
                 "--type-section", "--type-page", "--type-panel",
                 "--type-value", "--type-halo"],
    "radius":   ["--radius-panel", "--radius-card", "--radius-unit", "--radius-pill"],
    "color":    ["--bg", "--text", "--muted", "--accent",
                 "--success", "--warning", "--danger"],
    "glass":    ["--glass-blur", "--glass-panel", "--glass-card", "--glass-unit"],
}

SPACING_PROPS = (
    "gap", "row-gap", "column-gap",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "padding-inline", "padding-inline-start", "padding-inline-end",
    "padding-block",  "padding-block-start",  "padding-block-end",
    "margin",  "margin-top",  "margin-right",  "margin-bottom",  "margin-left",
    "margin-inline",  "margin-inline-start",  "margin-inline-end",
    "margin-block",   "margin-block-start",   "margin-block-end",
)

# 旧令牌名（design.md v2.2 时代），新文件中只允许作为 var(--xxx) 的 alias 定义出现
LEGACY_TOKENS = ["--cyan", "--type-xs", "--type-sm", "--type-md",
                 "--type-lg", "--type-xl", "--type-2xl",
                 "--surface-1", "--surface-2", "--surface-3"]

DECL_RE = re.compile(
    r"^(\s*)(" + "|".join(re.escape(p) for p in SPACING_PROPS) + r")(\s*:\s*)(.+?)(;)(\s*)$",
    re.IGNORECASE,
)
FONT_RE  = re.compile(r"^\s*font-size\s*:\s*([^;]+);", re.IGNORECASE)
NUMERIC_RE = re.compile(r"^\s*-?\d+(\.\d+)?(rem|px|em)\s*$", re.IGNORECASE)
LEGACY_USE_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in LEGACY_TOKENS) + r")\b")


def main() -> int:
    src = "\n".join(path.read_text(encoding="utf-8") for path in CSS_FILES)

    print("=" * 64)
    print(f" design compliance check — {STYLE_ROOT.relative_to(ROOT)}")
    print("=" * 64)

    # 1) 必需令牌
    print("\n[1] Required tokens")
    missing = []
    for group, names in REQUIRED_TOKENS.items():
        for n in names:
            if f"{n}:" not in src:
                missing.append(n)
                print(f"  MISSING  {n}")
            else:
                print(f"  ok       {n}")
    if not missing:
        print("  -> all required tokens present")

    # 2) 令牌使用次数
    print("\n[2] Token usage counts")
    for prefix in ("--space-", "--type-", "--radius-", "--accent", "--success",
                   "--warning", "--danger"):
        n = len(re.findall(r"var\(" + re.escape(prefix), src))
        marker = "  ok " if n > 0 else "  -- "
        print(f"  {marker}  var({prefix}*) × {n}")

    # 3) spacing 硬编码
    print("\n[3] Hardcoded rem/px in spacing properties (should be 0)")
    bad = []
    for i, line in enumerate(src.splitlines(), 1):
        m = DECL_RE.match(line)
        if not m:
            continue
        value = m.group(4)
        # 提取所有数值 token
        for token in re.findall(r"-?\d+(?:\.\d+)?(?:rem|px|em)", value):
            bad.append((i, line.rstrip(), token))
    if bad:
        for i, L, t in bad[:15]:
            print(f"  L{i}: {t}  in  {L.strip()[:90]}")
        if len(bad) > 15:
            print(f"  ... and {len(bad) - 15} more")
    else:
        print("  ok  none")

    # 4) font-size 硬编码
    print("\n[4] Hardcoded font-size (should be 0)")
    bad_fs = []
    for i, line in enumerate(src.splitlines(), 1):
        m = FONT_RE.match(line)
        if not m:
            continue
        val = m.group(1).strip()
        if "var(--type-" not in val and NUMERIC_RE.match(val):
            bad_fs.append((i, line.rstrip(), val))
    if bad_fs:
        for i, L, t in bad_fs[:10]:
            print(f"  L{i}: {t}  in  {L.strip()[:90]}")
    else:
        print("  ok  none")

    # 5) 旧令牌
    print("\n[5] Legacy token references (alias definitions in :root are OK)")
    legacy_lines = []
    in_root = False
    for i, line in enumerate(src.splitlines(), 1):
        if ":root" in line and "{" in line:
            in_root = True
        if in_root and "}" in line:
            in_root = False
        if in_root:
            continue
        if LEGACY_USE_RE.search(line):
            legacy_lines.append((i, line.rstrip()))
    if legacy_lines:
        for i, L in legacy_lines[:10]:
            print(f"  L{i}: {L.strip()[:100]}")
        if len(legacy_lines) > 10:
            print(f"  ... and {len(legacy_lines) - 10} more")
    else:
        print("  ok  no legacy tokens used outside :root")

    # 总结
    print("\n" + "=" * 64)
    total_issues = len(missing) + len(bad) + len(bad_fs) + len(legacy_lines)
    if total_issues == 0:
        print(" RESULT: PASS — design system compliant")
        return 0
    print(f" RESULT: {total_issues} issue(s) — see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
