#!/usr/bin/env python3
"""
AI Coding Tools Comparison Matrix
Scores 5 AI tools on 10 dimensions (1-10 scale)

Tools: Claude Code, Cursor AI, GitHub Copilot, Manus AI, OpenClaw
Dimensions: Code Quality, Speed, Context, Multi-file Editing, Autonomy, 
            Pricing, IDE Integration, Learning Curve, Enterprise, Community

Author: AI Research Analysis
Date: 2025
"""

from tabulate import tabulate

# AI Tools Scoring Matrix
# 5 Tools x 10 Dimensions (1-10 scale)

tools = {
    "Claude Code": {
        "Code Quality": 9,
        "Speed/Latency": 7,
        "Context Understanding": 9,
        "Multi-file Editing": 8,
        "Agent Autonomy": 8,
        "Pricing Value": 7,
        "IDE Integration": 7,
        "Learning Curve": 6,
        "Enterprise Features": 6,
        "Community/Ecosystem": 7,
    },
    "Cursor AI": {
        "Code Quality": 9,
        "Speed/Latency": 8,
        "Context Understanding": 8,
        "Multi-file Editing": 9,
        "Agent Autonomy": 9,
        "Pricing Value": 5,  # Controversial usage-based pricing
        "IDE Integration": 10,  # Native AI editor
        "Learning Curve": 8,
        "Enterprise Features": 8,
        "Community/Ecosystem": 8,
    },
    "GitHub Copilot": {
        "Code Quality": 8,
        "Speed/Latency": 9,
        "Context Understanding": 7,
        "Multi-file Editing": 6,
        "Agent Autonomy": 5,
        "Pricing Value": 8,
        "IDE Integration": 9,
        "Learning Curve": 9,
        "Enterprise Features": 9,
        "Community/Ecosystem": 10,
    },
    "Manus AI": {
        "Code Quality": 7,
        "Speed/Latency": 6,
        "Context Understanding": 8,
        "Multi-file Editing": 7,
        "Agent Autonomy": 10,  # Most autonomous
        "Pricing Value": 6,
        "IDE Integration": 4,
        "Learning Curve": 5,
        "Enterprise Features": 7,
        "Community/Ecosystem": 5,
    },
    "OpenClaw": {
        "Code Quality": 7,
        "Speed/Latency": 7,
        "Context Understanding": 8,
        "Multi-file Editing": 6,
        "Agent Autonomy": 8,
        "Pricing Value": 10,  # Free/open source
        "IDE Integration": 5,
        "Learning Curve": 4,  # Requires setup
        "Enterprise Features": 4,
        "Community/Ecosystem": 9,  # 227k stars
    },
}


def calculate_scores(tools_dict):
    """Calculate total and average scores for each tool."""
    results = []
    for tool, scores in tools_dict.items():
        total = sum(scores.values())
        avg = round(total / len(scores), 2)
        row = [tool] + list(scores.values()) + [total, avg]
        results.append(row)
    return results


def print_comparison_table(table_data, headers):
    """Print formatted comparison table."""
    print("=" * 120)
    print("AI CODING TOOLS COMPARISON MATRIX (5 Tools x 10 Dimensions)")
    print("=" * 120)
    print()
    print(tabulate(table_data, headers=headers, tablefmt='grid', stralign='center'))
    print()


def print_rankings(table_data):
    """Print tool rankings by total score."""
    print("RANKINGS BY TOTAL SCORE:")
    print("-" * 60)
    for i, row in enumerate(table_data, 1):
        print(f"  {i}. {row[0]:<15} | Total: {row[-2]} | Avg: {row[-1]}")
    print()


def print_dimension_winners(tools_dict, table_data):
    """Print highest scorer for each dimension."""
    print("DIMENSION WINNERS (Highest Score Per Category):")
    print("-" * 60)
    dimensions = list(tools_dict["Claude Code"].keys())
    for i, dim in enumerate(dimensions):
        max_score = max(row[i+1] for row in table_data)
        winners = [row[0] for row in table_data if row[i+1] == max_score]
        print(f"  {dim:<22} -> {', '.join(winners)} ({max_score}/10)")
    print()


def print_analysis_notes():
    """Print analysis insights."""
    print("=" * 120)
    print("ANALYSIS NOTES:")
    print("-" * 60)
    print("* Cursor AI leads due to superior IDE integration and agent capabilities")
    print("* GitHub Copilot dominates in ecosystem and enterprise readiness")
    print("* OpenClaw wins on pricing (free) but has setup complexity")
    print("* Manus AI excels at autonomy but weaker as pure coding tool")
    print("* Claude Code offers excellent code quality but limited to CLI")
    print("=" * 120)


def main():
    """Main execution function."""
    # Calculate scores
    table_data = calculate_scores(tools)
    
    # Sort by total score (descending)
    table_data.sort(key=lambda x: x[-2], reverse=True)
    
    # Define headers
    headers = ["Tool"] + list(tools["Claude Code"].keys()) + ["TOTAL", "AVG"]
    
    # Print results
    print_comparison_table(table_data, headers)
    print_rankings(table_data)
    print_dimension_winners(tools, table_data)
    print_analysis_notes()


if __name__ == "__main__":
    main()
