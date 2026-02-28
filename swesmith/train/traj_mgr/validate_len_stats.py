"""
Validate that a length-stats manifest matches a target SFT jsonl dataset.

Usage:
python -m swesmith.train.traj_mgr.validate_len_stats \
    --data_file trajectories_sft/xxx.jsonl \
    --stats_file trajectories_sft/.len_stats_32k.json \
    --max_seq_len 32768
"""

import argparse
import json
from pathlib import Path


def _count_non_empty_lines(path: Path) -> int:
    cnt = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cnt += 1
    return cnt


def main(data_file: Path, stats_file: Path, max_seq_len: int) -> None:
    if not data_file.exists():
        raise FileNotFoundError(f"Data file not found: {data_file}")
    if not stats_file.exists():
        raise FileNotFoundError(f"Stats file not found: {stats_file}")

    stats = json.loads(stats_file.read_text(encoding="utf-8"))

    stats_data_file = stats.get("file")
    if not isinstance(stats_data_file, str):
        raise ValueError("Invalid stats file: missing string field `file`.")
    if str(data_file.resolve()) != str(Path(stats_data_file).resolve()):
        raise ValueError(
            "Stats file does not match target data file.\n"
            f"  stats.file = {Path(stats_data_file).resolve()}\n"
            f"  data_file   = {data_file.resolve()}"
        )

    stats_num_samples = stats.get("num_samples")
    if not isinstance(stats_num_samples, int):
        raise ValueError("Invalid stats file: missing int field `num_samples`.")

    actual_num_samples = _count_non_empty_lines(data_file)
    if stats_num_samples != actual_num_samples:
        raise ValueError(
            "Sample count mismatch between stats and data file.\n"
            f"  stats.num_samples = {stats_num_samples}\n"
            f"  data_file lines   = {actual_num_samples}"
        )

    gt_key = f"gt_{max_seq_len}"
    gt_cnt = stats.get(gt_key)
    if not isinstance(gt_cnt, int):
        raise ValueError(f"Invalid stats file: missing int field `{gt_key}`.")

    ratio = gt_cnt / actual_num_samples if actual_num_samples > 0 else 0.0
    print("[validate_len_stats] Validation passed.")
    print(f"[validate_len_stats] data_file={data_file}")
    print(f"[validate_len_stats] stats_file={stats_file}")
    print(
        f"[validate_len_stats] over_{max_seq_len}={gt_cnt}/{actual_num_samples} "
        f"({ratio:.2%})"
    )
    print(
        "[validate_len_stats] policy=keep_all_truncate "
        f"(training max_seq_len={max_seq_len})"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate SFT length stats manifest.")
    parser.add_argument(
        "--data_file",
        type=Path,
        required=True,
        help="Path to target SFT jsonl file.",
    )
    parser.add_argument(
        "--stats_file",
        type=Path,
        required=True,
        help="Path to .len_stats_32k.json manifest.",
    )
    parser.add_argument(
        "--max_seq_len",
        type=int,
        default=32768,
        help="Context length threshold used for reporting over-length ratio.",
    )
    args = parser.parse_args()
    main(**vars(args))
