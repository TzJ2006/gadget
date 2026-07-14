"""
HTML report generation for benchmark results.

Generates interactive HTML reports with leaderboards and charts
using Plotly and Pandas.

The report automatically includes all historical data from the CSV file,
making it "self-growing" - each time you benchmark new hardware,
those results are added to the CSV and the report reflects all accumulated data.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from plotly.offline import get_plotlyjs_version


class BenchmarkReport:
    """
    Generate HTML reports from benchmark CSV data.

    The report is designed to be "self-growing":
    - CSV files use append mode, accumulating results over time
    - Report generation reads ALL data from the CSV
    - Each hardware shows its best performance across all runs
    - Historical trends show performance over time

    Features:
    - Leaderboards for CPU/GPU performance
    - Comparison charts (bar charts)
    - Historical trend charts
    - Precision comparison charts
    - Run history tracking
    """

    # HTML template
    HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark Results Report</title>
    <script src="{plotly_js_cdn}"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 40px 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            margin-bottom: 30px;
        }}
        .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .header .subtitle {{ color: #888; font-size: 1.1em; }}
        .section {{
            background: rgba(255,255,255,0.03);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .section h2 {{
            font-size: 1.8em;
            margin-bottom: 20px;
            color: #4fc3f7;
            border-bottom: 2px solid #4fc3f7;
            padding-bottom: 10px;
        }}
        .section h3 {{
            font-size: 1.4em;
            margin-bottom: 15px;
            color: #81c784;
            margin-top: 25px;
        }}
        .chart-container {{
            width: 100%;
            height: 500px;
            margin: 20px 0;
            border-radius: 10px;
            overflow: hidden;
        }}
        .leaderboard-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: rgba(255,255,255,0.02);
            border-radius: 10px;
            overflow: hidden;
        }}
        .leaderboard-table th {{
            background: rgba(76, 175, 80, 0.2);
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #81c784;
        }}
        .leaderboard-table td {{
            padding: 12px 15px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .leaderboard-table tr:hover {{
            background: rgba(255,255,255,0.05);
        }}
        .rank-1 {{ color: #ffd700; font-weight: bold; }}
        .rank-2 {{ color: #c0c0c0; font-weight: bold; }}
        .rank-3 {{ color: #cd7f32; font-weight: bold; }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}
        .stat-card .value {{
            font-size: 2em;
            font-weight: bold;
            color: #4fc3f7;
        }}
        .stat-card .label {{
            color: #888;
            margin-top: 5px;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }}
        @media (max-width: 768px) {{
            .header h1 {{ font-size: 1.8em; }}
            .chart-container {{ height: 350px; }}
            .leaderboard-table {{ font-size: 0.9em; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Benchmark Results Report</h1>
            <div class="subtitle">
                Generated: {generated_time}<br>
                📊 Total Records: {total_records} | 📅 Date Range: {date_range}<br>
                🖥️ Unique CPUs: {unique_cpus} | 🎮 Unique GPUs: {unique_gpus} | 🔄 Total Runs: {total_runs}
            </div>
        </div>

        {content}

        <div class="footer">
            <p>Generated by Cross-Platform Benchmark Tool |
               <a href="https://github.com/TzJ2006/gadget/tree/main/test" style="color: #4fc3f7;">GitHub</a>
               <br>
               <small style="color: #666;">Report includes all historical benchmark results - new hardware automatically added</small>
            </p>
        </div>
    </div>
</body>
</html>
"""

    def __init__(self, csv_path: str):
        """
        Initialize report generator.

        Args:
            csv_path: Path to benchmark CSV file
        """
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Load and process data
        self.df = pd.read_csv(self.csv_path)
        self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
        self.df['flops_gflops'] = pd.to_numeric(self.df['flops_gflops'], errors='coerce')
        self.df['date'] = self.df['timestamp'].dt.date

        # Remove rows that cannot be plotted numerically
        before_numeric_filter = len(self.df)
        self.df = self.df.dropna(subset=['timestamp', 'flops_gflops'])
        numeric_filtered = before_numeric_filter - len(self.df)
        if numeric_filtered > 0:
            print(f"Filtered out {numeric_filtered} records with invalid numeric/time values")

        # Filter out records with Unknown CPU
        before_count = len(self.df)
        self.df = self.df[~self.df['cpu_model'].str.contains('Unknown', case=False, na=False)]
        filtered_count = before_count - len(self.df)
        if filtered_count > 0:
            print(f"Filtered out {filtered_count} records with Unknown CPU")

        # Figures to include in report
        self.figures: List[Tuple[str, str, go.Figure]] = []  # (title, div_id, figure)

    def _plotly_cdn_url(self) -> str:
        """Use a pinned Plotly JS version compatible with installed plotly.py."""
        version = get_plotlyjs_version()
        return f"https://cdn.plot.ly/plotly-{version}.min.js"

    def _get_summary_stats(self) -> Dict[str, any]:
        """Get summary statistics including date range."""
        min_date = self.df['timestamp'].min().strftime('%Y-%m-%d')
        max_date = self.df['timestamp'].max().strftime('%Y-%m-%d')
        date_range = f"{min_date} to {max_date}"

        # Count total runs (unique dates)
        total_runs = self.df['date'].nunique()

        return {
            'total_records': len(self.df),
            'unique_cpus': self.df['cpu_model'].nunique(),
            'unique_gpus': self.df[self.df['gpu_vendor'] != 'N/A']['gpu_model'].nunique(),
            'date_range': date_range,
            'total_runs': total_runs,
        }

    def generate_cpu_leaderboard(self) -> pd.DataFrame:
        """
        Generate CPU performance leaderboard.

        Returns:
            DataFrame with rankings
        """
        # Filter CPU benchmarks only
        cpu_df = self.df[self.df['benchmark_type'].str.contains('cpu', case=False, na=False)].copy()

        # Get best result per CPU model and benchmark type
        leaderboards = []
        for bench_type in cpu_df['benchmark_type'].unique():
            type_df = cpu_df[cpu_df['benchmark_type'] == bench_type]
            best = type_df.groupby('cpu_model').agg({
                'flops_gflops': 'max',
                'timestamp': 'max'
            }).reset_index()
            best['benchmark_type'] = bench_type
            leaderboards.append(best)

        if not leaderboards:  # no CPU rows (e.g. a GPU-only CSV) — avoid pd.concat([])
            return pd.DataFrame()

        result = pd.concat(leaderboards, ignore_index=True)
        result = result.sort_values(['benchmark_type', 'flops_gflops'], ascending=[True, False])
        result['rank'] = result.groupby('benchmark_type').cumcount() + 1

        return result

    def generate_gpu_leaderboard(self) -> pd.DataFrame:
        """
        Generate GPU performance leaderboard.

        Returns:
            DataFrame with rankings
        """
        # Filter GPU benchmarks only
        gpu_df = self.df[(self.df['backend'].isin(['cuda', 'mps', 'xpu'])) &
                         (self.df['flops_gflops'] > 0)].copy()

        if gpu_df.empty:
            return pd.DataFrame()

        # Get best result per GPU model and dtype
        leaderboards = []
        for dtype in gpu_df['dtype'].unique():
            if dtype == 'N/A':
                continue
            type_df = gpu_df[gpu_df['dtype'] == dtype]
            best = type_df.groupby(['gpu_model', 'gpu_vendor']).agg({
                'flops_gflops': 'max',
                'timestamp': 'max'
            }).reset_index()
            best['dtype'] = dtype
            leaderboards.append(best)

        if not leaderboards:  # all GPU rows had dtype 'N/A' — avoid pd.concat([])
            return pd.DataFrame()

        result = pd.concat(leaderboards, ignore_index=True)
        result = result.sort_values(['dtype', 'flops_gflops'], ascending=[True, False])
        result['rank'] = result.groupby('dtype').cumcount() + 1

        return result

    def create_cpu_comparison_chart(self) -> go.Figure:
        """Create CPU performance comparison bar chart."""
        cpu_df = self.df[self.df['benchmark_type'].str.contains('cpu', case=False, na=False)].copy()

        # Get latest result per CPU and benchmark type
        # Use drop_duplicates to get the latest result for each CPU+type combination
        latest = cpu_df.sort_values('timestamp').drop_duplicates(
            ['cpu_model', 'benchmark_type'], keep='last'
        )

        # Create separate chart for each benchmark type
        fig = go.Figure()

        colors = {
            'cpu_single_core': '#FF6B6B',
            'cpu_single_core_blas': '#4ECDC4',
            'cpu_all_cores': '#96CEB4',
        }

        for bench_type in latest['benchmark_type'].unique():
            type_df = latest[latest['benchmark_type'] == bench_type].sort_values(
                'flops_gflops', ascending=False
            )
            x_values = type_df['cpu_model'].astype(str).tolist()
            y_values = type_df['flops_gflops'].astype(float).tolist()
            fig.add_trace(go.Bar(
                name=bench_type.replace('_', ' ').title(),
                x=x_values,
                y=y_values,
                marker_color=colors.get(bench_type, '#95E1D3'),
            ))

        fig.update_layout(
            title='🖥️ CPU Performance Comparison (GFLOPS)',
            xaxis_title='CPU Model',
            yaxis_title='Performance (GFLOPS)',
            barmode='group',
            height=500,
            template='plotly_dark',
            hovermode='x unified',
            yaxis=dict(rangemode='tozero'),
        )

        return fig

    def create_gpu_comparison_chart(self, dtype: str = 'FP32') -> go.Figure:
        """Create GPU performance comparison bar chart."""
        gpu_df = self.df[(self.df['backend'].isin(['cuda', 'mps', 'xpu'])) &
                         (self.df['dtype'] == dtype) &
                         (self.df['flops_gflops'] > 0)].copy()

        if gpu_df.empty:
            # Return empty figure if no data
            fig = go.Figure()
            fig.add_annotation(text=f"No {dtype} GPU data available",
                             xref="paper", yref="paper",
                             x=0.5, y=0.5, showarrow=False)
            return fig

        # Get best result per GPU
        best = gpu_df.sort_values('flops_gflops', ascending=False).drop_duplicates(
            ['gpu_model', 'gpu_vendor'], keep='first'
        ).sort_values('flops_gflops', ascending=False).reset_index(drop=True)

        # Create labels with vendor
        best['label'] = best['gpu_vendor'] + ' ' + best['gpu_model']
        labels = best['label'].astype(str).tolist()
        scores = best['flops_gflops'].astype(float).tolist()
        score_text = [f'{score:,.0f}' for score in scores]

        fig = go.Figure(data=[
            go.Bar(
                x=labels,
                y=scores,
                marker=dict(
                    color=scores,
                    colorscale='Viridis',
                    showscale=False,  # Hide colorbar
                ),
                text=score_text,
                textposition='outside',
            )
        ])

        fig.update_layout(
            title=f'🎮 GPU Performance Comparison ({dtype})',
            xaxis_title='GPU Model',
            yaxis_title='Performance (GFLOPS)',
            height=500,
            template='plotly_dark',
            yaxis=dict(rangemode='tozero'),
        )

        return fig

    def create_precision_comparison_chart(self) -> go.Figure:
        """Create chart comparing different precisions for each GPU."""
        gpu_df = self.df[(self.df['backend'].isin(['cuda', 'mps', 'xpu'])) &
                         (self.df['flops_gflops'] > 0)].copy()

        if gpu_df.empty:
            fig = go.Figure()
            fig.add_annotation(text="No GPU data available",
                             xref="paper", yref="paper",
                             x=0.5, y=0.5, showarrow=False)
            return fig

        # Get best result per GPU and precision
        best = gpu_df.sort_values('flops_gflops', ascending=False).drop_duplicates(
            ['gpu_model', 'dtype'], keep='first'
        )

        fig = go.Figure()

        for gpu in best['gpu_model'].unique():
            gpu_data = best[best['gpu_model'] == gpu].sort_values('flops_gflops', ascending=False)
            fig.add_trace(go.Bar(
                name=gpu,
                x=gpu_data['dtype'].astype(str).tolist(),
                y=gpu_data['flops_gflops'].astype(float).tolist(),
            ))

        fig.update_layout(
            title='📊 GPU Performance by Precision',
            xaxis_title='Precision',
            yaxis_title='Performance (GFLOPS)',
            barmode='group',
            height=500,
            template='plotly_dark',
            hovermode='x unified',
            yaxis=dict(rangemode='tozero'),
        )

        return fig

    def create_trend_chart(self) -> go.Figure:
        """Compatibility fallback: trend chart section is removed from report."""
        fig = go.Figure()
        fig.add_annotation(
            text="Historical trend chart is disabled in this report version.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        fig.update_layout(
            title="Historical Trends (Disabled)",
            height=500,
            template="plotly_dark",
        )
        return fig

    def _format_leaderboard_table(self, df: pd.DataFrame, title: str) -> str:
        """Format leaderboard DataFrame as HTML table."""
        if df.empty:
            return f'<p>No {title} data available.</p>'

        html = f'<h3>{title}</h3>'
        html += '<table class="leaderboard-table">'

        # Table header
        html += '<thead><tr>'
        if 'rank' in df.columns:
            html += '<th>Rank</th>'
        for col in df.columns:
            if col not in ['rank', 'date'] and df[col].dtype != 'datetime64[ns]':
                html += f'<th>{col.replace("_", " ").title()}</th>'
        html += '</tr></thead><tbody>'

        # Table body
        for _, row in df.iterrows():
            rank = row.get('rank', 0)
            rank_class = f'rank-{rank}' if 1 <= rank <= 3 else ''

            html += f'<tr class="{rank_class}">'
            if 'rank' in df.columns:
                html += f'<td>#{int(rank)}</td>'
            for col in df.columns:
                if col not in ['rank', 'date'] and df[col].dtype != 'datetime64[ns]':
                    val = row[col]
                    if pd.notna(val):
                        if isinstance(val, float) and 'flops' in col.lower():
                            html += f'<td>{val:,.2f}</td>'
                        else:
                            html += f'<td>{val}</td>'
                    else:
                        html += '<td>N/A</td>'
            html += '</tr>'

        html += '</tbody></table>'
        return html

    def _format_stat_card(self, value: str, label: str) -> str:
        """Format a stat card HTML."""
        return f"""
        <div class="stat-card">
            <div class="value">{value}</div>
            <div class="label">{label}</div>
        </div>
        """

    def generate_html(self, output_path: str = 'benchmark_report.html'):
        """
        Generate complete HTML report.

        Args:
            output_path: Path to output HTML file
        """
        print("Generating HTML report...")

        # Generate all content
        content_parts = []

        # 1. Summary statistics
        stats = self._get_summary_stats()
        content_parts.append('<div class="section"><h2>📊 Summary Statistics</h2>')
        content_parts.append('<div class="stat-grid">')
        content_parts.append(self._format_stat_card(str(stats['total_records']), 'Total Records'))
        content_parts.append(self._format_stat_card(str(stats['unique_cpus']), 'Unique CPUs'))
        content_parts.append(self._format_stat_card(str(stats['unique_gpus']), 'Unique GPUs'))
        content_parts.append('</div></div>')

        # 2. CPU Leaderboard
        print("  Generating CPU leaderboard...")
        cpu_lb = self.generate_cpu_leaderboard()
        if not cpu_lb.empty:
            content_parts.append('<div class="section"><h2>🏆 CPU Performance Leaderboard</h2>')
            for bench_type in cpu_lb['benchmark_type'].unique():
                type_df = cpu_lb[cpu_lb['benchmark_type'] == bench_type]
                content_parts.append(self._format_leaderboard_table(type_df, bench_type.replace('_', ' ').title()))
            content_parts.append('</div>')

        # 3. GPU Leaderboard
        print("  Generating GPU leaderboard...")
        gpu_lb = self.generate_gpu_leaderboard()
        if not gpu_lb.empty:
            content_parts.append('<div class="section"><h2>🏆 GPU Performance Leaderboard</h2>')
            for dtype in gpu_lb['dtype'].unique():
                type_df = gpu_lb[gpu_lb['dtype'] == dtype]
                content_parts.append(self._format_leaderboard_table(type_df, f'{dtype} Performance'))
            content_parts.append('</div>')

        # 4. Charts
        content_parts.append('<div class="section"><h2>📈 Performance Charts</h2>')

        # CPU comparison chart
        print("  Generating CPU comparison chart...")
        cpu_fig = self.create_cpu_comparison_chart()
        content_parts.append('<h3>CPU Performance Comparison</h3>')
        content_parts.append(f'<div class="chart-container" id="cpu-chart"></div>')
        self.figures.append(('cpu-chart', cpu_fig.to_html(full_html=False, include_plotlyjs=False)))

        # GPU comparison charts (FP32, FP16, BF16)
        for dtype in ['FP32', 'FP16', 'BF16']:
            print(f"  Generating GPU {dtype} comparison chart...")
            gpu_fig = self.create_gpu_comparison_chart(dtype)
            content_parts.append(f'<h3>GPU {dtype} Performance</h3>')
            content_parts.append(f'<div class="chart-container" id="gpu-{dtype.lower()}-chart"></div>')
            self.figures.append((f'gpu-{dtype.lower()}-chart', gpu_fig.to_html(full_html=False, include_plotlyjs=False)))

        # Precision comparison
        print("  Generating precision comparison chart...")
        prec_fig = self.create_precision_comparison_chart()
        content_parts.append('<h3>Performance by Precision</h3>')
        content_parts.append(f'<div class="chart-container" id="precision-chart"></div>')
        self.figures.append(('precision-chart', prec_fig.to_html(full_html=False, include_plotlyjs=False)))

        content_parts.append('</div>')

        # Combine all content
        content = '\n'.join(content_parts)

        # Generate HTML
        generated_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        html = self.HTML_TEMPLATE.format(
            generated_time=generated_time,
            total_records=stats['total_records'],
            unique_cpus=stats['unique_cpus'],
            unique_gpus=stats['unique_gpus'],
            date_range=stats['date_range'],
            total_runs=stats['total_runs'],
            plotly_js_cdn=self._plotly_cdn_url(),
            content=content,
        )

        # Insert Plotly figures
        # Note: to_html() wraps content in <div>, so we need to strip the outer div tags
        # to avoid nested div issues with the chart-container
        for div_id, fig_html in self.figures:
            # Strip the outer <div> and </div> from fig_html
            fig_html_stripped = fig_html.strip()
            if fig_html_stripped.startswith('<div>'):
                fig_html_stripped = fig_html_stripped[5:]  # Remove '<div>'
            if fig_html_stripped.endswith('</div>'):
                fig_html_stripped = fig_html_stripped[:-6]  # Remove '</div>'
            html = html.replace(f'<div class="chart-container" id="{div_id}"></div>',
                               f'<div class="chart-container" id="{div_id}">{fig_html_stripped}</div>')

        # Write to file
        output_path = Path(output_path)
        output_path.write_text(html, encoding='utf-8')

        print(f"✓ HTML report saved to: {output_path.absolute()}")
        print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")


def generate_report(csv_path: str = '', output_path: str = ''):
    if not csv_path:
        from common.paths import DATA_DIR
        csv_path = str(DATA_DIR / "benchmark" / "results.csv")
    if not output_path:
        from common.paths import REPORTS_DIR
        output_path = str(REPORTS_DIR / "benchmark" / "report.html")
    """
    Generate HTML report from CSV data.

    Args:
        csv_path: Path to benchmark CSV file
        output_path: Path to output HTML file
    """
    report = BenchmarkReport(csv_path)
    report.generate_html(output_path)
