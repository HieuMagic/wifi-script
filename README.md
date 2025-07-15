# 🚀 WiFi Auto-Connector 

*Chương trình tự động kết nối WiFi với captive portal - Dành cho những ai chán click "Đồng ý" mỗi 30 phút*

---

## 🤔 Câu chuyện đằng sau

Bạn có bao giờ ngồi ở quán cà phê, mở laptop ra làm việc, nhưng cứ 30 phút lại phải click vào browser để login WiFi lại không? Hoặc tệ hơn, bị block MAC address và phải đợi hoặc fake MAC? 

Tôi đã từng như vậy. Ngồi code được 20 phút thì mất mạng, phải mở browser, click accept terms, wait 6 giây, click connect... Rồi 30 phút sau lại làm lại. Đôi khi còn bị block MAC và phải restart máy hoặc đợi.

Thế là tôi viết chương trình này. Giờ chỉ cần chạy script, ngồi code uống cà phê thôi! 🎯

---

## ✨ Tính năng chính

- **🔄 Tự động login captive portal** - Không cần click manual nữa
- **🎭 MAC address spoofing** - Bypass MAC blocking thông minh
- **🌈 Logging màu sắc** - Biết chuyện gì đang xảy ra
- **⚡ Performance optimization** - Caching, smart retry, resource management
- **🛡️ Graceful shutdown** - Không để lại process zombie
- **🏗️ Clean architecture** - Code dễ maintain và extend
- **📊 Smart monitoring** - Chỉ check khi cần, không spam

---

## 🚀 Quick Start

```bash
# 1. Clone hoặc download
git clone <repo-url>
cd wifi-script

# 2. Cài dependencies
pip install selenium requests

# 3. Download Edge WebDriver
# https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/

# 4. Cài spoof-mac tool (optional)
pip install spoof-mac

# 5. Configure XPath trong file
# Sửa WifiConfig trong wifi_refactored.py

# 6. Run
python wifi_refactored.py
```

---

## 🔧 Chi tiết Setup

### 1. Requirements
- **Python 3.7+** 
- **Microsoft Edge** (đã cài sẵn trên Windows)
- **Edge WebDriver** - Download từ [Microsoft](https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/)
- **spoof-mac** (optional) - Cho MAC address changing

### 2. Cài đặt Dependencies

```bash
pip install selenium requests
```

### 3. Download Edge WebDriver
- Vào https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/
- Download version match với Edge browser của bạn
- Extract vào folder (ví dụ: `C:\Users\Hieu\Desktop\Edge_Driver\`)

### 4. Cài spoof-mac (Optional)
```bash
pip install spoof-mac
```

### 5. Tìm XPath của trang captive portal
- Mở browser, connect WiFi
- Khi xuất hiện trang login, press F12 → Elements
- Right-click vào button "Remind me later" → Copy → Copy XPath
- Làm tương tự với 2 buttons chính
- Paste vào config

---

## ⚙️ Configuration

Sửa class `WifiConfig` trong `wifi_refactored.py`:

```python
@dataclass
class WifiConfig:
    # Đường dẫn đến Edge WebDriver
    edge_driver_path: str = r"C:\Users\Hieu\Desktop\Edge_Driver\msedgedriver.exe"
    
    # XPath của các elements (tìm bằng F12 Developer Tools)
    xpath_popup_remind_later: str = "//*[@id='remind-me']"
    xpath_button_1: str = "/html/body/main/div[1]/div[3]/div/div/div/div[1]/button"
    xpath_button_2: str = "//*[@id='connectToInternet']"
    
    # Timing settings
    check_interval: int = 10                    # Kiểm tra mỗi 10 giây
    max_failures_before_mac_change: int = 4     # Đổi MAC sau 4 lần fail
    mac_change_cooldown: int = 300              # Cooldown 5 phút
    browser_timeout: int = 40                   # Timeout browser
    network_timeout: int = 10                   # Timeout network check
    mac_stabilization_time: int = 15            # Đợi network ổn định
```

---

## 🎮 Cách sử dụng

### Basic Usage
```bash
python wifi_refactored.py
```

### What You'll See
```
🚀 Starting WiFi Auto-Connector...
--- WiFi Auto-Connector Status (14:30:25) ---
State: connected
Consecutive failures: 0
MAC tool available: Yes
--------------------------------------------------
14:30:25 - INFO - ✅ Internet connection stable
14:30:25 - INFO - 🎉 Internet connection restored!
14:30:25 - INFO - ⏳ Next check in 10 seconds...
```

### Khi mất mạng
```
14:35:15 - WARNING - ❌ Blocked by captive portal
14:35:15 - WARNING - Connection failure #1
14:35:15 - INFO - 🔐 Attempting captive portal login...
14:35:15 - INFO - Starting browser automation...
14:35:16 - INFO - Found popup, dismissing...
14:35:16 - INFO - ✅ Popup dismissed
14:35:17 - INFO - ✅ First button clicked
14:35:23 - INFO - ✅ Second button clicked
14:35:33 - INFO - ✅ Login sequence completed successfully
```

### Khi cần đổi MAC
```
14:40:25 - INFO - 🔄 Attempting MAC address change...
14:40:25 - INFO - Changing MAC address using: C:\Users\...\spoof-mac.exe
14:40:26 - INFO - MAC address changed successfully
14:40:26 - INFO - Waiting 15s for network stabilization...
```

---

## 🔍 Troubleshooting

### "Edge driver not found"
```
❌ Configuration Error: Edge driver not found: C:\Users\...\msedgedriver.exe
```
**Fix**: Download đúng Edge WebDriver và update path trong config

### "Please replace XPath placeholders"
```
❌ Configuration Error: Please replace XPath placeholders with actual values
```
**Fix**: Thay thế XPath bằng values thực từ captive portal

### "spoof-mac tool not found"
```
⚠️ spoof-mac tool not found. MAC address changing will be unavailable.
```
**Fix**: `pip install spoof-mac` hoặc ignore nếu không cần đổi MAC

### Browser timeout
```
❌ Timeout during browser automation: Message: timeout
```
**Fix**: Tăng `browser_timeout` trong config hoặc check XPath

### Process cleanup issues
Nếu có Edge processes còn sót lại:
- Script tự động cleanup khi thoát
- Hoặc manually: Task Manager → End Edge processes

---

## 💡 Advanced Tips

### 1. Chạy background
```bash
# Windows
pythonw wifi_refactored.py

# Hoặc dùng nohup trên Linux/Mac
nohup python wifi_refactored.py &
```

### 2. Auto-start với Windows
- Tạo .bat file:
```batch
@echo off
cd /d "C:\Users\Hieu\Desktop\wifi-script"
python wifi_refactored.py
```
- Add vào Windows Startup folder

### 3. Multiple WiFi networks
- Tạo multiple config files
- Hoặc detect WiFi name và switch config

### 4. Logging to file
Sửa `setup_logging()` để add file handler:
```python
file_handler = logging.FileHandler('wifi_connector.log')
logger.addHandler(file_handler)
```

---

## 🏗️ Technical Details

### Architecture
```
WifiAutoConnector (Main Orchestrator)
├── ProcessManager (Edge process management)
├── NetworkChecker (Internet connectivity)
├── MacAddressManager (MAC spoofing)
├── BrowserAutomator (Selenium automation)
└── WifiConfig (Configuration)
```

### Design Patterns
- **Factory Pattern**: WebDriver setup
- **Strategy Pattern**: Different MAC spoofing methods
- **Observer Pattern**: State change notifications
- **Singleton Pattern**: Logger instance

### Performance Optimizations
- **Caching**: Network status cache (5s) để avoid spam checking
- **Lazy Loading**: Browser chỉ khởi tạo khi cần
- **Resource Management**: Proper cleanup với finally blocks
- **Process Tracking**: Chỉ track processes của script

### Error Handling
- **Custom Exceptions**: Specific error types
- **Graceful Degradation**: Fallback mechanisms
- **Retry Logic**: Smart retry với backoff
- **Resource Cleanup**: Guaranteed cleanup

---

## 🤝 Contributing

Nếu bạn muốn improve code:

1. **Fork** repo
2. **Create feature branch**: `git checkout -b feature/amazing-feature`
3. **Test thoroughly** - đặc biệt edge cases
4. **Update documentation** nếu cần
5. **Submit PR** với clear description

### Ideas for improvement:
- [ ] Support multiple captive portal types
- [ ] GUI interface
- [ ] Mobile hotspot support
- [ ] Network profile management
- [ ] Statistics và monitoring
- [ ] Docker container
- [ ] Cross-platform testing

---

## ⚖️ Legal & Disclaimer

### ⚠️ Important Notes:
- **Chỉ sử dụng trên WiFi mà bạn có quyền truy cập**
- **MAC spoofing có thể vi phạm ToS của một số networks**
- **Chịu trách nhiệm về việc sử dụng**
- **Không dùng để bypass security không được phép**

### Responsible Usage:
- Respect network policies
- Don't abuse free WiFi systems
- Use primarily for legitimate work/study
- Be mindful of bandwidth usage

---

## 🙏 Credits & Acknowledgments

- **Selenium** - Browser automation framework
- **spoof-mac** - MAC address spoofing tool
- **Microsoft Edge** - WebDriver platform
- **Python community** - Amazing ecosystem
- **Coffee shops** - Inspiration và testing environment ☕

---

## 📞 Support

Nếu gặp issues:
1. Check **Troubleshooting** section trước
2. Verify **configuration** 
3. Test **manually** trước khi report bug
4. Provide **detailed logs** khi báo lỗi

---

*Made with ❤️ và rất nhiều cà phê bởi ai đó chán click "Đồng ý" mỗi 30 phút*

**Version**: 2.0 (Refactored)  
**Last Updated**: July 2025  
**License**: MIT (Use responsibly!)
