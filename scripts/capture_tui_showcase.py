from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "tui-showcase"
OUTPUT = ROOT / "docs" / "tutorial" / "tui-showcase"

CASES = [
    ("01-minimal", "Minimal", "The smallest useful TUI: one workflow, one task and the core views.", ("monitor",)),
    ("02-workflow", "Standard workflow", "Dependencies, multiple tasks, stdout/stderr and a skipped optional task.", ("monitor", "logs")),
    ("03-artifacts", "Artifacts and contracts", "Inputs, outputs, checks, environment, cwd and reusable state.", ("monitor", "logs")),
    ("04-campaign", "Generic campaign", "Initialization plus four generic cycles, cycle navigation and campaign overview.", ("monitor", "cycles", "campaign", "logs")),
    ("05-problems", "Failure diagnosis", "A deliberate process failure with Problems and log evidence.", ("monitor", "problems", "logs")),
    ("06-invalid-input", "Invalid input", "A required input is missing before the process can start.", ("monitor", "problems")),
    ("07-invalid-output", "Invalid output", "The process exits successfully but violates its output contract.", ("monitor", "problems")),
    ("08-blocked", "Blocked dependency", "A disabled prerequisite leaves its downstream task blocked.", ("monitor", "problems")),
    ("09-timeout", "Timeout", "A local task exceeds its time limit and records diagnostic evidence.", ("monitor", "problems", "logs")),
]

EXPECTED_FAILURES = {
    "05-problems",
    "06-invalid-input",
    "07-invalid-output",
    "08-blocked",
    "09-timeout",
}

GENERATED_DIRS = {
    "03-artifacts": ("demo-work",),
    "04-campaign": ("campaign-work",),
    "05-problems": ("problem-work",),
    "07-invalid-output": ("invalid-output-work",),
}


def _swf(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "simpleworkflow.cli", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _prepare(case: str, workflow: Path) -> None:
    shutil.rmtree(workflow.parent / ".simpleworkflow", ignore_errors=True)
    for dirname in GENERATED_DIRS.get(case, ()):
        shutil.rmtree(workflow.parent / dirname, ignore_errors=True)
    result = _swf("run", str(workflow), "--ui", "plain", "--color", "never")
    if result.returncode != 0 and case not in EXPECTED_FAILURES:
        raise RuntimeError(
            f"showcase {case} failed unexpectedly with {result.returncode}:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )


def _capture(case: str, workflow: Path, view: str) -> Path:
    output = OUTPUT / f"{case}-{view}.svg"
    result = _swf(
        "capture-tui",
        str(workflow),
        "--view",
        view,
        "--size",
        "140x45",
        "--output",
        str(output),
        "--color",
        "always",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"capture failed for {case}/{view}:\n{result.stderr}"
        )
    return output


def _write_gallery(images: list[tuple[str, str, Path]]) -> None:
    lines = [
        "# simpleWorkflow TUI showcase",
        "",
        "Generated from deterministic 140x45 virtual terminal captures.",
        "",
    ]
    current = None
    for case, view, image in images:
        if case != current:
            current = case
            lines.extend([f"## {case}", ""])
        relative = image.relative_to(OUTPUT.parent)
        lines.extend(
            [
                f"### {view}",
                "",
                f"![{case} - {view}]({relative.as_posix()})",
                "",
            ]
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    (OUTPUT.parent / "tui-showcase.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )




def _write_html(images: list[tuple[str, str, Path]]) -> None:
    by_case: dict[str, list[tuple[str, Path]]] = {}
    for case, view, image in images:
        by_case.setdefault(case, []).append((view, image))

    nav = []
    sections = []
    for case, title, description, _views in CASES:
        nav.append(f'<a href="#{case}">{title}</a>')
        figures = []
        for view, image in by_case.get(case, []):
            rel = image.relative_to(OUTPUT.parent).as_posix()
            figures.append(
                f"""
                <figure class="shot">
                  <a href="{rel}" target="_blank" rel="noopener">
                    <img src="{rel}" alt="{title} — {view}" loading="lazy">
                  </a>
                  <figcaption><strong>{view}</strong><span>Open full-size SVG ↗</span></figcaption>
                </figure>
                """
            )
        sections.append(
            f"""
            <section id="{case}" class="case">
              <div class="case-heading">
                <span class="case-number">{case.split('-', 1)[0]}</span>
                <div>
                  <h2>{title}</h2>
                  <p>{description}</p>
                </div>
              </div>
              <div class="shots">{''.join(figures)}</div>
            </section>
            """
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>simpleWorkflow — TUI Showcase</title>
  <style>
    :root {{
      --bg:#0b0d12; --panel:#121620; --panel2:#171c27; --line:#2a3242;
      --text:#eef2f8; --muted:#9aa7b8; --accent:#8ab4ff; --accent2:#b9ccff;
      --max:1500px;
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0; background:var(--bg); color:var(--text);
      font:16px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }}
    a {{ color:var(--accent); }}
    header {{
      border-bottom:1px solid var(--line);
      background:linear-gradient(180deg,#121722 0%,#0b0d12 100%);
    }}
    .hero {{ max-width:var(--max); margin:auto; padding:64px 28px 40px; }}
    .eyebrow {{
      display:inline-block; color:var(--accent); font-weight:700; letter-spacing:.12em;
      text-transform:uppercase; font-size:.78rem; margin-bottom:12px;
    }}
    h1 {{ font-size:clamp(2.2rem,6vw,5rem); line-height:.96; margin:0 0 22px; letter-spacing:-.045em; }}
    .lead {{ max-width:820px; color:var(--muted); font-size:1.15rem; margin:0; }}
    .meta {{ margin-top:24px; display:flex; gap:10px; flex-wrap:wrap; }}
    .pill {{
      border:1px solid var(--line); background:var(--panel); border-radius:999px;
      padding:7px 11px; color:var(--muted); font-size:.9rem;
    }}
    nav {{
      position:sticky; top:0; z-index:10; border-bottom:1px solid var(--line);
      background:rgba(11,13,18,.94); backdrop-filter:blur(10px);
      overflow:auto; white-space:nowrap;
    }}
    nav .inner {{
      max-width:var(--max); margin:auto; padding:12px 28px; display:flex; gap:18px;
    }}
    nav a {{ text-decoration:none; color:var(--muted); font-size:.92rem; }}
    nav a:hover {{ color:var(--text); }}
    main {{ max-width:var(--max); margin:auto; padding:18px 28px 80px; }}
    .case {{ padding:56px 0; border-bottom:1px solid var(--line); scroll-margin-top:55px; }}
    .case-heading {{ display:flex; gap:18px; align-items:flex-start; margin-bottom:24px; }}
    .case-number {{
      min-width:46px; height:46px; display:grid; place-items:center; border:1px solid var(--line);
      background:var(--panel); border-radius:12px; color:var(--accent2); font-weight:800;
    }}
    h2 {{ margin:0 0 5px; font-size:1.7rem; }}
    .case-heading p {{ margin:0; color:var(--muted); max-width:820px; }}
    .shots {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,620px),1fr)); gap:20px; }}
    .shot {{
      margin:0; border:1px solid var(--line); background:var(--panel);
      border-radius:14px; overflow:hidden; box-shadow:0 10px 30px rgba(0,0,0,.18);
    }}
    .shot a {{ display:block; background:#080a0e; }}
    .shot img {{ display:block; width:100%; height:auto; }}
    figcaption {{
      display:flex; justify-content:space-between; gap:16px; padding:12px 14px;
      border-top:1px solid var(--line); text-transform:capitalize;
    }}
    figcaption span {{ color:var(--muted); font-size:.88rem; }}
    footer {{ max-width:var(--max); margin:auto; padding:0 28px 55px; color:var(--muted); }}
    code {{ background:var(--panel2); border:1px solid var(--line); border-radius:5px; padding:2px 5px; }}
    @media (max-width:650px) {{
      .hero {{ padding-top:42px; }}
      .hero, main, nav .inner, footer {{ padding-left:18px; padding-right:18px; }}
      .case {{ padding:38px 0; }}
      .case-heading {{ gap:12px; }}
      figcaption {{ align-items:flex-start; flex-direction:column; gap:2px; }}
    }}
  </style>
</head>
<body>
<header>
  <div class="hero">
    <span class="eyebrow">simpleWorkflow 0.6.0</span>
    <h1>TUI Showcase</h1>
    <p class="lead">A visual tour from the smallest local workflow to cycles, campaign views and failure diagnostics. Every screenshot is generated deterministically from runnable examples.</p>
    <div class="meta">
      <span class="pill">140 × 45 virtual terminal</span>
      <span class="pill">SVG screenshots</span>
      <span class="pill">Generic examples — no MONAN/JEDI dependency</span>
    </div>
  </div>
</header>
<nav><div class="inner">{''.join(nav)}</div></nav>
<main>{''.join(sections)}</main>
<footer>
  Generated by <code>python scripts/capture_tui_showcase.py</code>.
  Click any screenshot to inspect the original SVG at full size.
</footer>
</body>
</html>
"""
    page = OUTPUT.parent / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    images: list[tuple[str, str, Path]] = []
    for case, _title, _description, views in CASES:
        workflow = SHOWCASE / case / "workflow.yaml"
        _prepare(case, workflow)
        for view in views:
            images.append((case, view, _capture(case, workflow, view)))
    _write_gallery(images)
    _write_html(images)
    print(OUTPUT.parent / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
