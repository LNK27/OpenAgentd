# Vault Recall v1 — Kế hoạch Triển khai Chi tiết (Bản Tối ưu Kiến trúc & Tiếng Việt v5)

Triển khai **Vault Recall** cho OpenAgentd, cung cấp khả năng tìm kiếm (`vault_search`) và đọc (`vault_read`) dữ liệu Obsidian Vault một cách hiệu quả, giảm thiểu tối đa rủi ro tranh chấp tài nguyên qua các controlled agent tools dành riêng cho lead agent.

---

## ⛔ Phân tích Phản biện & Quyết định Kiến trúc Cao cấp (Chốt cứng)

Để đạt hiệu năng và độ ổn định thực chiến, các quyết định kiến trúc cốt lõi dưới đây được thống nhất và tối ưu hóa từ phản biện của GPT-5.5:

### 1. Loại bỏ ngôn ngữ overconfident (Hyperboles)
* Toàn bộ các từ ngữ phi kỹ thuật hoặc cường điệu ("hoàn toàn", "rất nhanh", "100%", "hoàn hảo") được làm sạch triệt để khỏi file plan.
* Hệ thống vận hành theo tinh thần thực tế: **"best-effort cache + retry + deterministic fallback"**.

### 2. Thiết kế Dataclass `VaultNoteInfo` đầy đủ
Để đóng gói trọn vẹn dữ liệu định danh và nội dung của một note phục vụ cho việc cache, search và deterministic sorting:
```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class VaultNoteInfo:
    folder: str
    slug: str
    path: str              # relative path dưới dạng "folder/slug.md"
    metadata: dict[str, Any]
    title: str
    note_type: str
    tags: list[str]
    body: str
```
* **Quy tắc lưu Cache:** Từ điển `_VAULT_CACHE` sẽ lưu trữ dạng: `dict[Path, tuple[int, int, VaultNoteInfo]]` (key: resolved absolute path, tuple: `(mtime_ns, size, note_info)`).

### 3. Tương thích ngược & Đồng bộ Công nghệ cho Wiki Search
* **Backward Compatibility:** Hàm `_tokenize(text)` tại `wiki_injection.py` được định nghĩa rõ ràng:
  `_tokenize(text) -> list(get_token_sets(text).exact)`.
* **Đồng bộ Tìm kiếm:** Hàm `_score_topics` tại `wiki_injection.py` được refactor để sử dụng trực tiếp `get_token_sets()` và áp dụng chung thuật toán **Exact Match Bonus** (thay thế cho logic token overlap cũ). Không sử dụng `_tokenize` cho scoring mới nữa để đảm bảo tính đồng nhất công nghệ.

### 4. Thuật toán Scoring: Exact Match Bonus chi tiết
* **Trọng số trường (Field Weights):** `Title` (2.0), `Tags` (1.5), `Slug` (1.0), `Body` (0.5).
* **Công thức tính điểm cho mỗi Field:**
  $$\text{Score}_{\text{field}} = \text{weight} \times \left( \operatorname{len}(\text{query\_folded} \cap \text{doc\_folded}) + 0.25 \times \operatorname{len}(\text{query\_exact} \cap \text{doc\_exact}) \right)$$
  * Việc so khớp được thực hiện trên **set** đã lọc trùng độc bản của từng trường (qua `TokenSets`) để loại bỏ hiện tượng duplicate score.

### 5. Quy trình Stat-Before-After Guard cho Lazy Cache (Chống TOCTOU Race Condition)
Để giải quyết triệt để rủi ro file bị thay đổi trên đĩa trong quá trình đọc/parse khiến cache lưu thông tin cũ đi kèm stat mới:
1. **Đọc metadata an sau (Step 1):** Acquire `asyncio.Lock` để lấy cached entry từ `_VAULT_CACHE` theo path, ghi nhận `(cached_mtime, cached_size)`. Release lock.
2. **Kiểm tra thay đổi:** So sánh với stat hiện tại trên đĩa. Nếu trùng khớp, sử dụng ngay cache entry.
3. **Đọc đĩa ngoài lock:** Nếu out-of-date, ghi nhận `stat_before = (mtime_ns, size)`. Thực hiện đọc và parse file Markdown hoàn toàn ngoài lock.
4. **Stat sau khi đọc (Step 2):** Đo lại `stat_after = (mtime_ns, size)` của file.
5. **Ghi cache an toàn:** Acquire `asyncio.Lock` lần thứ 2:
   * **Chỉ cập nhật cache** nếu `stat_before == stat_after` (chứng minh file không bị ghi đè trong lúc ta đang đọc). Nếu khác nhau, skip cache entry lần này.
   * Tiến hành prune các file không còn tồn tại trên đĩa khỏi `_VAULT_CACHE`.

### 6. Chuẩn hóa Tags thông minh (Hỗ trợ lỗi người dùng viết tay)
* Tag tìm kiếm đầu vào và tag trong frontmatter của note được chuẩn hóa bằng cách: `lower().strip().lstrip("#")`.
* **Khắc phục lỗi người dùng Obsidian:** Khi parse frontmatter, nếu trường `tags` là một chuỗi đơn (string) thay vì list (do người dùng viết tay sai cú pháp, ví dụ: `tags: work`), hệ thống sẽ tự động chuyển đổi thành **`[string]`** (nếu non-empty) thay vì loại bỏ hoặc gây lỗi.

### 7. Contract chi tiết khi Query Rỗng
* Cho phép query `None` hoặc `""` (rỗng) để browse/list ghi chú theo folder/tags.
* Trọng số score fallback = 0.0.
* Kết quả được sắp xếp deterministic theo `folder/slug` tăng dần và **bắt buộc áp dụng tham số `limit`** để bảo vệ context window của LLM.

### 8. Fallback `vault_read` thông minh dưới chốt chặn `max_chars`
* Khi `include_frontmatter=False` mà parse frontmatter bị lỗi (`VaultFrontmatterParseError`):
  * Hệ thống fallback trả về raw Markdown của ghi chú kèm dòng cảnh báo tường minh ở đầu.
  * **Chốt chặn an toàn:** Chuỗi kết quả cuối cùng **vẫn phải đi qua bộ lọc cắt ngắn `max_chars`** (đã clamp `1000..50000`) để bảo vệ context window của LLM.

---

## Proposed Changes

### Component: Services Layer

#### [NEW] [markdown_text.py](file:///d:/ai-agents/OpenAgentd/app/services/markdown_text.py)
Module tiện ích xử lý văn bản, tokenizer Unicode tiếng Việt và cú pháp Markdown dùng chung:
- **`VaultFrontmatterParseError(ValueError)`**: Ngoại lệ dùng chung khi parse frontmatter thất bại.
- **`TokenSets`**: Dataclass chứa hai set `exact` và `folded`.
- **`fold_vietnamese(text: str) -> str`**: Chuyển đổi thủ công chữ `đ/Đ` thành `d/D` và thực hiện NFD strip accents.
- **`get_token_sets(text: str) -> TokenSets`**: Tách từ bằng Unicode (coi `_` và `-` là separator), sinh hai set `exact` và `folded` độc bản.
- **`split_vault_note_frontmatter(raw: str) -> ParsedVaultNote`**: Tách YAML frontmatter và body an toàn, ném `VaultFrontmatterParseError` nếu malformed.
- **`strip_markdown_for_snippet(text: str) -> str`**: Strip định dạng thô đầu dòng và chuẩn hóa khoảng trắng.

#### [MODIFY] [vault_gatekeeper.py](file:///d:/ai-agents/OpenAgentd/app/services/vault_gatekeeper.py)
- **Giữ nguyên đơn nhiệm.** Không nhận thêm bất kỳ parser hay tokenizer nào.

#### [MODIFY] [vault_ingest.py](file:///d:/ai-agents/OpenAgentd/app/services/vault_ingest.py)
- Import và tái sử dụng `split_vault_note_frontmatter` và `VaultFrontmatterParseError` từ `markdown_text.py`.

#### [NEW] [vault_search.py](file:///d:/ai-agents/OpenAgentd/app/services/vault_search.py)
Tạo service tìm kiếm và đọc note tích hợp Lazy Cache:
- **In-Memory Cache:** `_VAULT_CACHE: dict[Path, tuple[int, int, VaultNoteInfo]]` (key: resolved absolute path). Được bảo vệ bởi một `asyncio.Lock` nội bộ.
- **`clear_vault_search_cache()`**: Reset sạch cache.
- **Windows Read Resilience Helper:** Đọc file có retry (3 lần, delay 10ms) cho `PermissionError` và `FileNotFoundError` tạm thời.
- **Stat-Before-After Guard:** Stat file trước và sau khi đọc I/O đĩa để tránh race conditions.
- `search_notes(query: str | None, folder: str | None = None, tags: list[str] | None = None, limit: int = 5) -> list[tuple[VaultNoteInfo, float, str]]`:
  - Quét đĩa 7 folders, check cache/đọc đĩa ngoài lock và cập nhật an toàn trong lock ngắn.
  - Lọc notes theo folder và AND tags (hỗ trợ phân cấp subtag match, chuẩn hóa tag string).
  - Điểm trùng khớp: Áp dụng công thức **Exact Match Bonus** qua TokenSets. Cho phép query rỗng (score fallback = 0.0, deterministic sort, áp dụng `limit`).
  - Sắp xếp kết quả: `score` giảm dần, sau đó theo `folder/slug` tăng dần (deterministic).
  - Snippet: Trích xuất 500 ký tự đầu tiên của body đã strip nhẹ bằng `strip_markdown_for_snippet()`, thêm `...` ở cuối nếu bị cắt ngắn.

---

### Component: Agent & Tools Layer

#### [MODIFY] [wiki_injection.py](file:///d:/ai-agents/OpenAgentd/app/agent/hooks/wiki_injection.py)
- Import `get_token_sets` từ `app.services.markdown_text`.
- **Backward Compatibility:** Định nghĩa `_tokenize(text) -> list(get_token_sets(text).exact)`.
- **Refactor Scoring:** Sửa `_score_topics` dùng trực tiếp `get_token_sets()` và áp dụng Exact Match Bonus đồng bộ.

#### [NEW] [vault_search.py](file:///d:/ai-agents/OpenAgentd/app/agent/tools/builtin/vault_search.py)
Tool tìm kiếm ghi chú cho agent:
- **Input Schema:** `query` (str | None), `folder` (str | None), `tags` (list[str] | None), `limit` (int = 5, clamp 1..20).
- **Output:** Định dạng sạch: `Path`, `Title`, `Type`, `Tags`, `Score`, `Snippet`.

#### [NEW] [vault_read.py](file:///d:/ai-agents/OpenAgentd/app/agent/tools/builtin/vault_read.py)
Tool đọc chi tiết ghi chú cho agent:
- **Input Schema:** `folder` (str), `slug` (str), `include_frontmatter` (bool = True), `max_chars` (int = 12000, clamp 1000..50000).
- **Output:**
  - Trả về Markdown raw của ghi chú. Đọc trực tiếp từ đĩa qua helper retry (không qua cache).
  - Cắt ngắn ở `max_chars` và thêm `\n\n[truncated at N characters]` nếu vượt quá.
  - Nếu note thực sự thiếu file: `"Note not found at vault/<folder>/<slug>.md"`.
  - Nếu `include_frontmatter=False`:
    - Note không có frontmatter -> trả raw body.
    - Note có malformed frontmatter -> **Fallback** trả về raw file kèm tiền tố cảnh báo và vẫn áp dụng chốt chặn cắt ngắn `max_chars`.

#### [MODIFY] [__init__.py](file:///d:/ai-agents/OpenAgentd/app/agent/tools/builtin/__init__.py)
- Đăng ký `vault_search` và `vault_read` vào default tool registry.

#### [MODIFY] [loader.py](file:///d:/ai-agents/OpenAgentd/app/agent/loader.py)
- Tự động inject `vault_search` và `vault_read` cho lead agent.

---

## Verification Plan

### Automated Tests
1. **`tests/services/test_markdown_text.py` [NEW]**:
   - Verify `split_vault_note_frontmatter` hoạt động chính xác và ném đúng `VaultFrontmatterParseError`.
   - Verify `get_token_sets` trích xuất `exact` và `folded` chính xác cho tiếng Việt có dấu.
   - Verify tokenizer tách từ qua dấu gạch dưới `_` và gạch ngang `-`.
2. **`tests/services/test_vault_search.py` [MODIFY]**:
   - Test subtag matching, test normalize tag string.
   - Test Lazy `mtime_ns` Cache: Đảm bảo cache hoạt động, check Stat-Before-After Guard, tự động prune cache khi file bị xóa, và reset cache trong pytest.
   - Test công thức Exact Match Bonus sử dụng TokenSets.
   - Test Fine-grained Locking hoạt động chính xác, giải phóng lock khi đọc I/O đĩa.
   - Test Windows Read Resilience Helper.
   - Test deterministic sorting theo `folder/slug` cho kết quả bằng điểm.
3. **`tests/agent/tools/test_vault_search_tool.py` [NEW]** & **`tests/agent/tools/test_vault_read_tool.py` [NEW]**:
   - Test fallback thông minh của `vault_read` dưới chốt chặn `max_chars` và đọc trực tiếp từ đĩa.
4. **`tests/agent/test_loader.py` & `tests/agent/tools/test_wiki_search.py` (Regression)**:
   - Đảm bảo re-export hoạt động hoàn hảo, các tests cũ pass 100%.

### Manual Verification
- Chạy bộ test trên môi trường Windows thông qua PowerShell:
  `uv run pytest tests/services/test_vault_ingest.py tests/services/test_markdown_text.py tests/services/test_vault_search.py tests/agent/tools/test_vault_search_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py --no-cov -v`
