# Icons — Lucide Only

**Nguồn duy nhất:** [Lucide Icons](https://lucide.dev). Mọi icon trong project phải lấy từ bộ Lucide.

## Rule

- **Luôn dùng Lucide.** Không dùng icon từ nguồn khác (Fluent, Material, custom SVG không xuất phát từ Lucide).
- **Thiếu thì tải:** Nếu cần icon chưa có trong repo → tải SVG từ Lucide, lưu vào đúng vị trí (xem dưới), rồi dùng.

## Cách tải khi thiếu

1. **Tìm tên icon:** Vào [lucide.dev/icons](https://lucide.dev/icons), tìm icon (tên Lucide dạng kebab-case, ví dụ `search`, `arrow-right`, `folder-open`).
2. **Tải SVG:** Dùng một trong hai:
   - **UNPKG (khuyến nghị):**  
     `https://unpkg.com/lucide-static@latest/files/icons/<tên-icon>.svg`  
     Ví dụ: `https://unpkg.com/lucide-static@latest/files/icons/info.svg`, `search.svg`, `folder-plus.svg`.
   - **GitHub:**  
     `https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/<tên-icon>.svg`
3. **Lưu file** vào đúng thư mục (xem **Vị trí lưu**). Tên file = tên Lucide + `.svg` (giữ kebab-case nếu Lucide dùng, ví dụ `arrow-right.svg`).

## Vị trí lưu

| Mục đích | Thư mục | Ghi chú |
|----------|---------|--------|
| Shelf / toolbar (Houdini) | `toolbar/icons/<tên>.svg` | Icon dùng trong `MonoFX.shelf` (toolbar). |
| Houdini user folder (installer) | `config/Icons/<tên>.svg` | Copy trùng bộ với `toolbar/icons/` để installer đưa vào `Documents\houdiniXX.X\monofx\config\Icons\`. |
| Tool cụ thể (chỉ tool đó dùng) | `tools/fx/<tên_tool>/icons/<tên>.svg` | Ví dụ: `tools/fx/split_geometry/icons/icon_select.svg` → nên đổi tên theo Lucide nếu có (vd. `mouse-pointer-click.svg`). |

**Khi thêm icon mới cho shelf:** Thêm vào **cả hai** `toolbar/icons/` và `config/Icons/` (cùng tên file) để shelf và installer đồng bộ.

## Đặt tên file

- **Chuẩn Lucide:** Tên file = tên icon trên lucide.dev, dạng kebab-case: `arrow-right.svg`, `folder-plus.svg`, `search.svg`.
- Shelf đang dùng tên đơn giản: `info`, `layers`, `palette`, `replace` — tương ứng Lucide cùng tên, giữ nguyên.

## Tùy biến (nền, scale) cho shelf

Một số icon trong shelf có thể được chỉnh cho Houdini (nền màu, scale 0.65). Nếu chỉnh:
- Giữ bản gốc Lucide trong repo hoặc ghi chú trong commit rằng đã chỉnh từ Lucide.
- Rule vẫn là **bắt đầu từ Lucide**; chỉnh chỉ là bước sau (style), không thay bằng icon nguồn khác.

## Tóm tắt

1. Chỉ dùng icon từ **Lucide**.
2. Thiếu → tải từ UNPKG hoặc GitHub (link trên), lưu vào `toolbar/icons/` (+ `config/Icons/` nếu dùng cho shelf).
3. Tên file = tên icon Lucide (kebab-case) + `.svg`.
