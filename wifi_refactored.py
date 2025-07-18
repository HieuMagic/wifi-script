#!/usr/bin/env python3
"""
WiFi Auto-Connector - Optimized Version
Automated WiFi connection with captive portal login, MAC spoofing, and hotspot sharing
"""

import atexit
import ctypes
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple, Dict
import requests
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ================================= CONSTANTS =================================

class Constants:
    """Application constants"""
    # Network
    NETWORK_CHECK_URLS = ["https://www.google.com", "https://www.cloudflare.com"]
    NETWORK_TIMEOUT = 10
    CACHE_DURATION = 10  # seconds
    
    # Browser
    BROWSER_TIMEOUT = 40
    POPUP_TIMEOUT = 15
    STABILIZATION_DELAY = 6
    CONNECTION_WAIT = 10
    
    # System
    PROCESS_TIMEOUT = 30
    ADMIN_CHECK_TIMEOUT = 5
    MAC_STABILIZATION_TIME = 15
    
    # Hotspot
    HOTSPOT_CACHE_DURATION = 10
    HOTSPOT_STABILIZATION_TIME = 3
    
    # Retry
    MAX_RETRIES = 3
    RETRY_DELAY = 2

# ================================= CONFIGURATION =================================

@dataclass
class WifiConfig:
    """WiFi Auto-Connector Configuration"""
    # Edge WebDriver
    edge_driver_path: str = field(default_factory=lambda: _find_edge_driver())
    
    # XPath selectors
    xpath_popup_remind_later: str = "//*[@id='remind-me']"
    xpath_button_1: str = "/html/body/main/div[1]/div[3]/div/div/div/div[1]/button"
    xpath_button_2: str = "//*[@id='connectToInternet']"
    
    # Timing
    check_interval: int = 10
    max_failures_before_mac_change: int = 3
    mac_change_cooldown: int = 300  # 5 minutes
    mac_stabilization_time: int = 15  # seconds to wait after MAC change
    
    # Features
    enable_mac_spoofing: bool = True
    enable_hotspot_sharing: bool = True
    auto_enable_hotspot: bool = True
    keep_hotspot_always_on: bool = True
    disable_hotspot_on_wifi_loss: bool = True
    
    def validate(self) -> None:
        """Validate configuration"""
        if not Path(self.edge_driver_path).exists():
            raise ConfigurationError(f"Edge driver not found: {self.edge_driver_path}")
        
        # Check for placeholder values
        placeholders = ["DÁN_XPATH", "PLACEHOLDER", "CHANGE_ME"]
        for placeholder in placeholders:
            if placeholder in (self.xpath_button_1, self.xpath_button_2, self.xpath_popup_remind_later):
                raise ConfigurationError(f"Please replace XPath placeholder: {placeholder}")

def _find_edge_driver() -> str:
    """Auto-detect Edge WebDriver location"""
    possible_paths = [
        os.path.join(os.getcwd(), "msedgedriver.exe"),
        os.path.join(os.path.expanduser("~"), "Desktop", "Edge_Driver", "msedgedriver.exe"),
        os.path.join(os.path.dirname(sys.executable), "Scripts", "msedgedriver.exe"),
        "msedgedriver.exe"  # Assume it's in PATH
    ]
    
    for path in possible_paths:
        if Path(path).exists():
            return path
    
    # Default fallback
    return r"C:\Users\Hieu\Desktop\Edge_Driver\msedgedriver.exe"

# ================================= EXCEPTIONS =================================

class WifiConnectorError(Exception):
    """Base exception for WiFi connector"""
    pass

class ConfigurationError(WifiConnectorError):
    """Configuration validation errors"""
    pass

class NetworkError(WifiConnectorError):
    """Network-related errors"""
    pass

class BrowserError(WifiConnectorError):
    """Browser automation errors"""
    pass

class HotspotError(WifiConnectorError):
    """Hotspot management errors"""
    pass

class MacAddressError(WifiConnectorError):
    """MAC address management errors"""
    pass

# ================================= ENUMS =================================

class ConnectionState(Enum):
    """Connection states"""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    RECOVERING = "recovering"
    MAC_CHANGING = "mac_changing"
    HOTSPOT_MANAGING = "hotspot_managing"

class LoginResult(Enum):
    """Login attempt results"""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"

# ================================= LOGGING =================================

class ColoredFormatter(logging.Formatter):
    """Colored log formatter"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[92m',     # Green
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[95m'  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

def setup_logging() -> logging.Logger:
    """Setup application logging"""
    logger = logging.getLogger('wifi_connector')
    logger.setLevel(logging.INFO)
    
    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

# ================================= UTILITIES =================================

def retry_on_failure(retries: int = Constants.MAX_RETRIES, delay: float = Constants.RETRY_DELAY):
    """Retry decorator for methods that might fail"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < retries - 1:
                        time.sleep(delay * (attempt + 1))  # Progressive delay
                    continue
            raise last_exception
        return wrapper
    return decorator

@contextmanager
def suppress_subprocess_output():
    """Context manager to suppress subprocess output"""
    devnull = open(os.devnull, 'w')
    try:
        yield devnull
    finally:
        devnull.close()

# ================================= CORE MANAGERS =================================

class NetworkManager:
    """Handles network connectivity"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._last_check_time: Optional[datetime] = None
        self._last_check_result: Optional[bool] = None
    
    def check_internet_connection(self) -> bool:
        """Check internet connectivity with caching"""
        # Use cache if available
        if (self._last_check_time and 
            datetime.now() - self._last_check_time < timedelta(seconds=Constants.CACHE_DURATION)):
            return self._last_check_result or False
        
        self.logger.info("Checking internet connection...")
        
        for url in Constants.NETWORK_CHECK_URLS:
            try:
                response = requests.get(
                    url,
                    timeout=Constants.NETWORK_TIMEOUT,
                    headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
                )
                
                if response.status_code == 200:
                    # Cache successful result
                    self._last_check_time = datetime.now()
                    self._last_check_result = True
                    self.logger.info("✅ Internet connection stable")
                    return True
                    
            except requests.RequestException:
                continue
        
        # Cache failed result
        self._last_check_time = datetime.now()
        self._last_check_result = False
        self.logger.warning("❌ No internet connection")
        return False
    
    def clear_cache(self) -> None:
        """Clear network check cache"""
        self._last_check_time = None
        self._last_check_result = None

class MacAddressManager:
    """Manages MAC address spoofing"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._spoof_mac_path: Optional[str] = None
    
    def find_spoof_mac_executable(self) -> Optional[str]:
        """Find spoof-mac executable"""
        if self._spoof_mac_path:
            return self._spoof_mac_path
        
        # Check system Scripts directory
        system_path = os.path.join(
            os.path.dirname(sys.executable), "Scripts", "spoof-mac.exe"
        )
        if os.path.exists(system_path):
            self._spoof_mac_path = system_path
            return system_path
        
        # Check user Scripts directory
        try:
            python_version = f"Python{sys.version_info.major}{sys.version_info.minor}"
            user_path = os.path.join(
                os.getenv('APPDATA'), "Python", python_version, "Scripts", "spoof-mac.exe"
            )
            if os.path.exists(user_path):
                self._spoof_mac_path = user_path
                return user_path
        except Exception:
            pass
        
        # Check for Python file
        try:
            user_py_path = os.path.join(
                os.getenv('APPDATA'), "Python", 
                f"Python{sys.version_info.major}{sys.version_info.minor}",
                "Scripts", "spoof-mac.py"
            )
            if os.path.exists(user_py_path):
                self._spoof_mac_path = user_py_path
                return user_py_path
        except Exception:
            pass
        
        return None
    
    def is_tool_available(self) -> bool:
        """Check if spoof-mac tool is available"""
        return self.find_spoof_mac_executable() is not None
    
    def change_mac_address(self) -> bool:
        """Change MAC address using spoof-mac tool"""
        spoof_mac_path = self.find_spoof_mac_executable()
        
        if not spoof_mac_path:
            raise MacAddressError("spoof-mac tool not found")
        
        self.logger.info(f"🔄 Changing MAC address using: {spoof_mac_path}")
        
        # Build command
        if spoof_mac_path.endswith(".py"):
            command = [sys.executable, spoof_mac_path, "randomize", "wi-fi"]
        else:
            command = [spoof_mac_path, "randomize", "wi-fi"]
        
        try:
            self.logger.debug(f"Running command: {' '.join(command)}")
            result = subprocess.run(
                command, 
                check=True, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            self.logger.info("✅ MAC address changed successfully")
            self.logger.info(f"⏳ Waiting {self.config.mac_stabilization_time}s for network stabilization...")
            time.sleep(self.config.mac_stabilization_time)
            
            return True
            
        except subprocess.CalledProcessError as e:
            raise MacAddressError(f"spoof-mac command failed: {e.stderr}")
        except Exception as e:
            raise MacAddressError(f"Unexpected error changing MAC: {e}")

class BrowserManager:
    """Handles browser automation and process management"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self.driver: Optional[webdriver.Edge] = None
        self.created_processes: List[int] = []
    
    @contextmanager
    def browser_session(self):
        """Context manager for browser sessions"""
        existing_pids = self._get_edge_processes()
        
        try:
            self.driver = self._setup_driver()
            self._track_new_processes(existing_pids)
            yield self.driver
        finally:
            self._cleanup_session()
    
    def _setup_driver(self) -> webdriver.Edge:
        """Setup optimized Edge WebDriver"""
        service = Service(executable_path=self.config.edge_driver_path)
        options = webdriver.EdgeOptions()
        
        # Performance optimizations
        options.add_argument("--headless")
        options.add_argument("--log-level=3")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        
        options.page_load_strategy = 'eager'
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_experimental_option('useAutomationExtension', False)
        
        return webdriver.Edge(service=service, options=options)
    
    def perform_login(self) -> LoginResult:
        """Perform captive portal login"""
        try:
            with self.browser_session() as driver:
                self.logger.info("🔐 Starting captive portal login...")
                driver.get("http://neverssl.com")
                
                wait = WebDriverWait(driver, Constants.BROWSER_TIMEOUT)
                
                # Handle popup if present
                self._handle_popup(driver)
                
                # Click sequence
                self._click_button_sequence(driver, wait)
                
                self.logger.info("✅ Login sequence completed successfully")
                return LoginResult.SUCCESS
                
        except TimeoutException:
            self.logger.error("❌ Login timeout")
            return LoginResult.TIMEOUT
        except Exception as e:
            self.logger.error(f"❌ Login failed: {e}")
            return LoginResult.FAILED
    
    def _handle_popup(self, driver: webdriver.Edge) -> None:
        """Handle popup dismissal"""
        try:
            popup_wait = WebDriverWait(driver, Constants.POPUP_TIMEOUT)
            popup_button = popup_wait.until(
                EC.element_to_be_clickable((By.XPATH, self.config.xpath_popup_remind_later))
            )
            self.logger.info("Found popup, dismissing...")
            time.sleep(1)
            driver.execute_script("arguments[0].click();", popup_button)
            self.logger.info("✅ Popup dismissed")
        except TimeoutException:
            self.logger.debug("No popup found")
    
    def _click_button_sequence(self, driver: webdriver.Edge, wait: WebDriverWait) -> None:
        """Execute button click sequence"""
        # First button
        self.logger.info("Clicking first button...")
        button1 = wait.until(EC.element_to_be_clickable((By.XPATH, self.config.xpath_button_1)))
        driver.execute_script("arguments[0].click();", button1)
        self.logger.info("✅ First button clicked")
        
        # Required delay
        time.sleep(Constants.STABILIZATION_DELAY)
        
        # Second button
        self.logger.info("Clicking second button...")
        button2 = wait.until(EC.element_to_be_clickable((By.XPATH, self.config.xpath_button_2)))
        driver.execute_script("arguments[0].click();", button2)
        driver.execute_script("arguments[0].click();", button2)
        self.logger.info("✅ Second button clicked")
        
        # Connection wait
        time.sleep(Constants.CONNECTION_WAIT)
    
    def _get_edge_processes(self) -> List[int]:
        """Get current Edge process PIDs"""
        try:
            result = subprocess.run(
                ["tasklist", "/fi", "imagename eq msedge.exe", "/fo", "csv"],
                capture_output=True, text=True, timeout=10
            )
            
            pids = []
            for line in result.stdout.split('\n')[1:]:  # Skip header
                if line.strip():
                    parts = line.split(',')
                    if len(parts) >= 2:
                        pid = parts[1].strip('"')
                        if pid.isdigit():
                            pids.append(int(pid))
            return pids
        except Exception:
            return []
    
    def _track_new_processes(self, existing_pids: List[int]) -> None:
        """Track new processes for cleanup"""
        current_pids = self._get_edge_processes()
        new_pids = [pid for pid in current_pids if pid not in existing_pids]
        self.created_processes.extend(new_pids)
    
    def _cleanup_session(self) -> None:
        """Clean up browser session"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            finally:
                self.driver = None
        
        # Clean up processes
        for pid in self.created_processes:
            try:
                subprocess.run(["taskkill", "/f", "/pid", str(pid)], 
                             capture_output=True, timeout=5)
            except Exception:
                pass
        self.created_processes.clear()

class HotspotManager:
    """Manages Windows Mobile Hotspot functionality"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._last_check_time: Optional[datetime] = None
        self._last_status: Optional[bool] = None
        self._is_admin: Optional[bool] = None
    
    def is_admin(self) -> bool:
        """Check if running with administrator privileges"""
        if self._is_admin is None:
            try:
                self._is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except:
                self._is_admin = False
        return self._is_admin
    
    def is_available(self) -> bool:
        """Check if hotspot functionality is available"""
        if not self.is_admin():
            return False
        
        try:
            cmd = """
            try {
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) { 
                    [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    Write-Output "AVAILABLE"
                } else { exit 1 }
            } catch { exit 1 }
            """
            result = subprocess.run(["powershell", "-Command", cmd], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0 and "AVAILABLE" in result.stdout
        except Exception:
            return False
    
    def check_status(self) -> bool:
        """Check hotspot status with caching"""
        # Use cache if available
        if (self._last_check_time and 
            datetime.now() - self._last_check_time < timedelta(seconds=Constants.HOTSPOT_CACHE_DURATION)):
            return self._last_status or False
        
        try:
            cmd = """
            try {
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) {
                    $manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    Write-Output $manager.TetheringOperationalState
                } else { Write-Output "0" }
            } catch { Write-Output "0" }
            """
            
            result = subprocess.run(["powershell", "-Command", cmd], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                # TetheringOperationalState: 0=Unknown, 1=Off, 2=On, 3=InTransition
                state = int(result.stdout.strip())
                is_enabled = state == 2
                
                # Cache result
                self._last_check_time = datetime.now()
                self._last_status = is_enabled
                return is_enabled
                
        except Exception:
            pass
        
        return False
    
    def enable(self) -> bool:
        """Enable mobile hotspot"""
        if not self.is_admin():
            raise HotspotError("Administrator privileges required")
        
        self.logger.info("🔥 Enabling mobile hotspot...")
        
        try:
            cmd = """
            try {
                # Load Windows Runtime assembly
                Add-Type -AssemblyName System.Runtime.WindowsRuntime
                
                # Define function to convert Windows Runtime tasks to .NET Tasks
                $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
                Function Await($WinRtTask, $ResultType) {
                    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                    $netTask = $asTask.Invoke($null, @($WinRtTask))
                    $netTask.Wait(-1) | Out-Null
                    $netTask.Result
                }
                
                # Get profile and manager
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) {
                    $manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    $result = Await ($manager.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
                    Write-Output "SUCCESS"
                } else { Write-Output "ERROR: No internet connection" }
            } catch { Write-Output "ERROR: $($_.Exception.Message)" }
            """
            
            result = subprocess.run(["powershell", "-Command", cmd], 
                                  capture_output=True, text=True, timeout=Constants.PROCESS_TIMEOUT)
            
            if result.returncode == 0 and "SUCCESS" in result.stdout:
                self._invalidate_cache()
                time.sleep(Constants.HOTSPOT_STABILIZATION_TIME)
                self.logger.info("✅ Mobile hotspot enabled successfully")
                return True
            else:
                raise HotspotError(f"Failed to enable hotspot: {result.stdout}")
                
        except subprocess.TimeoutExpired:
            raise HotspotError("Hotspot enable operation timed out")
    
    def disable(self) -> bool:
        """Disable mobile hotspot"""
        if not self.is_admin():
            raise HotspotError("Administrator privileges required")
        
        self.logger.info("🔥 Disabling mobile hotspot...")
        
        try:
            cmd = """
            try {
                # Load Windows Runtime assembly
                Add-Type -AssemblyName System.Runtime.WindowsRuntime
                
                # Define function to convert Windows Runtime tasks to .NET Tasks
                $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
                Function Await($WinRtTask, $ResultType) {
                    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                    $netTask = $asTask.Invoke($null, @($WinRtTask))
                    $netTask.Wait(-1) | Out-Null
                    $netTask.Result
                }
                
                # Get profile and manager
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) {
                    $manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    $result = Await ($manager.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
                    Write-Output "SUCCESS"
                } else { Write-Output "ERROR: No internet connection" }
            } catch { Write-Output "ERROR: $($_.Exception.Message)" }
            """
            
            result = subprocess.run(["powershell", "-Command", cmd], 
                                  capture_output=True, text=True, timeout=Constants.PROCESS_TIMEOUT)
            
            if result.returncode == 0 and "SUCCESS" in result.stdout:
                self._invalidate_cache()
                self.logger.info("✅ Mobile hotspot disabled successfully")
                return True
            else:
                raise HotspotError(f"Failed to disable hotspot: {result.stdout}")
                
        except subprocess.TimeoutExpired:
            raise HotspotError("Hotspot disable operation timed out")
    
    def _invalidate_cache(self) -> None:
        """Invalidate status cache"""
        self._last_check_time = None
        self._last_status = None

# ================================= MAIN ORCHESTRATOR =================================

class WifiAutoConnector:
    """Main WiFi Auto-Connector orchestrator"""
    
    def __init__(self, config: WifiConfig):
        self.config = config
        self.logger = setup_logging()
        self.state = ConnectionState.DISCONNECTED
        self.consecutive_failures = 0
        self.last_mac_change_time: Optional[datetime] = None
        
        # Initialize managers
        self.network_manager = NetworkManager(self.logger, config)
        self.mac_manager = MacAddressManager(self.logger, config)
        self.browser_manager = BrowserManager(self.logger, config)
        self.hotspot_manager = HotspotManager(self.logger, config)
        
        # Setup shutdown handlers
        self._setup_shutdown_handlers()
    
    def _setup_shutdown_handlers(self) -> None:
        """Setup graceful shutdown handlers"""
        def shutdown_handler(signum, frame):
            self.logger.info("Received shutdown signal, cleaning up...")
            self._cleanup()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, shutdown_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, shutdown_handler)
        
        atexit.register(self._cleanup)
    
    def _cleanup(self) -> None:
        """Perform cleanup operations"""
        self.logger.info("🧹 Cleaning up...")
        try:
            self.browser_manager._cleanup_session()
            # Clean up any orphaned drivers
            subprocess.run(["taskkill", "/f", "/im", "msedgedriver.exe"], 
                         capture_output=True, timeout=5)
        except Exception:
            pass
    
    def run(self) -> None:
        """Main execution loop"""
        self.logger.info("🚀 Starting WiFi Auto-Connector...")
        
        # Initial system check
        self._check_system_requirements()
        
        try:
            # Main monitoring loop
            while True:
                self._display_status()
                
                if self.network_manager.check_internet_connection():
                    self._handle_connected_state()
                else:
                    self._handle_disconnected_state()
                
                self._sleep_with_status()
                
        except KeyboardInterrupt:
            self.logger.info("Script interrupted by user")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            self._cleanup()
    
    def _check_system_requirements(self) -> None:
        """Check system requirements and capabilities"""
        # Check MAC spoofing capability
        if self.config.enable_mac_spoofing:
            if not self.mac_manager.is_tool_available():
                self.logger.warning("⚠️ MAC spoofing tool not found. MAC changing will be disabled.")
                self.config.enable_mac_spoofing = False
        
        # Check hotspot capability
        if self.config.enable_hotspot_sharing:
            if not self.hotspot_manager.is_admin():
                self.logger.warning("⚠️ Not running as administrator. Hotspot functionality will be limited.")
            elif not self.hotspot_manager.is_available():
                self.logger.warning("⚠️ Mobile hotspot not available on this system.")
            else:
                self.logger.info("✅ Mobile hotspot functionality available")
    
    def _display_status(self) -> None:
        """Display current system status"""
        os.system('cls' if os.name == 'nt' else 'clear')
        
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"--- WiFi Auto-Connector Status ({current_time}) ---")
        print(f"State: {self.state.value}")
        print(f"Consecutive failures: {self.consecutive_failures}")
        print(f"MAC spoofing: {'Available' if self.mac_manager.is_tool_available() else 'Unavailable'}")
        print(f"Running as admin: {'Yes' if self.hotspot_manager.is_admin() else 'No'}")
        
        if self.config.enable_hotspot_sharing:
            hotspot_status = "Enabled (Sharing)" if self.hotspot_manager.check_status() else "Disabled"
            print(f"Hotspot status: {hotspot_status}")
        
        print("-" * 50)
    
    def _handle_connected_state(self) -> None:
        """Handle connected state"""
        if self.state != ConnectionState.CONNECTED:
            self.logger.info("🎉 Internet connection restored!")
            self.state = ConnectionState.CONNECTED
            self.consecutive_failures = 0
            self.network_manager.clear_cache()
            
            # Enable hotspot sharing
            if (self.config.enable_hotspot_sharing and 
                self.config.auto_enable_hotspot and
                not self.hotspot_manager.check_status()):
                self._manage_hotspot(enable=True)
        
        # Maintain hotspot if configured
        if (self.config.keep_hotspot_always_on and 
            self.config.enable_hotspot_sharing and
            not self.hotspot_manager.check_status()):
            self._manage_hotspot(enable=True)
    
    def _handle_disconnected_state(self) -> None:
        """Handle disconnected state"""
        self.state = ConnectionState.DISCONNECTED
        self.consecutive_failures += 1
        
        self.logger.warning(f"Connection failure #{self.consecutive_failures}")
        
        # Disable hotspot if configured
        if (self.config.enable_hotspot_sharing and 
            self.config.disable_hotspot_on_wifi_loss and
            self.hotspot_manager.check_status()):
            self._manage_hotspot(enable=False)
        
        # Check if MAC change is needed
        if self._should_change_mac():
            if self._attempt_mac_change():
                return  # Skip login attempt after MAC change
        
        # Attempt login
        self._attempt_login()
    
    def _should_change_mac(self) -> bool:
        """Determine if MAC address should be changed"""
        if not self.config.enable_mac_spoofing:
            return False
        
        if not self.mac_manager.is_tool_available():
            return False
        
        if self.consecutive_failures < self.config.max_failures_before_mac_change:
            return False
        
        # Check cooldown
        if self.last_mac_change_time:
            elapsed = (datetime.now() - self.last_mac_change_time).total_seconds()
            if elapsed < self.config.mac_change_cooldown:
                return False
        
        return True
    
    def _attempt_mac_change(self) -> bool:
        """Attempt MAC address change"""
        self.state = ConnectionState.MAC_CHANGING
        
        try:
            success = self.mac_manager.change_mac_address()
            if success:
                self.consecutive_failures = 0
                self.last_mac_change_time = datetime.now()
                self.network_manager.clear_cache()
                return True
        except MacAddressError as e:
            self.logger.error(f"❌ MAC change failed: {e}")
            time.sleep(self.config.mac_change_cooldown)
        
        return False
    
    def _manage_hotspot(self, enable: bool) -> None:
        """Manage hotspot state"""
        if not self.config.enable_hotspot_sharing:
            return
        
        self.state = ConnectionState.HOTSPOT_MANAGING
        
        try:
            if enable:
                self.hotspot_manager.enable()
                self.logger.info("✅ Mobile hotspot enabled - WiFi connection is now shared!")
            else:
                self.hotspot_manager.disable()
                self.logger.info("✅ Mobile hotspot disabled")
        except HotspotError as e:
            self.logger.error(f"❌ Hotspot management failed: {e}")
    
    def _attempt_login(self) -> None:
        """Attempt captive portal login"""
        self.state = ConnectionState.RECOVERING
        
        result = self.browser_manager.perform_login()
        
        if result == LoginResult.SUCCESS:
            self.logger.info("✅ Login attempt completed")
            self.network_manager.clear_cache()
        else:
            self.logger.error(f"❌ Login attempt failed: {result.value}")
    
    def _sleep_with_status(self) -> None:
        """Sleep with status indication"""
        self.logger.info(f"⏳ Next check in {self.config.check_interval} seconds...")
        time.sleep(self.config.check_interval)

# ================================= MAIN EXECUTION =================================

def main():
    """Main application entry point"""
    try:
        # Load and validate configuration
        config = WifiConfig()
        config.validate()
        
        # Create and run connector
        connector = WifiAutoConnector(config)
        connector.run()
        
    except ConfigurationError as e:
        print(f"❌ Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
