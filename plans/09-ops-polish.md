# Plan 09 — Ops & polish: Docker, auth, logging, frontend tests

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: plan 03 (làm bất kỳ lúc nào sau đó).
> Mục tiêu: chạy được bằng một lệnh, để lâu không hỏng, người ngoài mạng LAN không đụng được.

## Việc cần làm

### 1. Đóng gói

- `backend/Dockerfile` (python:3.10-slim, install `-e .`, uvicorn) và
  `frontend/Dockerfile` (build Vite → serve tĩnh bằng nginx, proxy `/api` → backend).
- `docker-compose.yml`: services `api`, `web`, volume cho `backend/data/` (DB + CSV).
  Service `live` (profile riêng của compose, không auto-start) chạy `bot.cli live` — cho plan 07.
- `.env.example`: `BOT_DB_PATH`, `TELEGRAM_*`, `BOT_API_TOKEN`, port. Env đọc qua một module
  `bot/settings.py` duy nhất (không rải `os.environ` khắp nơi).
- Chạy ngoài Docker trên máy Mac của user: file `launchd` plist mẫu (hoặc hướng dẫn
  `docker compose up -d`) trong `docs/ops.md` — kèm lệnh backup DB
  (`sqlite3 … ".backup …"`, cron hàng ngày, giữ 7 bản).

### 2. Auth tối thiểu

- Nếu đặt `BOT_API_TOKEN`: mọi endpoint (trừ `/api/health`) đòi header
  `Authorization: Bearer <token>` — middleware FastAPI đơn giản, không user/role.
  Frontend: ô nhập token 1 lần, lưu localStorage, gắn vào client fetch.
  Không đặt token → hành vi như hiện tại (dev mode). KHÔNG tự chế JWT/user management.

### 3. Logging & lỗi

- Backend: `logging` chuẩn cấu hình JSON lines ra stdout (Docker gom); mức INFO cho
  decision/trade/run lifecycle, WARNING cho feed degraded, ERROR kèm stack. Bỏ mọi `print`.
- Frontend: ErrorBoundary bọc từng page; fetch lỗi → toast + retry, không màn hình trắng.
- Uvicorn access log tắt ở production compose (ồn), giữ app log.

### 4. Frontend tests + chất lượng

- **Guard fail-open regime (user chốt 2026-07-18, đợt 3)**: tắt cả hai filter `adx` và `er`
  làm bot vào nhánh BREAKOUT mọi lúc (fail-open — xem decisions.md mục Mapping). Trang Config:
  khi user tắt filter **thứ hai** trong cặp {adx, er} (cái còn lại đã tắt), hiện **dialog
  xác nhận** giải thích hệ quả ("bot sẽ luôn chạy Breakout, không còn nhận diện regime") —
  chỉ áp dụng thay đổi sau khi user confirm; Cancel → giữ nguyên. Có test cho cả hai chiều
  (tắt adx trước er và ngược lại) + case chỉ tắt một cái thì không hỏi.
- Vitest + React Testing Library: smoke render 4 page với API mock (msw hoặc fetch mock);
  test FilterConfigPanel render đúng từ một schema fixture (đây là logic dày nhất của UI);
  test usePolling không rò interval khi unmount.
- `npm run typecheck` (tsc --noEmit) thêm vào CI cùng build (CI đã có từ plan 01 — mở rộng
  job frontend: typecheck + test + build).

### 5. Docs

- `docs/ops.md`: chạy compose, backup/restore DB, xoay token, xem log, checklist khi
  live runner chết (plan 07). README trỏ tới.

## Definition of done

- `docker compose up` từ máy sạch → mở `http://localhost:<port>` thấy dashboard hoạt động
  với backend trong container; token bật thì curl không token bị 401.
- CI xanh gồm frontend typecheck+test; backup script chạy được; test/mypy/ruff backend
  không suy suyển.
