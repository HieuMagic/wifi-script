# � WiFi Auto-Connector

*Bởi vì cuộc đời quá ngắn để ngồi click "Đồng ý" mỗi 15 phút*

---

## �‍♂️ Tại sao tôi viết cái này?

Câu chuyện bắt đầu từ cái sự nghèo khỉ của tôi trong một mùa thu ở Sài Gòn. Tôi đang sử dụng mạng miễn phí của kí túc xá, deadline đang cận kề, code đang chạy smooth... thì đột nhiên mất mạng. Mở browser lên, trang login hiện ra với dòng chữ quen thuộc "Vui lòng đồng ý điều khoản". Click. Đợi 6 giây. Click tiếp. Xong.

15 phút sau, lại mất mạng. Lại click. Lại đợi.

Ngày hôm đó tôi mất mạng 8 lần. Mỗi lần phải ngừng code để làm cái ritual click-đợi-click này. Tệ hơn, có lúc bị block MAC address, phải đợi hoặc restart máy.

Tôi nghĩ: "Chắc có cách nào tự động hóa cái này được."

Và đây là kết quả. Giờ tôi chỉ cần chạy script này, ngồi code uống cà phê, không cần quan tâm WiFi nữa. Thậm chí còn tự động chia sẻ mạng cho điện thoại luôn.

---

## 🎯 Nó làm được gì?

- **Tự động login captive portal** - Không bao giờ phải click manual nữa
- **MAC spoofing thông minh** - Bypass các giới hạn MAC address
- **Chia sẻ WiFi qua hotspot** - Điện thoại/tablet tự động có mạng
- **Tự phục hồi** - Mất mạng? Không sao, script lo
- **Logging đầy đủ** - Biết chính xác chuyện gì đang xảy ra
- **Chạy êm ái** - Không spam, không làm chậm máy

---

## 🏃‍♂️ Chạy thử trong 5 phút

```bash
# Bước 1: Cài Python dependencies
pip install selenium requests

# Bước 2: Tải Edge WebDriver
# Vào https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/
# Download về đâu đó, nhớ đường dẫn

# Bước 3: Cài MAC spoofing tool (optional nhưng nên có)
pip install spoof-mac

# Bước 4: Sửa config trong wifi_refactored.py
# Thay đổi đường dẫn driver và XPath (xem phần dưới)

# Bước 5: Chạy
python wifi_refactored.py
```

Thế thôi! Script sẽ tự động lo phần còn lại.

---

## ⚙️ Cấu hình cơ bản

Mở file `wifi_refactored.py` và sửa class `WifiConfig`:

```python
@dataclass
class WifiConfig:
    # Đường dẫn tới Edge WebDriver (thay đổi theo máy bạn)
    edge_driver_path: str = r"C:\Users\Hieu\Desktop\Edge_Driver\msedgedriver.exe"
    
    # XPath của các nút trên trang login (quan trọng nhất!)
    xpath_popup_remind_later: str = "//*[@id='remind-me']"
    xpath_button_1: str = "/html/body/main/div[1]/div[3]/div/div/div/div[1]/button"
    xpath_button_2: str = "//*[@id='connectToInternet']"
    
    # Các tùy chọn khác (có thể để mặc định)
    check_interval: int = 10                    # Kiểm tra mỗi 10 giây
    enable_hotspot_sharing: bool = True         # Tự động chia sẻ WiFi
    enable_mac_spoofing: bool = True           # Cho phép đổi MAC
```

### 🔍 Cách tìm XPath

Đây là phần quan trọng nhất. Nếu XPath sai, script sẽ không hoạt động:

1. **Kết nối WiFi và mở trang login**
2. **Nhấn F12 → Developer Tools**
3. **Click biểu tượng mũi tên (Select element)**
4. **Click vào nút cần lấy XPath**
5. **Right-click → Copy → Copy XPath**
6. **Paste vào config**

Làm tương tự cho cả 3 elements: popup dismiss, button 1, button 2.

---

## 🎮 Sử dụng

### Chạy bình thường:
```bash
python wifi_refactored.py
```

### Chạy với quyền admin (để bật hotspot):
```bash
# Mở PowerShell/CMD as Administrator, rồi chạy
python wifi_refactored.py
```

### Chạy ngầm:
```bash
pythonw wifi_refactored.py
```

### Khi chạy, bạn sẽ thấy:

```
🚀 Starting WiFi Auto-Connector...
--- WiFi Auto-Connector Status (14:30:25) ---
State: connected
Hotspot status: Enabled (Sharing WiFi)
Running as admin: Yes
--------------------------------------------------
✅ Internet connection stable
🔥 Mobile hotspot enabled - sharing WiFi
⏳ Next check in 10 seconds...
```

---

## � Xử lý lỗi thường gặp

### "Edge driver not found"
**Nguyên nhân:** Đường dẫn WebDriver sai  
**Cách fix:** Download Edge WebDriver từ Microsoft và sửa đường dẫn trong config

### "XPath not found"
**Nguyên nhân:** XPath elements đã thay đổi  
**Cách fix:** Dùng F12 Developer Tools để lấy XPath mới

### "Not running as administrator"
**Nguyên nhân:** Thiếu quyền admin để bật hotspot  
**Cách fix:** Chạy PowerShell/CMD as Administrator

### "spoof-mac not found"
**Nguyên nhân:** Chưa cài MAC spoofing tool  
**Cách fix:** `pip install spoof-mac` hoặc tắt MAC spoofing trong config

### Browser bị timeout
**Nguyên nhân:** Mạng chậm hoặc trang login phức tạp  
**Cách fix:** Tăng `browser_timeout` trong config

---

## 💡 Mẹo hay

### 🔄 Chạy tự động khi khởi động Windows
Tạo file `start_wifi.bat`:
```batch
@echo off
cd /d "C:\Users\Hieu\Desktop\wifi-script"
python wifi_refactored.py
```
Rồi bỏ vào thư mục Startup của Windows.

### 📱 Chia sẻ WiFi cho điện thoại
Script tự động bật hotspot khi WiFi hoạt động. Điện thoại chỉ cần kết nối vào hotspot của máy tính là có mạng.

### 🏃‍♂️ Chạy nhiều config khác nhau
Nếu bạn thường xuyên ở các quán khác nhau với captive portal khác nhau, có thể tạo nhiều file config và switch giữa chúng.

---

## 🤝 Đóng góp

Nếu bạn có ý tưởng cải tiến hoặc gặp bug, welcome to contribute! Tôi built cái này để giải quyết vấn đề của mình, nhưng nếu nó hữu ích cho bạn và bạn muốn làm nó tốt hơn, tôi rất vui.

---

## ⚖️ Lưu ý pháp lý

**Sử dụng có trách nhiệm:**
- Chỉ dùng trên WiFi mà bạn được phép truy cập
- Không lạm dụng để bypass security
- Tôn trọng terms of service của từng mạng
- Chịu trách nhiệm về việc sử dụng

---

*Được viết bởi một developer chán ngấy việc click "Đồng ý" mỗi 30 phút. Nếu bạn cũng như tôi, hy vọng cái này sẽ giúp bạn tập trung vào việc quan trọng hơn.*

**Made with ❤️ and lots of ☕**
