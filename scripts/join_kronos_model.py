"""Ghép lại model.safetensors của Kronos-base từ các part chia nhỏ.

File gốc 409MB vượt limit 100MB/file của GitHub nên repo chỉ giữ 7 part
(model.safetensors.part00..part06, mỗi part 58,466,287 B). Script này ghép
chúng lại thành file model.safetensors nguyên vẹn (bản gốc bị .gitignore).

Chạy: .venv/Scripts/python.exe scripts/join_kronos_model.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "Kronos-base"
OUT = MODEL_DIR / "model.safetensors"
EXPECTED_SIZE = 409_264_008  # kích thước gốc trên HuggingFace


def main() -> None:
    parts = sorted(MODEL_DIR.glob("model.safetensors.part*"))
    if not parts:
        raise SystemExit(f"Không thấy part nào trong {MODEL_DIR}")
    if OUT.exists() and OUT.stat().st_size == EXPECTED_SIZE:
        print("model.safetensors đã tồn tại đủ dung lượng — bỏ qua (xoá tay để ghép lại).")
        return
    h = hashlib.sha256()
    with open(OUT, "wb") as w:
        for p in parts:
            data = p.read_bytes()
            w.write(data)
            h.update(data)
            print(f"ghep {p.name}: {len(data):,} B")
    size = OUT.stat().st_size
    if size != EXPECTED_SIZE:
        raise SystemExit(f"Kích thước sau ghép {size:,} != {EXPECTED_SIZE:,} — part thiếu/corrup!")
    print(f"OK: {size:,} B, sha256={h.hexdigest()}")


if __name__ == "__main__":
    main()
