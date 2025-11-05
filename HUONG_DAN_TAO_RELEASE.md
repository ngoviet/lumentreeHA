# Hướng dẫn tạo GitHub Release v4.0.0

## ⚡ Cách nhanh nhất (2 phút)

1. **Click vào link này để tạo release:**
   https://github.com/ngoviet/lumentreeHA/releases/new

2. **Điền thông tin:**
   - **Choose a tag**: Chọn `v4.0.0` (hoặc tạo mới nếu chưa có)
   - **Release title**: `v4.0.0`
   - **Describe this release**: Copy toàn bộ nội dung từ file `RELEASE_NOTES_v4.0.0.md` và paste vào đây

3. **Click "Publish release"**

4. **Xong!** HACS sẽ tự động nhận version mới sau vài phút.

---

## 🔧 Cách dùng script (nếu muốn tự động)

Nếu bạn có GitHub Personal Access Token:

1. **Lấy token:**
   - Vào: https://github.com/settings/tokens
   - Click "Generate new token (classic)"
   - Chọn quyền: `repo` (tick vào checkbox "repo")
   - Click "Generate token"
   - Copy token

2. **Chạy script:**
   ```powershell
   .\create_release.ps1 -Token "your_token_here"
   ```

---

## ✅ Sau khi tạo release

1. Vào HACS → Integrations
2. Tìm "Lumentree Inverter"
3. Click vào integration → "Reload" hoặc "Update"
4. Version 4.0.0 sẽ xuất hiện!

