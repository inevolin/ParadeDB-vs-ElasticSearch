#!/usr/bin/env python3
"""
ParadeDB vs Elasticsearch Benchmark Plot Generator
Generates performance comparison plots from benchmark results
"""

import os
import sys
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

def parse_time_file(filepath):
    """Parse timing file and extract average and total times in seconds"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            avg_time = None
            total_time = None
            
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('Average time'):
                    time_str = line.split(':')[1].strip()
                    avg_time = float(time_str.rstrip('s'))
                elif line.startswith('Total time'):
                    time_str = line.split(':')[1].strip()
                    total_time = float(time_str.rstrip('s'))
            
            return {'average': avg_time, 'total': total_time}
            
            # Fallback: Look for "real XmY.ZZZs" format (old format)
            for line in content.split('\n'):
                if line.strip().startswith('real'):
                    time_str = line.split()[1]
                    # Convert XmY.ZZZs to seconds
                    if 'm' in time_str:
                        minutes, seconds = time_str.split('m')
                        seconds = seconds.rstrip('s')
                        total_seconds = float(minutes) * 60 + float(seconds)
                    else:
                        total_seconds = float(time_str.rstrip('s'))
                    return {'average': total_seconds, 'total': total_seconds}
    except (FileNotFoundError, ValueError, IndexError):
        pass
    return None

def generate_plots(databases, results_dir='results', plots_dir='plots', scale=''):
    """Generate performance comparison plots"""

    # Ensure plots directory exists
    Path(plots_dir).mkdir(exist_ok=True)

    queries = ['query1', 'query2', 'query3']
    query_labels = ['Simple Term Search', 'Phrase Search', 'Complex Query']

    # Colors for different databases
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

    # Collect all times for totals
    total_times = {db: 0.0 for db in databases}
    query_times = {query: {db: None for db in databases} for query in queries}
    query_tps = {query: {db: None for db in databases} for query in queries}

    for query in queries:
        for db in databases:
            time_file = os.path.join(results_dir, f'{scale}_{db}_{query}_time.txt')
            times = parse_time_file(time_file)
            if times:
                avg_time = times['average']
                query_times[query][db] = avg_time
                # Calculate TPS (Transactions Per Second) = 1 / average_time
                if avg_time > 0:
                    query_tps[query][db] = 1.0 / avg_time
                if times['total'] is not None:
                    total_times[db] += times['total']

    # Create figure with subplots (2x4: three queries time + total time + three queries TPS + total TPS)
    fig, axes = plt.subplots(2, 4, figsize=(20, 10))
    axes = axes.flatten()
    fig.suptitle('ParadeDB vs Elasticsearch Performance Comparison (Time & TPS)', fontsize=16, fontweight='bold')

    # Plot query times (first row)
    for i, (query, label) in enumerate(zip(queries, query_labels)):
        ax = axes[i]

        db_names = []
        times = []

        for db in databases:
            time_seconds = query_times[query][db]
            if time_seconds is not None:
                db_names.append(db.title())
                times.append(time_seconds)

        if times:
            # Create bar chart
            bars = ax.bar(range(len(db_names)), times, color=colors[:len(db_names)], alpha=0.7)

            # Add value labels on bars
            for bar, time in zip(bars, times):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + max(times)*0.02,
                       f'{time:.4f}', ha='center', va='bottom', fontweight='bold')

            # Customize plot
            ax.set_title(f'{label}\nQuery {i+1} - Time', fontweight='bold')
            ax.set_ylabel('Time (seconds)')
            ax.set_xticks(range(len(db_names)))
            ax.set_xticklabels(db_names, rotation=45, ha='right')
            ax.grid(True, alpha=0.3, axis='y')

            # Set y-axis to start from 0
            ax.set_ylim(bottom=0)

        else:
            ax.text(0.5, 0.5, 'No data available',
                   transform=ax.transAxes, ha='center', va='center',
                   fontsize=12, color='gray')
            ax.set_title(f'{label}\nQuery {i+1} - Time', fontweight='bold')

    # Total duration subplot (first row, last column)
    ax = axes[3]
    db_names = []
    totals = []
    for db in databases:
        if total_times[db] > 0:
            db_names.append(db.title())
            totals.append(total_times[db])

    if totals:
        bars = ax.bar(range(len(db_names)), totals, color=colors[:len(db_names)], alpha=0.7)
        for bar, total in zip(bars, totals):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + max(totals)*0.02,
                   f'{total:.4f}', ha='center', va='bottom', fontweight='bold')
        ax.set_title('Total Test Duration', fontweight='bold')
        ax.set_ylabel('Time (seconds)')
        ax.set_xticks(range(len(db_names)))
        ax.set_xticklabels(db_names, rotation=45, ha='right')
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_ylim(bottom=0)
    else:
        ax.text(0.5, 0.5, 'No data available',
               transform=ax.transAxes, ha='center', va='center',
               fontsize=12, color='gray')
        ax.set_title('Total Test Duration', fontweight='bold')

    # Plot query TPS (second row)
    for i, (query, label) in enumerate(zip(queries, query_labels)):
        ax = axes[i + 4]  # Second row

        db_names = []
        tps_values = []

        for db in databases:
            tps = query_tps[query][db]
            if tps is not None:
                db_names.append(db.title())
                tps_values.append(tps)

        if tps_values:
            # Create bar chart
            bars = ax.bar(range(len(db_names)), tps_values, color=colors[:len(db_names)], alpha=0.7)

            # Add value labels on bars
            for bar, tps_val in zip(bars, tps_values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + max(tps_values)*0.02,
                       f'{tps_val:.2f}', ha='center', va='bottom', fontweight='bold')

            # Customize plot
            ax.set_title(f'{label}\nQuery {i+1} - TPS', fontweight='bold')
            ax.set_ylabel('Transactions Per Second')
            ax.set_xticks(range(len(db_names)))
            ax.set_xticklabels(db_names, rotation=45, ha='right')
            ax.grid(True, alpha=0.3, axis='y')

            # Set y-axis to start from 0
            ax.set_ylim(bottom=0)

        else:
            ax.text(0.5, 0.5, 'No data available',
                   transform=ax.transAxes, ha='center', va='center',
                   fontsize=12, color='gray')
            ax.set_title(f'{label}\nQuery {i+1} - TPS', fontweight='bold')

    # Total TPS subplot (second row, last column)
    ax = axes[7]
    db_names = []
    total_tps_values = []
    
    # Calculate total TPS as sum of individual query TPS
    for db in databases:
        total_tps = 0
        count = 0
        for query in queries:
            if query_tps[query][db] is not None:
                total_tps += query_tps[query][db]
                count += 1
        if count > 0:
            db_names.append(db.title())
            total_tps_values.append(total_tps / count)  # Average TPS across queries

    if total_tps_values:
        bars = ax.bar(range(len(db_names)), total_tps_values, color=colors[:len(db_names)], alpha=0.7)
        for bar, tps_val in zip(bars, total_tps_values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + max(total_tps_values)*0.02,
                   f'{tps_val:.2f}', ha='center', va='bottom', fontweight='bold')
        ax.set_title('Average TPS Across Queries', fontweight='bold')
        ax.set_ylabel('Transactions Per Second')
        ax.set_xticks(range(len(db_names)))
        ax.set_xticklabels(db_names, rotation=45, ha='right')
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_ylim(bottom=0)
    else:
        ax.text(0.5, 0.5, 'No data available',
               transform=ax.transAxes, ha='center', va='center',
               fontsize=12, color='gray')
        ax.set_title('Average TPS Across Queries', fontweight='bold')

    plt.tight_layout()

    # Save plot
    plot_file = os.path.join(plots_dir, f'{scale}_performance_comparison.png' if scale else 'performance_comparison.png')
    plt.savefig(plot_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"Performance plot saved to: {plot_file}")

    # Generate aggregated plot (all queries in one chart) - Time
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    fig2.suptitle('Aggregated Performance by Query Type - Time', fontsize=16, fontweight='bold')

    x = np.arange(len(queries))
    width = 0.35

    db_data = []
    for db in databases:
        times = [query_times[q][db] for q in queries]
        db_data.append(times)

    if any(any(t is not None for t in times) for times in db_data):
        for i, db in enumerate(databases):
            times = [query_times[q][db] for q in queries]
            valid_times = [t for t in times if t is not None]
            if valid_times:
                ax2.bar(x + i*width, times, width, label=db.title(), color=colors[i], alpha=0.7)

        ax2.set_xlabel('Query Type')
        ax2.set_ylabel('Time (seconds)')
        ax2.set_title('Query Performance Comparison')
        ax2.set_xticks(x + width/2)
        ax2.set_xticklabels(query_labels)
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis='y')
        ax2.set_ylim(bottom=0)

        # Add value labels
        for i, db in enumerate(databases):
            for j, time_val in enumerate([query_times[q][db] for q in queries]):
                if time_val is not None:
                    ax2.text(x[j] + i*width, time_val + max([t for sublist in db_data for t in sublist if t is not None])*0.02,
                            f'{time_val:.4f}', ha='center', va='bottom', fontweight='bold')

    else:
        ax2.text(0.5, 0.5, 'No data available',
                transform=ax2.transAxes, ha='center', va='center',
                fontsize=12, color='gray')

    plt.tight_layout()
    agg_plot_file = os.path.join(plots_dir, f'{scale}_aggregated_performance_time.png' if scale else 'aggregated_performance_time.png')
    plt.savefig(agg_plot_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"Aggregated time performance plot saved to: {agg_plot_file}")

    # Generate aggregated plot (all queries in one chart) - TPS
    fig3, ax3 = plt.subplots(figsize=(10, 6))
    fig3.suptitle('Aggregated Performance by Query Type - TPS', fontsize=16, fontweight='bold')

    db_tps_data = []
    for db in databases:
        tps_values = [query_tps[q][db] for q in queries]
        db_tps_data.append(tps_values)

    if any(any(t is not None for t in tps_values) for tps_values in db_tps_data):
        for i, db in enumerate(databases):
            tps_values = [query_tps[q][db] for q in queries]
            valid_tps = [t for t in tps_values if t is not None]
            if valid_tps:
                ax3.bar(x + i*width, tps_values, width, label=db.title(), color=colors[i], alpha=0.7)

        ax3.set_xlabel('Query Type')
        ax3.set_ylabel('Transactions Per Second')
        ax3.set_title('Query TPS Comparison')
        ax3.set_xticks(x + width/2)
        ax3.set_xticklabels(query_labels)
        ax3.legend()
        ax3.grid(True, alpha=0.3, axis='y')
        ax3.set_ylim(bottom=0)

        # Add value labels
        for i, db in enumerate(databases):
            for j, tps_val in enumerate([query_tps[q][db] for q in queries]):
                if tps_val is not None:
                    ax3.text(x[j] + i*width, tps_val + max([t for sublist in db_tps_data for t in sublist if t is not None])*0.02,
                            f'{tps_val:.2f}', ha='center', va='bottom', fontweight='bold')

    else:
        ax3.text(0.5, 0.5, 'No data available',
                transform=ax3.transAxes, ha='center', va='center',
                fontsize=12, color='gray')

    plt.tight_layout()
    agg_tps_plot_file = os.path.join(plots_dir, f'{scale}_aggregated_performance_tps.png' if scale else 'aggregated_performance_tps.png')
    plt.savefig(agg_tps_plot_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"Aggregated TPS performance plot saved to: {agg_tps_plot_file}")

    # Generate summary text file
    summary_file = os.path.join(plots_dir, f'{scale}_performance_summary.txt' if scale else 'performance_summary.txt')
    with open(summary_file, 'w') as f:
        f.write("# Performance Comparison Summary\n\n")

        for i, (query, label) in enumerate(zip(queries, query_labels)):
            f.write(f"Query {i+1}: {label}\n")

            for db in databases:
                time_seconds = query_times[query][db]
                tps = query_tps[query][db]
                if time_seconds is not None:
                    f.write(f"  {db.title()}: {time_seconds:.4f}s")
                    if tps is not None:
                        f.write(f" ({tps:.2f} TPS)")
                    f.write("\n")
                else:
                    f.write(f"  {db.title()}: N/A\n")

            f.write("\n")

        # Add total durations
        f.write("Total Test Duration:\n")
        for db in databases:
            if total_times[db] > 0:
                f.write(f"  {db.title()}: {total_times[db]:.4f}s\n")
            else:
                f.write(f"  {db.title()}: N/A\n")

        f.write("\n")

        # Add TPS summary
        f.write("TPS Summary (Average across queries):\n")
        for db in databases:
            total_tps = 0
            count = 0
            for query in queries:
                if query_tps[query][db] is not None:
                    total_tps += query_tps[query][db]
                    count += 1
            if count > 0:
                avg_tps = total_tps / count
                f.write(f"  {db.title()}: {avg_tps:.2f} TPS\n")
            else:
                f.write(f"  {db.title()}: N/A\n")

        f.write("\n")

    print(f"Summary text saved to: {summary_file}")

def main():
    # Get databases and scale from command line arguments or environment
    if len(sys.argv) > 1:
        databases = sys.argv[1:-1] if len(sys.argv) > 2 else sys.argv[1:]
        scale = sys.argv[-1] if len(sys.argv) > 2 else ''
    else:
        # Try to get from environment variable
        databases_env = os.environ.get('DATABASES', 'paradedb elasticsearch')
        databases = databases_env.split()
        scale = ''

    print(f"Generating plots for databases: {databases}, scale: {scale}")

    # Use current directory structure
    results_dir = 'results'
    plots_dir = 'plots'

    generate_plots(databases, results_dir, plots_dir, scale)

if __name__ == '__main__':
    main()