"""Run the language-benchmark suites selected in config.json.

    python run.py
    python run.py --skip-ollama
    python run.py --only gpt-5.6-sol
    python run.py --no-publish

Flags are forwarded to each suite script and override the config file.
After those suites have been attempted, articles are built from the JSON
already on disk, then the Hugo site is published unless publish is off.
"""
import subprocess
import sys
from pathlib import Path

import bench_config

HERE = Path(__file__).resolve().parent
SCRIPTS = {"zh": "zhbench.py", "en": "enbench.py", "doc": "docbench.py"}
# gen_post needs both writing records; gen_doc_post needs the tutorial record.
POSTS = (
    ("gen_post.py", ("zhbench.json", "enbench.json")),
    ("gen_doc_post.py", ("docbench.json",)),
)


def run_suites(selected) -> int:
    """Attempt each selected suite. A failure leaves JSON already on disk."""
    code = 0
    for name in selected:
        script = HERE / SCRIPTS[name]
        print(f"== {script.name} ==", flush=True)
        result = subprocess.run([sys.executable, str(script), *sys.argv[1:]])
        if result.returncode != 0:
            print(
                f"{script.name} exited {result.returncode}; "
                "leaving existing JSON in place",
                flush=True,
            )
            if code == 0:
                code = result.returncode
    return code


def generate_posts(out_dir: Path) -> None:
    """Build website articles from JSON on disk. Skip a generator whose inputs are missing."""
    for script_name, required in POSTS:
        missing = [name for name in required if not (out_dir / name).is_file()]
        if missing:
            print(
                f"skip {script_name}: missing {', '.join(missing)} in {out_dir}",
                flush=True,
            )
            continue
        script = HERE / script_name
        print(f"== {script.name} ==", flush=True)
        result = subprocess.run([sys.executable, str(script)])
        if result.returncode != 0:
            raise SystemExit(result.returncode)


def publish_site(cfg, argv=None) -> None:
    """Push the Hugo site the same way update.ps1 / update.sh do.

    Those scripts call tools/website/publish.py. summarize and the FLOPS
    benchmark reach them through common.hugo.run_hugo_update.
    """
    if not bench_config.publish_enabled(cfg, argv):
        print("publish off; skipping the live push", flush=True)
        return
    from common.hugo import run_hugo_update

    print("== website publish ==", flush=True)
    try:
        ok = run_hugo_update(Path("tools/website"))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    if not ok:
        raise SystemExit("website update script not found")


def main():
    cfg = bench_config.load_config()
    selected = bench_config.suite_names(cfg)
    print(f"config: {cfg['_source']}", flush=True)
    print(f"suites: {selected or '(none)'}", flush=True)
    code = run_suites(selected)
    generate_posts(bench_config.output_dir(cfg))
    publish_site(cfg)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
