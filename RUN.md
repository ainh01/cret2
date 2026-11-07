# RUN

## Docker / Linux

1. Sao chép `.env.example` thành `.env`, rồi điền API text và API ảnh.
2. Mở Cret2 bằng URL công khai mà người học truy cập được; ứng dụng tự lấy URL đó từ trình duyệt để tạo link ảnh. Reverse proxy cần chuyển tiếp `/generated-images/` đến Cret2.
3. Chạy `docker compose up -d --build` và mở cổng 3004 hoặc cấu hình reverse proxy.

Ảnh và cài đặt được lưu trong volume `cret2-data` tại `/app/data`, nên tồn tại khi container được tạo lại. Đừng xóa volume nếu muốn giữ ảnh cho các bài đã chia sẻ. Cài đặt đổi qua `/settings` được ghi vào volume và ưu tiên hơn biến môi trường ở lần khởi động sau. Tránh chạy nhiều bản Cret2 với các volume ảnh riêng nếu không có bộ nhớ dùng chung.

Nếu mở Cret2 qua localhost hoặc mạng nội bộ, các máy khác không thể truy cập ảnh: hãy mở app bằng domain công khai. Nếu trang học chạy HTTPS, URL ảnh cũng nên dùng HTTPS để tránh mixed content.

## Quiz backend (storage, port 3003)

```powershell
cd C:\Users\Ainh\Desktop\fakedev\quizbackend
npm install
node app.js
```

## Quiz frontend (learn app, port 5173)

```powershell
cd C:\Users\Ainh\Desktop\dev\quiz
npm run dev -- --port 5173 --strictPort
```

## Cret2 (generator, port 3004)

```powershell
cd C:\Users\Ainh\Desktop\fakedev\cret2
python -m uvicorn app:app --host 0.0.0.0 --port 3004
```
