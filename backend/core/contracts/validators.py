"""
Contract Validators - 契約検証とログ分析

Depth契約の検証、ログからのプログレス検出、
契約遵守率の分析を行うモジュール。
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .depth_contracts import Depth0Contract, Depth1Contract, ValidationResult


class ContractValidator:
    """契約検証とログ分析を行うクラス"""

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: データベースパス（指定しない場合はdata/nia.sqlite3を使用）
        """
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent.parent / "data" / "nia.sqlite3")
        self.db_path = db_path

    def validate_depth0_output(self, output: str) -> ValidationResult:
        """Depth0出力を検証"""
        return Depth0Contract.validate(output)

    def validate_depth1_output(self, output: str) -> ValidationResult:
        """Depth1出力を検証"""
        return Depth1Contract.validate(output)

    def validate_by_depth(self, depth: int, output: str) -> ValidationResult:
        """
        深度に応じた検証を実行

        Args:
            depth: 深度（0 or 1）
            output: 検証対象の出力

        Returns:
            ValidationResult: 検証結果
        """
        if depth == 0:
            return self.validate_depth0_output(output)
        elif depth == 1:
            return self.validate_depth1_output(output)
        else:
            result = ValidationResult(is_valid=False)
            result.add_violation(f"未対応の深度: {depth}", severity=1.0)
            return result

    def analyze_recent_outputs(
        self,
        thread_id: str = "default_thread",
        limit: int = 100
    ) -> Dict[str, any]:
        """
        最近の出力を分析し、契約遵守状況を集計

        Args:
            thread_id: スレッドID
            limit: 分析する最新メッセージ数

        Returns:
            Dict: 分析結果（遵守率、違反パターンなど）
        """
        analysis = {
            "total_messages": 0,
            "depth0_count": 0,
            "depth1_count": 0,
            "depth0_compliance_rate": 0.0,
            "depth1_compliance_rate": 0.0,
            "common_violations": [],
            "improvement_trend": None,
        }

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Depth0の出力を取得（inner_monologueから）
            query = """
            SELECT created_at, text
            FROM messages
            WHERE thread_id = ?
              AND role = 'assistant'
              AND text LIKE '%[PONDERING]%'
            ORDER BY created_at DESC
            LIMIT ?
            """
            cursor.execute(query, (thread_id, limit))
            depth0_results = cursor.fetchall()

            depth0_scores = []
            depth0_violations = []

            for created_at, text in depth0_results:
                # [PONDERING] タグの後のテキストを抽出
                if "[PONDERING]" in text:
                    pondering_text = text.split("[PONDERING]", 1)[1].strip()
                    result = self.validate_depth0_output(pondering_text)
                    depth0_scores.append(result.score)
                    depth0_violations.extend(result.violations)
                    analysis["depth0_count"] += 1

            # Depth1の出力を取得（詳細な分析が必要な場合）
            # ここでは簡易的に、長い出力をDepth1と仮定
            query = """
            SELECT created_at, text
            FROM messages
            WHERE thread_id = ?
              AND role = 'assistant'
              AND LENGTH(text) > 200
              AND text NOT LIKE '%[PONDERING]%'
            ORDER BY created_at DESC
            LIMIT ?
            """
            cursor.execute(query, (thread_id, limit // 2))
            depth1_results = cursor.fetchall()

            depth1_scores = []
            depth1_violations = []

            for created_at, text in depth1_results:
                result = self.validate_depth1_output(text)
                depth1_scores.append(result.score)
                depth1_violations.extend(result.violations)
                analysis["depth1_count"] += 1

            conn.close()

            # 遵守率の計算
            if depth0_scores:
                analysis["depth0_compliance_rate"] = sum(depth0_scores) / len(depth0_scores)
            if depth1_scores:
                analysis["depth1_compliance_rate"] = sum(depth1_scores) / len(depth1_scores)

            # よくある違反パターンの抽出
            all_violations = depth0_violations + depth1_violations
            violation_counts = {}
            for v in all_violations:
                # 違反メッセージから主要な部分を抽出
                key = v.split("（")[0] if "（" in v else v.split("(")[0]
                violation_counts[key] = violation_counts.get(key, 0) + 1

            # 頻度順にソート
            analysis["common_violations"] = sorted(
                violation_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]  # 上位5つ

            analysis["total_messages"] = len(depth0_results) + len(depth1_results)

        except Exception as e:
            analysis["error"] = str(e)

        return analysis

    def detect_progress(
        self,
        thread_id: str = "default_thread",
        window_size: int = 50
    ) -> Dict[str, any]:
        """
        プログレス検出 - 契約遵守率の改善トレンドを分析

        Args:
            thread_id: スレッドID
            window_size: 分析ウィンドウサイズ

        Returns:
            Dict: プログレス情報（改善率、トレンドなど）
        """
        progress = {
            "is_improving": False,
            "early_compliance_rate": 0.0,
            "recent_compliance_rate": 0.0,
            "improvement_percentage": 0.0,
            "trend": "stable",
        }

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 全期間のメッセージを取得
            query = """
            SELECT created_at, text, role
            FROM messages
            WHERE thread_id = ?
              AND role = 'assistant'
            ORDER BY created_at ASC
            """
            cursor.execute(query, (thread_id,))
            all_messages = cursor.fetchall()
            conn.close()

            if len(all_messages) < window_size * 2:
                progress["error"] = "データ不足（最低でも100メッセージ必要）"
                return progress

            # 初期ウィンドウ（最初のwindow_size件）
            early_messages = all_messages[:window_size]
            early_scores = []
            for created_at, text, role in early_messages:
                # Depth0とDepth1を簡易的に判定
                if "[PONDERING]" in text:
                    pondering_text = text.split("[PONDERING]", 1)[1].strip()
                    result = self.validate_depth0_output(pondering_text)
                    early_scores.append(result.score)
                elif len(text) > 200:
                    result = self.validate_depth1_output(text)
                    early_scores.append(result.score)

            # 最近のウィンドウ（最後のwindow_size件）
            recent_messages = all_messages[-window_size:]
            recent_scores = []
            for created_at, text, role in recent_messages:
                if "[PONDERING]" in text:
                    pondering_text = text.split("[PONDERING]", 1)[1].strip()
                    result = self.validate_depth0_output(pondering_text)
                    recent_scores.append(result.score)
                elif len(text) > 200:
                    result = self.validate_depth1_output(text)
                    recent_scores.append(result.score)

            # 平均スコアの計算
            if early_scores:
                progress["early_compliance_rate"] = sum(early_scores) / len(early_scores)
            if recent_scores:
                progress["recent_compliance_rate"] = sum(recent_scores) / len(recent_scores)

            # 改善率の計算
            if progress["early_compliance_rate"] > 0:
                improvement = (
                    progress["recent_compliance_rate"] - progress["early_compliance_rate"]
                )
                progress["improvement_percentage"] = (
                    improvement / progress["early_compliance_rate"] * 100
                )
                progress["is_improving"] = improvement > 0.05  # 5%以上の改善

                # トレンド判定
                if improvement > 0.1:
                    progress["trend"] = "improving"
                elif improvement < -0.1:
                    progress["trend"] = "declining"
                else:
                    progress["trend"] = "stable"

        except Exception as e:
            progress["error"] = str(e)

        return progress

    def generate_compliance_report(
        self,
        thread_id: str = "default_thread"
    ) -> str:
        """
        契約遵守レポートを生成

        Args:
            thread_id: スレッドID

        Returns:
            str: フォーマットされたレポート
        """
        analysis = self.analyze_recent_outputs(thread_id=thread_id)
        progress = self.detect_progress(thread_id=thread_id)

        report = f"""
=================================
📊 Depth Contract Compliance Report
=================================

Thread ID: {thread_id}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

--- 📈 Overall Compliance ---
Total Messages Analyzed: {analysis['total_messages']}
  - Depth0 Count: {analysis['depth0_count']}
  - Depth1 Count: {analysis['depth1_count']}

Compliance Rates:
  - Depth0: {analysis['depth0_compliance_rate']:.1%}
  - Depth1: {analysis['depth1_compliance_rate']:.1%}

--- 🔍 Common Violations ---
"""
        for i, (violation, count) in enumerate(analysis.get('common_violations', []), 1):
            report += f"{i}. {violation}: {count}件\n"

        report += f"""
--- 📊 Progress Trend ---
Early Compliance Rate: {progress['early_compliance_rate']:.1%}
Recent Compliance Rate: {progress['recent_compliance_rate']:.1%}
Improvement: {progress['improvement_percentage']:+.1f}%
Trend: {progress['trend'].upper()}
Is Improving: {"✅ Yes" if progress['is_improving'] else "⚠️ No"}

=================================
"""
        return report
