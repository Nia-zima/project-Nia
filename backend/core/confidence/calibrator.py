"""
Confidence Calibrator - 確信度キャリブレーション

Expected Calibration Error (ECE) を使用して、
確信度と実際の正解率のズレを補正します。
"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Tuple, Optional
import json

logger = logging.getLogger(__name__)


class ConfidenceCalibrator:
    """
    確信度キャリブレータ

    ECE (Expected Calibration Error) を使用して、
    モデルの確信度を実際の正解率に合わせて補正します。

    キャリブレーション手法:
    1. 確信度を複数のビン（例: [0-0.1, 0.1-0.2, ...）に分割
    2. 各ビンの平均確信度と実際の正解率を計算
    3. ズレを補正するマッピング関数を学習
    """

    def __init__(
        self,
        num_bins: int = 10,
        calibration_data: Optional[List[Tuple[float, bool]]] = None,
    ):
        """
        Args:
            num_bins: 確信度を分割するビンの数
            calibration_data: キャリブレーションデータ（確信度, 正解フラグ）のリスト
        """
        self.num_bins = num_bins
        self.bin_boundaries = [i / num_bins for i in range(num_bins + 1)]
        self.calibration_map = {}  # 確信度 → 補正後の確信度

        if calibration_data:
            self.fit(calibration_data)

    def fit(self, data: List[Tuple[float, bool]]):
        """
        キャリブレーションデータから補正マップを学習

        Args:
            data: (確信度, 正解フラグ) のリスト
        """
        if not data:
            logger.warning("[CALIBRATOR] No data provided for calibration")
            return

        # ビンごとにデータを分割
        bins = [[] for _ in range(self.num_bins)]

        for confidence, is_correct in data:
            bin_idx = self._get_bin_index(confidence)
            bins[bin_idx].append(is_correct)

        # 各ビンの実際の正解率を計算
        for i, bin_data in enumerate(bins):
            if not bin_data:
                # データがないビンは補正なし
                mid_point = (self.bin_boundaries[i] + self.bin_boundaries[i + 1]) / 2
                self.calibration_map[mid_point] = mid_point
            else:
                # ビンの中央値を確信度、正解率を補正後の確信度とする
                mid_point = (self.bin_boundaries[i] + self.bin_boundaries[i + 1]) / 2
                accuracy = sum(bin_data) / len(bin_data)
                self.calibration_map[mid_point] = accuracy

        logger.info(
            "[CALIBRATOR] Fitted with %d samples. ECE: %.4f",
            len(data),
            self.calculate_ece(data)
        )

    def calibrate(self, raw_confidence: float) -> float:
        """
        確信度を補正

        Args:
            raw_confidence: 生の確信度 (0.0 - 1.0)

        Returns:
            float: 補正後の確信度 (0.0 - 1.0)
        """
        if not self.calibration_map:
            # キャリブレーションされていない場合はそのまま返す
            return raw_confidence

        # 最も近いビンの補正値を使用（線形補間）
        bin_idx = self._get_bin_index(raw_confidence)
        lower_mid = (self.bin_boundaries[bin_idx] + self.bin_boundaries[bin_idx + 1]) / 2
        lower_calibrated = self.calibration_map.get(lower_mid, raw_confidence)

        # 隣のビンとの間で線形補間
        if bin_idx < self.num_bins - 1:
            upper_mid = (self.bin_boundaries[bin_idx + 1] + self.bin_boundaries[bin_idx + 2]) / 2
            upper_calibrated = self.calibration_map.get(upper_mid, raw_confidence)

            # 線形補間
            alpha = (raw_confidence - lower_mid) / (upper_mid - lower_mid) if upper_mid != lower_mid else 0
            calibrated = lower_calibrated + alpha * (upper_calibrated - lower_calibrated)
        else:
            calibrated = lower_calibrated

        # 0.0 - 1.0 にクランプ
        return max(0.0, min(1.0, calibrated))

    def calculate_ece(self, data: List[Tuple[float, bool]]) -> float:
        """
        Expected Calibration Error (ECE) を計算

        Args:
            data: (確信度, 正解フラグ) のリスト

        Returns:
            float: ECE値（低いほど良い）
        """
        if not data:
            return 0.0

        # ビンごとにデータを分割
        bins = [[] for _ in range(self.num_bins)]
        bin_confidences = [[] for _ in range(self.num_bins)]

        for confidence, is_correct in data:
            bin_idx = self._get_bin_index(confidence)
            bins[bin_idx].append(is_correct)
            bin_confidences[bin_idx].append(confidence)

        # ECEの計算
        total_samples = len(data)
        ece = 0.0

        for i, bin_data in enumerate(bins):
            if not bin_data:
                continue

            # ビンのサイズ
            bin_size = len(bin_data)

            # 平均確信度
            avg_confidence = sum(bin_confidences[i]) / bin_size

            # 実際の正解率
            accuracy = sum(bin_data) / bin_size

            # 重み付きでECEに加算
            ece += (bin_size / total_samples) * abs(avg_confidence - accuracy)

        return ece

    def _get_bin_index(self, confidence: float) -> int:
        """
        確信度が属するビンのインデックスを取得

        Args:
            confidence: 確信度 (0.0 - 1.0)

        Returns:
            int: ビンのインデックス (0 - num_bins-1)
        """
        for i in range(self.num_bins):
            if self.bin_boundaries[i] <= confidence < self.bin_boundaries[i + 1]:
                return i

        # 1.0 の場合は最後のビン
        return self.num_bins - 1

    def save_to_db(self, db_path: str, calibrator_id: str = "default"):
        """
        キャリブレーションマップをデータベースに保存

        Args:
            db_path: データベースパス
            calibrator_id: キャリブレータID
        """
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS confidence_calibration (
                calibrator_id TEXT PRIMARY KEY,
                num_bins INTEGER,
                calibration_map TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # データ挿入（または更新）
        calibration_map_json = json.dumps(self.calibration_map)
        cursor.execute("""
            INSERT OR REPLACE INTO confidence_calibration
            (calibrator_id, num_bins, calibration_map)
            VALUES (?, ?, ?)
        """, (calibrator_id, self.num_bins, calibration_map_json))

        conn.commit()
        conn.close()

        logger.info(
            "[CALIBRATOR] Saved to DB: %s (id=%s)",
            db_path,
            calibrator_id
        )

    @classmethod
    def load_from_db(
        cls,
        db_path: str,
        calibrator_id: str = "default"
    ) -> Optional['ConfidenceCalibrator']:
        """
        データベースからキャリブレータを読み込み

        Args:
            db_path: データベースパス
            calibrator_id: キャリブレータID

        Returns:
            ConfidenceCalibrator or None: 読み込んだキャリブレータ
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT num_bins, calibration_map
                FROM confidence_calibration
                WHERE calibrator_id = ?
            """, (calibrator_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                num_bins, calibration_map_json = row
                calibrator = cls(num_bins=num_bins)
                calibrator.calibration_map = json.loads(calibration_map_json)

                # キーを浮動小数点数に変換
                calibrator.calibration_map = {
                    float(k): v for k, v in calibrator.calibration_map.items()
                }

                logger.info(
                    "[CALIBRATOR] Loaded from DB: %s (id=%s)",
                    db_path,
                    calibrator_id
                )
                return calibrator
            else:
                logger.warning(
                    "[CALIBRATOR] Not found in DB: %s (id=%s)",
                    db_path,
                    calibrator_id
                )
                return None

        except Exception as e:
            logger.error("[CALIBRATOR] Failed to load from DB: %s", e)
            return None
