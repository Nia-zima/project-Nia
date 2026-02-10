#!/usr/bin/env python3
"""
契約遵守レポートを生成するスクリプト

Phase 0: Depth Contracts の遵守状況を分析し、
改善のための洞察を提供します。

使用例:
    python scripts/contract_compliance_report.py
    python scripts/contract_compliance_report.py --thread-id my_thread
    python scripts/contract_compliance_report.py --limit 200
"""

import argparse
import sys
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.core.contracts import ContractValidator


def main():
    parser = argparse.ArgumentParser(
        description="Depth Contracts の遵守レポートを生成"
    )
    parser.add_argument(
        "--thread-id",
        default="default_thread",
        help="分析するスレッドID（デフォルト: default_thread）"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="分析する最新メッセージ数（デフォルト: 100）"
    )
    parser.add_argument(
        "--db-path",
        help="データベースパス（デフォルト: data/nia.sqlite3）"
    )

    args = parser.parse_args()

    # Validatorの初期化
    validator = ContractValidator(db_path=args.db_path)

    print("=" * 70)
    print("📊 Depth Contract Compliance Report Generator")
    print("=" * 70)
    print()
    print(f"Thread ID: {args.thread_id}")
    print(f"Analysis Limit: {args.limit} messages")
    print()

    # レポート生成
    print("🔄 Analyzing recent outputs...")
    print()

    report = validator.generate_compliance_report(thread_id=args.thread_id)
    print(report)

    # 詳細分析
    print()
    print("=" * 70)
    print("📈 Detailed Analysis")
    print("=" * 70)
    print()

    analysis = validator.analyze_recent_outputs(
        thread_id=args.thread_id,
        limit=args.limit
    )

    if "error" in analysis:
        print(f"⚠️ Error: {analysis['error']}")
        return

    print(f"Total Messages: {analysis['total_messages']}")
    print(f"  - Depth0: {analysis['depth0_count']}")
    print(f"  - Depth1: {analysis['depth1_count']}")
    print()

    print(f"Compliance Rates:")
    print(f"  - Depth0: {analysis['depth0_compliance_rate']:.1%}")
    print(f"  - Depth1: {analysis['depth1_compliance_rate']:.1%}")
    print()

    if analysis['common_violations']:
        print("Most Common Violations:")
        for i, (violation, count) in enumerate(analysis['common_violations'], 1):
            print(f"  {i}. {violation}: {count}件")
        print()

    # プログレス分析
    print("=" * 70)
    print("📊 Progress Trend Analysis")
    print("=" * 70)
    print()

    progress = validator.detect_progress(thread_id=args.thread_id)

    if "error" in progress:
        print(f"⚠️ Error: {progress['error']}")
    else:
        print(f"Early Compliance: {progress['early_compliance_rate']:.1%}")
        print(f"Recent Compliance: {progress['recent_compliance_rate']:.1%}")
        print(f"Improvement: {progress['improvement_percentage']:+.1f}%")
        print(f"Trend: {progress['trend'].upper()}")
        print(f"Is Improving: {'✅ Yes' if progress['is_improving'] else '⚠️ No'}")
        print()

    # 推奨事項
    print("=" * 70)
    print("💡 Recommendations")
    print("=" * 70)
    print()

    if analysis['depth0_compliance_rate'] < 0.7:
        print("⚠️ Depth0 遵守率が低いです。以下を確認してください:")
        print("  - 結論的な表現を避ける")
        print("  - 不確実性を明示する（「わからない」「不明」など）")
        print("  - 思考の断片を示す")
        print()

    if analysis['depth1_compliance_rate'] < 0.7:
        print("⚠️ Depth1 遵守率が低いです。以下を確認してください:")
        print("  - 質問を明示する")
        print("  - 既知/未知の情報を整理する")
        print("  - 推論チェーンを示す")
        print("  - 複数の選択肢を提示する")
        print()

    if progress.get('trend') == 'declining':
        print("📉 契約遵守率が低下しています。")
        print("  - システムプロンプトを見直す")
        print("  - フィードバックループを強化する")
        print()
    elif progress.get('trend') == 'improving':
        print("✅ 契約遵守率が向上しています！")
        print("  - 現在のアプローチを継続")
        print()

    print("=" * 70)
    print("✨ Report Complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
