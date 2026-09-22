# models/ — Kronos (HuggingFace)

Model Kronos (NeoQuasar) dùng cho dự đoán kline, tải từ HuggingFace 2026-09-22 theo yêu cầu user.

| Thư mục | Repo HF | Files | Giữ local | Trên git |
|---|---|---|---|---|
| `Kronos-Tokenizer-base/` | [NeoQuasar/Kronos-Tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base) | config.json + model.safetensors (15,842,368 B) | model.safetensors | config.json + model.safetensors (nguyên vẹn, 15.8MB < 100MB) |
| `Kronos-base/` | [NeoQuasar/Kronos-base](https://huggingface.co/NeoQuasar/Kronos-base) | config.json + model.safetensors (409,264,008 B) | model.safetensors | config.json + 7 part (`model.safetensors.part00..06`, mỗi part 58,466,287 B) |

## Ghép lại model Kronos-base sau khi clone

`model.safetensors` gốc (409MB) vượt limit 100MB/file của GitHub nên bị `.gitignore` —
chỉ các part được push. Ghép lại bằng script:

```bash
.venv/Scripts/python.exe scripts/join_kronos_model.py
```

Script verify kích thước cuối đúng 409,264,008 B (thiếu part sẽ báo lỗi thay vì ghép sai).

## Cập nhật khi tải phiên bản HF mới

Xoá các part cũ trước khi chia lại (số part / kích thước part có thể khác):

```bash
rm models/Kronos-base/model.safetensors.part*
```
