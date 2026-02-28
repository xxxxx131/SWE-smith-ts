#!/usr/bin/env python
"""
Evaluate assistant-token next-token accuracy on an OpenAI-chat JSONL dataset.

Metric:
    teacher-forcing top-1 token accuracy over assistant turns only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

def _to_token_list(token_ids: Any) -> list[int]:
    if hasattr(token_ids, "tolist"):
        token_ids = token_ids.tolist()
    if token_ids and isinstance(token_ids[0], list):
        token_ids = token_ids[0]
    return list(token_ids)


def build_ids_and_assistant_mask(
    tokenizer, messages: list[dict[str, Any]], max_seq_len: int
) -> tuple[list[int], list[int]]:
    full_ids = _to_token_list(
        tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
        )
    )
    assistant_mask = [0] * len(full_ids)

    prev_ids: list[int] = []
    for i, msg in enumerate(messages):
        cur_ids = _to_token_list(
            tokenizer.apply_chat_template(
                messages[: i + 1],
                tokenize=True,
                add_generation_prompt=False,
            )
        )
        start = min(len(prev_ids), len(full_ids))
        end = min(len(cur_ids), len(full_ids))
        if msg.get("role") == "assistant" and end > start:
            for j in range(start, end):
                assistant_mask[j] = 1
        prev_ids = cur_ids

    if len(full_ids) > max_seq_len:
        full_ids = full_ids[:max_seq_len]
        assistant_mask = assistant_mask[:max_seq_len]

    return full_ids, assistant_mask


def eval_one_sequence_chunked(
    model,
    device,
    token_ids: list[int],
    assistant_mask: list[int],
    chunk_size: int,
) -> tuple[int, int]:
    import torch

    if len(token_ids) < 2:
        return 0, 0

    correct = 0
    total = 0
    past_key_values = None
    seq_len = len(token_ids)

    for start in range(0, seq_len - 1, chunk_size):
        stop = min(start + chunk_size, seq_len - 1)
        x = torch.tensor([token_ids[start:stop]], dtype=torch.long, device=device)
        y = torch.tensor(token_ids[start + 1 : stop + 1], dtype=torch.long, device=device)
        m = torch.tensor(
            assistant_mask[start + 1 : stop + 1], dtype=torch.bool, device=device
        )

        out = model(input_ids=x, past_key_values=past_key_values, use_cache=True)
        past_key_values = out.past_key_values
        pred = torch.argmax(out.logits[0], dim=-1)

        if m.any():
            correct += int((pred[m] == y[m]).sum().item())
            total += int(m.sum().item())

        del x, y, m, out, pred

    return correct, total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate assistant-token teacher-forcing accuracy for chat JSONL."
    )
    parser.add_argument("--model_path", type=str, required=True)
    parser.add_argument("--data_file", type=Path, required=True)
    parser.add_argument("--max_seq_len", type=int, default=32768)
    parser.add_argument("--chunk_size", type=int, default=2048)
    parser.add_argument("--sample_limit", type=int, default=0)
    parser.add_argument("--dtype", choices=["bf16", "fp16", "fp32"], default="bf16")
    parser.add_argument("--output_json", type=Path, default=None)
    args = parser.parse_args()

    if not args.data_file.exists():
        raise FileNotFoundError(f"data file not found: {args.data_file}")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if args.dtype == "bf16":
        torch_dtype = torch.bfloat16
    elif args.dtype == "fp16":
        torch_dtype = torch.float16
    else:
        torch_dtype = torch.float32

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this evaluation script.")

    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        torch_dtype=torch_dtype,
        trust_remote_code=True,
        device_map="auto",
    )
    model.eval()
    device = next(model.parameters()).device

    records = []
    with args.data_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if args.sample_limit > 0:
        records = records[: args.sample_limit]

    total_correct = 0
    total_tokens = 0
    skipped = 0

    for i, rec in enumerate(records, start=1):
        messages = rec.get("messages")
        if not isinstance(messages, list) or not messages:
            skipped += 1
            continue

        token_ids, assistant_mask = build_ids_and_assistant_mask(
            tokenizer, messages, args.max_seq_len
        )
        c, t = eval_one_sequence_chunked(
            model=model,
            device=device,
            token_ids=token_ids,
            assistant_mask=assistant_mask,
            chunk_size=args.chunk_size,
        )
        if t == 0:
            skipped += 1
        total_correct += c
        total_tokens += t

        running_acc = (total_correct / total_tokens) if total_tokens > 0 else 0.0
        print(
            f"[{i}/{len(records)}] sample_tokens={t} running_acc={running_acc:.6f}",
            flush=True,
        )

        if i % 5 == 0:
            torch.cuda.empty_cache()

    accuracy = (total_correct / total_tokens) if total_tokens > 0 else 0.0
    result = {
        "model_path": args.model_path,
        "data_file": str(args.data_file),
        "num_samples": len(records),
        "skipped_samples": skipped,
        "assistant_tokens": total_tokens,
        "correct_tokens": total_correct,
        "assistant_token_accuracy": accuracy,
        "max_seq_len": args.max_seq_len,
        "chunk_size": args.chunk_size,
        "dtype": args.dtype,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output_json is not None:
        args.output_json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"saved: {args.output_json}")


if __name__ == "__main__":
    main()
