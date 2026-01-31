import pandas as pd
import matplotlib.pyplot as plt
import os
import sys

LOWER_IS_BETTER = ["CPU (%)", "Memory (%)", "Packet_in Delta", "Score"]
HIGHER_IS_BETTER = ["Throughput (Mbps)"]  # You can add more KPIs here later


def load_data_3ctrl(c1_file, c2_file, c3_file):
    """Load and normalize CSV data for 3 controllers."""
    files = [c1_file, c2_file, c3_file]
    for file in files:
        if not os.path.exists(file):
            print(f"Error: Missing file {file}")
            return None, None, None

    # Read the CSVs
    df_c1 = pd.read_csv(c1_file)
    df_c2 = pd.read_csv(c2_file)
    df_c3 = pd.read_csv(c3_file)

    # Normalize column names: strip spaces, lowercase
    for df in [df_c1, df_c2, df_c3]:
        df.columns = df.columns.str.strip().str.lower()

    # Ensure expected columns exist
    expected = {"timestamp", "cpu", "memory", "packet_in_delta", "score"}
    dataframes = [("c1", df_c1), ("c2", df_c2), ("c3", df_c3)]
    
    for name, df in dataframes:
        if not expected.issubset(df.columns):
            print(f"Error: Missing expected columns in {name}")
            print(f"Found in {name}:", df.columns.tolist())
            return None, None, None

    # Normalize time axis
    start_time = min(df_c1["timestamp"].min(), df_c2["timestamp"].min(), df_c3["timestamp"].min())
    df_c1["time"] = df_c1["timestamp"] - start_time
    df_c2["time"] = df_c2["timestamp"] - start_time
    df_c3["time"] = df_c3["timestamp"] - start_time

    return df_c1, df_c2, df_c3


def trim_to_common_window(dfs, warmup=10.0):
    """Trim all DataFrames to the same [warmup, common_end] window."""
    common_end = min(df["time"].max() for df in dfs)
    trimmed = []
    for df in dfs:
        d = df[(df["time"] >= warmup) & (df["time"] <= common_end)].copy()
        trimmed.append(d)
    return trimmed


def plot_time_series_3ctrl(df_noLB_c1, df_noLB_c2, df_noLB_c3, df_LB_c1, df_LB_c2, df_LB_c3, 
                          metric, ylabel, output_prefix):
    """Plot time series for 3-controller comparison."""
    plt.figure(figsize=(10, 6))

    # NoLB series
    # NoLB series (warm colors)
    plt.plot(df_noLB_c1["time"].to_numpy(), df_noLB_c1[metric].to_numpy(),
             label="NoLB - C1", color="tomato", linestyle="-", linewidth=1.8)
    plt.plot(df_noLB_c2["time"].to_numpy(), df_noLB_c2[metric].to_numpy(),
             label="NoLB - C2", color="darkorange", linestyle="-", linewidth=1.8)
    plt.plot(df_noLB_c3["time"].to_numpy(), df_noLB_c3[metric].to_numpy(),
             label="NoLB - C3", color="firebrick", linestyle="-", linewidth=1.8)

    # LB series (cool colors)
    plt.plot(df_LB_c1["time"].to_numpy(), df_LB_c1[metric].to_numpy(),
             label="LB - C1", color="royalblue", linestyle="--", linewidth=2.0)
    plt.plot(df_LB_c2["time"].to_numpy(), df_LB_c2[metric].to_numpy(),
             label="LB - C2", color="seagreen", linestyle="--", linewidth=2.0)
    plt.plot(df_LB_c3["time"].to_numpy(), df_LB_c3[metric].to_numpy(),
             label="LB - C3", color="purple", linestyle="--", linewidth=2.0)

    plt.xlabel("Time (s)", fontsize=12)
    plt.ylabel(ylabel, fontsize=12)
    plt.title(f"{ylabel} Over Time (3-Controller: NoLB vs LB)", fontsize=14, fontweight="bold")
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_{metric}_timeseries.png", dpi=300, bbox_inches='tight')
    plt.close()


def generate_kpi_table_3ctrl(df_c1, df_c2, df_c3, agg="mean"):
    """Generate KPI table for 3 controllers using mean or median."""
    func = getattr(pd.Series, agg)
    return pd.DataFrame({
        "CPU (%)": [func(df_c1["cpu"]), func(df_c2["cpu"]), func(df_c3["cpu"])],
        "Memory (%)": [func(df_c1["memory"]), func(df_c2["memory"]), func(df_c3["memory"])],
        "Packet_in Delta": [func(df_c1["packet_in_delta"]), func(df_c2["packet_in_delta"]), func(df_c3["packet_in_delta"])],
        "Score": [func(df_c1["score"]), func(df_c2["score"]), func(df_c3["score"])]
    }, index=["Controller 1", "Controller 2", "Controller 3"]).round(2)


def calculate_load_balance_metrics(table):
    """Calculate load distribution metrics."""
    metrics = {}
    for col in table.columns:
        values = table[col].values
        metrics[f"{col}_std"] = values.std().round(2)
        metrics[f"{col}_max_diff"] = (values.max() - values.min()).round(2)
        if values.mean() > 0:
            metrics[f"{col}_cv"] = (values.std() / values.mean()).round(3)
        else:
            metrics[f"{col}_cv"] = 0
    return metrics


def print_improvements_3ctrl(table_noLB, table_LB):
    """Print percentage improvements for 3-controller setup."""
    print("\n📈 Percentage Improvements:\n")
    for metric in table_noLB.columns:
        for ctrl in table_noLB.index:
            before = table_noLB.loc[ctrl, metric]
            after = table_LB.loc[ctrl, metric]
            if before == 0:
                change = 0
            elif metric in LOWER_IS_BETTER:
                change = ((before - after) / before) * 100
            elif metric in HIGHER_IS_BETTER:
                change = ((after - before) / before) * 100
            else:
                change = ((before - after) / before) * 100
            print(f"{metric} improvement ({ctrl}): {change:.2f}%")
    
    # Load balancing effectiveness
    print("\n📊 Load Balancing Effectiveness:\n")
    lb_noLB = calculate_load_balance_metrics(table_noLB)
    lb_LB = calculate_load_balance_metrics(table_LB)
    
    for key in lb_noLB.keys():
        if key.endswith('_std') or key.endswith('_max_diff') or key.endswith('_cv'):
            metric_name = key.replace('_std', '').replace('_max_diff', '').replace('_cv', '')
            suffix = key.split('_')[-1]
            improvement = ((lb_noLB[key] - lb_LB[key]) / lb_noLB[key]) * 100 if lb_noLB[key] > 0 else 0
            print(f"{metric_name} {suffix.upper()} improvement: {improvement:.2f}%")


def combine_tables_3ctrl(table_noLB, table_LB):
    """Combine NoLB and LB tables for 3 controllers."""
    combined = pd.DataFrame(index=table_noLB.index)
    for col in table_noLB.columns:
        combined[f"{col} (NoLB)"] = table_noLB[col]
        combined[f"{col} (LB)"] = table_LB[col]
    return combined


def plot_bar_charts_3ctrl(combined_table, output_prefix):
    """Plot bar charts for 3-controller comparison."""
    for metric in set(col.split(" (")[0] for col in combined_table.columns):
        col_nolb = [c for c in combined_table.columns if c.startswith(metric) and "(NoLB)" in c][0]
        col_lb   = [c for c in combined_table.columns if c.startswith(metric) and "(LB)" in c][0]

        values = combined_table[[col_nolb, col_lb]]

        ax = values.plot(kind="bar", rot=45, figsize=(8, 6),
                         color=["indianred", "royalblue"], edgecolor="black")

        plt.title(f"{metric} - NoLB vs LB (3 Controllers)", fontsize=14, fontweight="bold")
        plt.ylabel(metric, fontsize=12)
        plt.grid(True, axis="y", linestyle="--", alpha=0.6)

        for i, ctrl in enumerate(values.index):
            before = values.iloc[i, 0]
            after = values.iloc[i, 1]
            if before == 0:
                change = 0
            elif metric in LOWER_IS_BETTER:
                change = ((before - after) / before) * 100
            elif metric in HIGHER_IS_BETTER:
                change = ((after - before) / before) * 100
            else:
                change = ((before - after) / before) * 100

            ax.text(i + 0.20, after + (0.05 * after), f"{change:.1f}%",
                    ha='center', va='bottom', fontsize=9, fontweight='bold', color='darkblue')

        plt.tight_layout()
        plt.savefig(f"{output_prefix}_{metric}_barchart.png", dpi=300, bbox_inches='tight')
        plt.close()


def analyze_kpi_3ctrl(noLB_c1, noLB_c2, noLB_c3, LB_c1, LB_c2, LB_c3, 
                     output_prefix="comparison_3ctrl", agg="mean", warmup=10.0):
    """Main analysis function for 3-controller setup."""
    df_noLB_c1, df_noLB_c2, df_noLB_c3 = load_data_3ctrl(noLB_c1, noLB_c2, noLB_c3)
    df_LB_c1, df_LB_c2, df_LB_c3 = load_data_3ctrl(LB_c1, LB_c2, LB_c3)
    
    if any(x is None for x in (df_noLB_c1, df_noLB_c2, df_noLB_c3, df_LB_c1, df_LB_c2, df_LB_c3)):
        return

    # Align datasets to common time window
    df_noLB_c1, df_noLB_c2, df_noLB_c3, df_LB_c1, df_LB_c2, df_LB_c3 = trim_to_common_window(
        [df_noLB_c1, df_noLB_c2, df_noLB_c3, df_LB_c1, df_LB_c2, df_LB_c3], warmup=warmup
    )

    # Time series plots
    for metric, ylabel in [
        ("cpu", "CPU Usage (%)"),
        ("memory", "Memory Usage (%)"),
        ("score", "Load Score"),
        ("packet_in_delta", "Packet_in Delta")
    ]:
        plot_time_series_3ctrl(df_noLB_c1, df_noLB_c2, df_noLB_c3, 
                              df_LB_c1, df_LB_c2, df_LB_c3, metric, ylabel, output_prefix)
    print(f"✅ Time-series plots saved with prefix '{output_prefix}_*_timeseries.png'")

    # KPI tables
    table_noLB = generate_kpi_table_3ctrl(df_noLB_c1, df_noLB_c2, df_noLB_c3, agg=agg)
    table_LB = generate_kpi_table_3ctrl(df_LB_c1, df_LB_c2, df_LB_c3, agg=agg)
    combined_table = combine_tables_3ctrl(table_noLB, table_LB)

    # Save tables
    table_noLB.to_csv(f"{output_prefix}_kpi_table_noLB.csv")
    table_LB.to_csv(f"{output_prefix}_kpi_table_LB.csv")
    combined_table.to_csv(f"{output_prefix}_kpi_table_combined.csv")
    with open(f"{output_prefix}_kpi_table_combined.tex", "w") as f:
        f.write(combined_table.to_latex())

    print("\n📊 KPI Table - No Load Balancing:\n", table_noLB)
    print("\n📊 KPI Table - With Load Balancing:\n", table_LB)
    print("\n📊 Combined KPI Table:\n", combined_table)

    # Bar charts
    plot_bar_charts_3ctrl(combined_table, output_prefix)
    print(f"✅ Bar charts saved with prefix '{output_prefix}_*_barchart.png'")

    # Improvements
    print_improvements_3ctrl(table_noLB, table_LB)
    print(f"✅ Tables and charts saved with prefix '{output_prefix}_*'")


if __name__ == "__main__":
    if len(sys.argv) < 8:
        print("Usage: python3 analyze_kpi_3ctrl.py <noLB_c1.csv> <noLB_c2.csv> <noLB_c3.csv> <LB_c1.csv> <LB_c2.csv> <LB_c3.csv> <output_prefix> [agg] [warmup]")
    else:
        agg = sys.argv[8] if len(sys.argv) > 8 else "mean"
        warmup = float(sys.argv[9]) if len(sys.argv) > 9 else 10.0
        analyze_kpi_3ctrl(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], 
                         sys.argv[5], sys.argv[6], sys.argv[7], agg=agg, warmup=warmup)
