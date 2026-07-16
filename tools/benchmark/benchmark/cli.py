"""
Command-line interface for the cross-platform benchmarking tool.

Usage:
    python -m benchmark.cli                    # Run all benchmarks
    python -m benchmark.cli --cpu-only         # CPU benchmarks only
    python -m benchmark.cli --gpu-only         # GPU benchmarks only
    python -m benchmark.cli --report           # Generate HTML report
    python -m benchmark.cli --report-only      # Only generate report, don't run benchmarks
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import detect, cpu, gpu, core, report
from common.hugo import run_hugo_update
from common.paths import GADGET_ROOT, TOOLS_DIR

_PROJECT_ROOT = GADGET_ROOT
# Single SoT shared with submit/ingest/CI (was split vs outputs/data/benchmark/results.csv).
_DEFAULT_CSV = str(TOOLS_DIR / "benchmark" / "benchmark_results.csv")
_DEFAULT_HTML = str(_PROJECT_ROOT / "outputs" / "reports" / "benchmark" / "report.html")


def is_interactive() -> bool:
    """Return whether CLI can safely prompt for input."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def resolve_relay_url(args) -> str:
    """Resolve relay URL from CLI flag or environment fallback."""
    if args.relay_url:
        return args.relay_url.strip()
    return os.getenv('BENCHMARK_RELAY_URL', '').strip()


def prompt_upload() -> bool:
    """Ask user whether to upload result; default is No."""
    answer = input("Upload latest benchmark result to public leaderboard? [y/N]: ").strip().lower()
    return answer in {'y', 'yes'}


def run_upload(output_csv: str, relay_url: str, source_id: str, timeout: int, verbose: bool) -> tuple[bool, str]:
    """Upload latest CSV row via scripts/submit_result.py."""
    script_path = Path(__file__).resolve().parents[1] / 'scripts' / 'submit_result.py'
    if not script_path.exists():
        return False, f"Upload helper not found: {script_path}"

    cmd = [
        sys.executable,
        str(script_path),
        '--input-csv', output_csv,
        '--relay-url', relay_url,
        '--timeout', str(timeout),
    ]
    if source_id:
        cmd.extend(['--source-id', source_id])

    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"Upload execution failed: {e}"

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()

    if result.returncode == 0:
        message = stdout or "Upload succeeded."
        return True, message

    if verbose and stderr:
        return False, f"Upload failed: {stderr}"
    if stdout:
        return False, f"Upload failed: {stdout}"
    return False, f"Upload failed with exit code {result.returncode}"


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Cross-platform CPU/GPU benchmarking tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m benchmark.cli                    # Run all benchmarks (CSV auto-appends)
  python -m benchmark.cli --cpu-only         # CPU benchmarks only
  python -m benchmark.cli --gpu-only         # GPU benchmarks only
  python -m benchmark.cli --report           # Run benchmarks + generate HTML report
  python -m benchmark.cli --report-only      # Only generate report from existing CSV

Workflow for accumulating results:
  1. Run benchmark on different hardware (results append to CSV):
     python -m benchmark.cli --output my_results.csv

  2. Generate/update HTML report (includes ALL historical data):
     python -m benchmark.cli --report-only --input-csv my_results.csv

The HTML report automatically includes all hardware ever benchmarked!
        """
    )

    # Benchmark selection
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--cpu-only',
        action='store_true',
        help='Run only CPU benchmarks'
    )
    group.add_argument(
        '--gpu-only',
        action='store_true',
        help='Run only GPU benchmarks'
    )
    group.add_argument(
        '--report-only',
        action='store_true',
        help='Only generate HTML report, don\'t run benchmarks'
    )

    # Output options
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=_DEFAULT_CSV,
        help='Output CSV file path'
    )
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Run benchmarks without saving to CSV'
    )

    # Benchmark parameters
    parser.add_argument(
        '--matrix-size',
        type=int,
        default=None,
        help='Matrix size for GEMM benchmarks (default: 4096 GPU, 8192/4096 CPU)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=None,
        help='Number of iterations (default: auto)'
    )
    parser.add_argument(
        '--duration',
        type=float,
        default=10.0,
        help='Target duration per benchmark in seconds (default: 10.0, use 60 for 1 minute)'
    )

    # Display options
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Quiet mode (minimal output)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose mode (detailed output)'
    )

    # Info options
    parser.add_argument(
        '--info',
        action='store_true',
        help='Show system information and exit'
    )

    # Report options
    parser.add_argument(
        '--report',
        action='store_true',
        help='Generate HTML report after benchmarks'
    )
    parser.add_argument(
        '--report-output',
        type=str,
        default=_DEFAULT_HTML,
        help='HTML report output path'
    )
    parser.add_argument(
        '--input-csv',
        type=str,
        default=_DEFAULT_CSV,
        help='Input CSV file for report generation'
    )
    parser.add_argument(
        '--deploy',
        action='store_true',
        help='Publish the latest HTML report to Hugo and trigger website deploy'
    )
    parser.add_argument(
        '--hugo-site',
        type=str,
        default=str(TOOLS_DIR / "website"),
        help='Hugo site root'
    )

    # Upload options
    parser.add_argument(
        '--relay-url',
        type=str,
        default='',
        help='Relay endpoint URL for leaderboard submissions (fallback: BENCHMARK_RELAY_URL)'
    )
    parser.add_argument(
        '--ask-upload',
        action='store_true',
        help='Ask whether to upload after benchmark run (interactive terminals only)'
    )
    upload_group = parser.add_mutually_exclusive_group()
    upload_group.add_argument(
        '--upload',
        action='store_true',
        help='Upload automatically after benchmark run (non-interactive friendly)'
    )
    upload_group.add_argument(
        '--no-upload',
        action='store_true',
        help='Disable upload flow after benchmark run'
    )
    parser.add_argument(
        '--source-id',
        type=str,
        default='',
        help='Optional source identifier attached to uploaded submission'
    )
    parser.add_argument(
        '--upload-timeout',
        type=int,
        default=20,
        help='Upload request timeout in seconds (default: 20)'
    )

    return parser.parse_args()


def print_header():
    """Print benchmark header."""
    print("\n" + "=" * 60)
    print("Cross-Platform CPU/GPU Benchmarking Tool")
    print("=" * 60)


def print_summary(all_results: list, system_info: dict):
    """Print summary of all benchmark results."""
    print("\n" + "=" * 60)
    print("Benchmark Results Summary")
    print("=" * 60)

    for result in all_results:
        if 'error' in result:
            continue

        name = result.get('name', 'Unknown')
        dtype = result.get('dtype', 'N/A')
        flops = result.get('flops_formatted', 'N/A')

        print(f"\n{name}")
        if dtype != 'N/A':
            print(f"  Precision: {dtype}")
        print(f"  Performance: {flops}")

    print("\n" + "=" * 60 + "\n")


def deploy_report(report_path: str, hugo_site: str, verbose: bool = False) -> bool:
    """Publish the benchmark report to Hugo staging and deploy the website."""
    report_file = Path(report_path)
    if not report_file.exists():
        print(f"Warning: report file not found, skipping deploy: {report_file}")
        return False

    site_root = Path(hugo_site)
    if not site_root.exists():
        print(f"Warning: Hugo site not found, skipping deploy: {site_root}")
        return False

    try:
        from .publish import stage_benchmark_report

        wrapper_path, staged_report = stage_benchmark_report(report_file, site_root)
        print(f"Staged benchmark wrapper: {wrapper_path}")
        print(f"Staged benchmark HTML: {staged_report}")
        run_hugo_update(site_root)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Warning: benchmark deploy failed: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return False


def main():
    """Main entry point for the CLI."""
    args = parse_args()

    # Report-only mode: just generate report from existing CSV
    if args.report_only:
        csv_path = Path(args.input_csv)
        if not csv_path.exists():
            print(f"Error: CSV file not found: {csv_path}")
            print(f"Please run benchmarks first to generate data, or specify a different file with --input-csv")
            return 1

        print(f"Generating HTML report from: {csv_path}")
        try:
            report.generate_report(str(csv_path), args.report_output)
            print("\n✓ Report generation complete!")
            if args.deploy:
                deploy_report(args.report_output, args.hugo_site, args.verbose)
            return 0
        except Exception as e:
            print(f"\n✗ Error generating report: {e}")
            import traceback
            if args.verbose:
                traceback.print_exc()
            return 1

    # Get system information
    system_info = detect.get_system_info()

    # Info only mode
    if args.info:
        print_header()
        detect.print_system_info(system_info)
        return 0

    # Print header
    if not args.quiet:
        print_header()
        detect.print_system_info(system_info)

    # Initialize results manager
    if not args.no_save:
        results_manager = core.BenchmarkResults(args.output)

    # Run benchmarks
    all_results = []

    try:
        # CPU benchmarks
        if not args.gpu_only:
            cpu_results = cpu.run_all_cpu_benchmarks(duration=args.duration)
            all_results.extend(cpu_results)

        # GPU benchmarks
        if not args.cpu_only:
            gpu_results = gpu.run_all_gpu_benchmarks(
                matrix_size=args.matrix_size,
                iterations=args.iterations,
                duration=args.duration
            )
            all_results.extend(gpu_results)

        # Print summary
        if not args.quiet:
            print_summary(all_results, system_info)

        # Save results
        if not args.no_save:
            for result in all_results:
                results_manager.add(result, system_info)
            results_manager.save()

        # Generate HTML report if requested
        if args.report and not args.no_save:
            print("\nGenerating HTML report...")
            try:
                report.generate_report(args.output, args.report_output)
            except FileNotFoundError:
                print(f"Warning: CSV file not found, skipping report generation")
            except Exception as e:
                print(f"Warning: Error generating report: {e}")

        # Optional upload flow (only after saved benchmark runs)
        if not args.no_save:
            relay_url = resolve_relay_url(args)
            upload_requested = args.upload
            upload_allowed = not args.no_upload

            if not upload_allowed:
                if args.verbose:
                    print("Upload skipped (--no-upload).")
            elif upload_requested:
                if not relay_url:
                    print("Warning: upload requested but no relay URL configured (--relay-url or BENCHMARK_RELAY_URL).")
                else:
                    ok, msg = run_upload(
                        output_csv=args.output,
                        relay_url=relay_url,
                        source_id=args.source_id,
                        timeout=args.upload_timeout,
                        verbose=args.verbose,
                    )
                    if ok:
                        print(f"✓ {msg}")
                    else:
                        print(f"Warning: {msg}")
            elif is_interactive():
                # Default interactive behavior is opt-in prompt, only when endpoint is configured.
                if not relay_url:
                    if args.ask_upload:
                        print("Upload prompt skipped: no relay URL configured (--relay-url or BENCHMARK_RELAY_URL).")
                else:
                    if prompt_upload():
                        ok, msg = run_upload(
                            output_csv=args.output,
                            relay_url=relay_url,
                            source_id=args.source_id,
                            timeout=args.upload_timeout,
                            verbose=args.verbose,
                        )
                        if ok:
                            print(f"✓ {msg}")
                        else:
                            print(f"Warning: {msg}")
            else:
                if args.verbose:
                    print("Upload skipped in non-interactive mode (use --upload).")

        if args.deploy:
            report_path = Path(args.report_output)
            if not report_path.exists():
                if args.no_save:
                    print("Warning: deploy requested but no report exists and --no-save prevents regenerating it.")
                else:
                    print("\nGenerating HTML report for deploy...")
                    report.generate_report(args.output, args.report_output)
            deploy_report(args.report_output, args.hugo_site, args.verbose)

    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user.")
        return 1
    except Exception as e:
        print(f"\n\nError during benchmark: {e}")
        import traceback
        if args.verbose:
            traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
