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
from typing import List, Optional
import requests
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ================================= CONSTANTS =================================

class Constants:
    """Application timing and configuration constants optimized for captive portal environments"""
    
    # Internet connectivity verification
    CONNECTIVITY_TEST_ENDPOINTS = ["https://www.google.com", "https://www.cloudflare.com"]
    CONNECTIVITY_CHECK_TIMEOUT = 10  # Balanced timeout for captive portal detection
    CONNECTIVITY_CACHE_DURATION = 10  # Cache results to avoid excessive network calls
    
    # Browser automation timings (tuned for captive portal response times)
    SELENIUM_OPERATION_TIMEOUT = 40  # Max time for captive portal page loads
    CAPTIVE_PORTAL_POPUP_TIMEOUT = 15  # Time to wait for dismissible popups
    PORTAL_INTERACTION_DELAY = 6  # Required delay between captive portal button clicks
    POST_LOGIN_VERIFICATION_WAIT = 10  # Time to wait after login before connectivity check
    
    # System process management
    SUBPROCESS_EXECUTION_TIMEOUT = 30  # Max time for system commands
    PRIVILEGE_CHECK_TIMEOUT = 5  # Quick timeout for admin rights verification
    NETWORK_ADAPTER_RESET_TIME = 15  # Time needed for MAC change to take effect
    
    # Mobile hotspot management (Windows API limitations)
    HOTSPOT_STATUS_CACHE_DURATION = 10  # Cache to avoid frequent Windows API calls
    HOTSPOT_STATE_TRANSITION_TIME = 3  # Time for hotspot enable/disable operations
    
    # Failure recovery strategy
    MAX_OPERATION_RETRIES = 3  # Retry limit for recoverable operations
    PROGRESSIVE_RETRY_DELAY = 2  # Base delay that increases with each retry

# ================================= CONFIGURATION =================================

@dataclass
class WifiConfig:
    """WiFi Auto-Connector configuration with captive portal and hotspot management settings"""
    # Browser automation setup
    edge_driver_path: str = field(default_factory=lambda: _find_edge_driver())
    
    # Captive portal navigation selectors (customize these for your specific portal)
    xpath_popup_remind_later: str = "//*[@id='remind-me']"
    xpath_button_1: str = "/html/body/main/div[1]/div[3]/div/div/div/div[1]/button"
    xpath_button_2: str = "//*[@id='connectToInternet']"
    
    # Connection monitoring and recovery behavior
    connectivity_check_interval: int = 10  # Seconds between connection status checks
    connection_failures_before_mac_reset: int = 3  # Failed attempts before trying MAC randomization
    mac_reset_cooldown_seconds: int = 300  # Minimum time between MAC address changes
    network_adapter_stabilization_time: int = 15  # Wait time after MAC change for network stack reset
    
    # Feature toggles for advanced functionality
    mac_spoofing_enabled: bool = True  # Randomize MAC to bypass device-based restrictions
    mobile_hotspot_enabled: bool = True  # Share connection via Windows mobile hotspot
    auto_enable_hotspot_on_connection: bool = True  # Start hotspot when internet is available
    persistent_hotspot_mode: bool = True  # Keep hotspot running continuously
    disable_hotspot_on_connection_loss: bool = True  # Stop hotspot when WiFi fails
    
    def validate(self) -> None:
        """Validate configuration and check for common setup issues"""
        if not Path(self.edge_driver_path).exists():
            raise ConfigurationError(f"Edge WebDriver not found at: {self.edge_driver_path}")
        
        # Detect placeholder values that need customization
        placeholder_indicators = ["DÁN_XPATH", "PLACEHOLDER", "CHANGE_ME"]
        xpath_fields = [self.xpath_button_1, self.xpath_button_2, self.xpath_popup_remind_later]
        
        for placeholder in placeholder_indicators:
            for xpath in xpath_fields:
                if placeholder in xpath:
                    raise ConfigurationError(f"XPath selector contains placeholder '{placeholder}' - please customize for your captive portal")

def _find_edge_driver() -> str:
    """Auto-detect Microsoft Edge WebDriver location across common installation paths"""
    candidate_paths = [
        os.path.join(os.getcwd(), "msedgedriver.exe"),  # Current directory
        os.path.join(os.path.expanduser("~"), "Desktop", "Edge_Driver", "msedgedriver.exe"),  # User desktop
        os.path.join(os.path.dirname(sys.executable), "Scripts", "msedgedriver.exe"),  # Python Scripts
        "msedgedriver.exe"  # System PATH
    ]
    
    for candidate_path in candidate_paths:
        if Path(candidate_path).exists():
            return candidate_path
    
    # Return default path as fallback (user must install driver here)
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
    """Setup application logging with colored output for better readability"""
    logger = logging.getLogger('wifi_connector')
    logger.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Use colored formatter for better visual distinction
    colored_formatter = ColoredFormatter(
        '%(asctime)s - %(levelname)s - %(message)s', 
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(colored_formatter)
    logger.addHandler(console_handler)
    
    return logger

# ================================= UTILITIES =================================

def retry_on_failure(retries: int = Constants.MAX_OPERATION_RETRIES, delay: float = Constants.PROGRESSIVE_RETRY_DELAY):
    """Decorator that retries failed operations with progressive backoff strategy"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < retries - 1:
                        # Progressive delay: 2s, 4s, 6s for attempts 1, 2, 3
                        time.sleep(delay * (attempt + 1))
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
    """Manages internet connectivity verification with intelligent caching"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._connectivity_cache_timestamp: Optional[datetime] = None
        self._cached_connectivity_status: Optional[bool] = None
    
    def verify_internet_connectivity(self) -> bool:
        """Check internet connectivity with caching to reduce network overhead"""
        # Return cached result if still valid
        if (self._connectivity_cache_timestamp and 
            datetime.now() - self._connectivity_cache_timestamp < timedelta(seconds=Constants.CONNECTIVITY_CACHE_DURATION)):
            return self._cached_connectivity_status or False
        
        self.logger.info("Verifying internet connectivity...")
        
        # Test multiple endpoints for reliability
        for test_endpoint in Constants.CONNECTIVITY_TEST_ENDPOINTS:
            try:
                response = requests.get(
                    test_endpoint,
                    timeout=Constants.CONNECTIVITY_CHECK_TIMEOUT,
                    headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}  # Bypass any caching
                )
                
                if response.status_code == 200:
                    self._update_cache(True)
                    self.logger.info("✅ Internet connectivity confirmed")
                    return True
                    
            except requests.RequestException:
                continue  # Try next endpoint
        
        self._update_cache(False)
        self.logger.warning("❌ No internet connectivity detected")
        return False
    
    def invalidate_connectivity_cache(self) -> None:
        """Force fresh connectivity check on next verification"""
        self._connectivity_cache_timestamp = None
        self._cached_connectivity_status = None
    
    def _update_cache(self, connectivity_status: bool) -> None:
        """Update connectivity cache with timestamp"""
        self._connectivity_cache_timestamp = datetime.now()
        self._cached_connectivity_status = connectivity_status

class MacAddressManager:
    """Manages network adapter MAC address randomization to bypass device-based restrictions"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._mac_spoofing_tool_path: Optional[str] = None
    
    def locate_mac_spoofing_tool(self) -> Optional[str]:
        """Locate spoof-mac executable across common Python installation paths"""
        if self._mac_spoofing_tool_path:
            return self._mac_spoofing_tool_path
        
        # Check Python Scripts directory (most common)
        system_scripts_path = os.path.join(
            os.path.dirname(sys.executable), "Scripts", "spoof-mac.exe"
        )
        if os.path.exists(system_scripts_path):
            self._mac_spoofing_tool_path = system_scripts_path
            return system_scripts_path
        
        # Check user-specific Python installation
        try:
            python_version = f"Python{sys.version_info.major}{sys.version_info.minor}"
            user_scripts_path = os.path.join(
                os.getenv('APPDATA'), "Python", python_version, "Scripts", "spoof-mac.exe"
            )
            if os.path.exists(user_scripts_path):
                self._mac_spoofing_tool_path = user_scripts_path
                return user_scripts_path
        except Exception:
            pass
        
        # Check for Python script version (development installation)
        try:
            user_python_script = os.path.join(
                os.getenv('APPDATA'), "Python", 
                f"Python{sys.version_info.major}{sys.version_info.minor}",
                "Scripts", "spoof-mac.py"
            )
            if os.path.exists(user_python_script):
                self._mac_spoofing_tool_path = user_python_script
                return user_python_script
        except Exception:
            pass
        
        return None
    
    def is_mac_spoofing_available(self) -> bool:
        """Check if MAC address spoofing capability is available"""
        return self.locate_mac_spoofing_tool() is not None
    
    def randomize_network_adapter_mac(self) -> bool:
        """Randomize WiFi adapter MAC address to bypass network device restrictions"""
        spoofing_tool_path = self.locate_mac_spoofing_tool()
        
        if not spoofing_tool_path:
            raise MacAddressError("spoof-mac tool not found. Install with: pip install spoof-mac")
        
        self.logger.info(f"🔄 Randomizing WiFi adapter MAC address using: {spoofing_tool_path}")
        
        # Construct command based on tool type
        if spoofing_tool_path.endswith(".py"):
            command = [sys.executable, spoofing_tool_path, "randomize", "wi-fi"]
        else:
            command = [spoofing_tool_path, "randomize", "wi-fi"]
        
        try:
            self.logger.debug(f"Executing: {' '.join(command)}")
            result = subprocess.run(
                command, 
                check=True, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            self.logger.info("✅ MAC address randomized successfully")
            self.logger.info(f"⏳ Waiting {self.config.network_adapter_stabilization_time}s for network adapter reset...")
            
            # Critical: Network stack needs time to reinitialize with new MAC
            time.sleep(self.config.network_adapter_stabilization_time)
            
            return True
            
        except subprocess.CalledProcessError as e:
            raise MacAddressError(f"MAC randomization failed: {e.stderr}")
        except Exception as e:
            raise MacAddressError(f"Unexpected MAC randomization error: {e}")

class BrowserManager:
    """Manages automated browser interactions for captive portal authentication"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self.driver: Optional[webdriver.Edge] = None
        self.spawned_browser_processes: List[int] = []
    
    @contextmanager
    def managed_browser_session(self):
        """Context manager for browser sessions with automatic cleanup"""
        initial_browser_pids = self._enumerate_browser_processes()
        
        try:
            self.driver = self._initialize_headless_browser()
            self._register_spawned_processes(initial_browser_pids)
            yield self.driver
        finally:
            self._cleanup_browser_session()
    
    def _initialize_headless_browser(self) -> webdriver.Edge:
        """Initialize optimized headless Edge browser for captive portal automation"""
        service = Service(executable_path=self.config.edge_driver_path)
        options = webdriver.EdgeOptions()
        
        # Performance optimizations for captive portal interaction
        options.add_argument("--headless")  # No GUI needed
        options.add_argument("--log-level=3")  # Suppress console noise
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Disable background processing that slows down automation
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        
        # Load strategy optimized for simple captive portals
        options.page_load_strategy = 'eager'
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_experimental_option('useAutomationExtension', False)
        
        return webdriver.Edge(service=service, options=options)
    
    def execute_captive_portal_login(self) -> LoginResult:
        """Execute the complete captive portal authentication flow"""
        try:
            with self.managed_browser_session() as driver:
                self.logger.info("🔐 Initiating captive portal authentication...")
                
                # Navigate to a non-HTTPS site to trigger captive portal redirect
                driver.get("http://neverssl.com")
                
                wait = WebDriverWait(driver, Constants.SELENIUM_OPERATION_TIMEOUT)
                
                # Handle any dismissible popups first
                self._dismiss_reminder_popup(driver)
                
                # Execute the portal navigation sequence
                self._navigate_captive_portal_flow(driver, wait)
                
                self.logger.info("✅ Captive portal authentication sequence completed")
                return LoginResult.SUCCESS
                
        except TimeoutException:
            self.logger.error("❌ Captive portal authentication timed out")
            return LoginResult.TIMEOUT
        except Exception as e:
            self.logger.error(f"❌ Captive portal authentication failed: {e}")
            return LoginResult.FAILED
    
    def _dismiss_reminder_popup(self, driver: webdriver.Edge) -> None:
        """Dismiss any reminder or promotional popups that may appear"""
        try:
            popup_wait = WebDriverWait(driver, Constants.CAPTIVE_PORTAL_POPUP_TIMEOUT)
            popup_button = popup_wait.until(
                EC.element_to_be_clickable((By.XPATH, self.config.xpath_popup_remind_later))
            )
            self.logger.info("Dismissing captive portal popup...")
            time.sleep(1)  # Brief pause for popup stability
            driver.execute_script("arguments[0].click();", popup_button)
            self.logger.info("✅ Popup dismissed successfully")
        except TimeoutException:
            self.logger.debug("No popup detected - proceeding with main flow")
    
    def _navigate_captive_portal_flow(self, driver: webdriver.Edge, wait: WebDriverWait) -> None:
        """Execute the two-step captive portal button sequence"""
        # Step 1: Click initial access button
        self.logger.info("Clicking initial access button...")
        button1 = wait.until(EC.element_to_be_clickable((By.XPATH, self.config.xpath_button_1)))
        driver.execute_script("arguments[0].click();", button1)
        self.logger.info("✅ Initial button clicked")
        
        # Critical delay: Many captive portals require time between interactions
        time.sleep(Constants.PORTAL_INTERACTION_DELAY)
        
        # Step 2: Click final connection button
        self.logger.info("Clicking connection confirmation button...")
        button2 = wait.until(EC.element_to_be_clickable((By.XPATH, self.config.xpath_button_2)))
        driver.execute_script("arguments[0].click();", button2)
        driver.execute_script("arguments[0].click();", button2)  # Double-click for reliability
        self.logger.info("✅ Connection button clicked")
        
        # Wait for connection establishment
        time.sleep(Constants.POST_LOGIN_VERIFICATION_WAIT)
    
    def _enumerate_browser_processes(self) -> List[int]:
        """Get current Edge browser process IDs for cleanup tracking"""
        try:
            result = subprocess.run(
                ["tasklist", "/fi", "imagename eq msedge.exe", "/fo", "csv"],
                capture_output=True, text=True, timeout=10
            )
            
            process_ids = []
            for line in result.stdout.split('\n')[1:]:  # Skip CSV header
                if line.strip():
                    csv_parts = line.split(',')
                    if len(csv_parts) >= 2:
                        pid_string = csv_parts[1].strip('"')
                        if pid_string.isdigit():
                            process_ids.append(int(pid_string))
            return process_ids
        except Exception:
            return []
    
    def _register_spawned_processes(self, initial_browser_pids: List[int]) -> None:
        """Track new browser processes for cleanup after automation"""
        current_pids = self._enumerate_browser_processes()
        newly_spawned_pids = [pid for pid in current_pids if pid not in initial_browser_pids]
        self.spawned_browser_processes.extend(newly_spawned_pids)
    
    def _cleanup_browser_session(self) -> None:
        """Clean up browser session and terminate spawned processes"""
        # Close WebDriver gracefully
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass  # Ignore errors during cleanup
            finally:
                self.driver = None
        
        # Force terminate any remaining browser processes
        for process_id in self.spawned_browser_processes:
            try:
                subprocess.run(["taskkill", "/f", "/pid", str(process_id)], 
                             capture_output=True, timeout=5)
            except Exception:
                pass  # Process may have already terminated
        self.spawned_browser_processes.clear()

class HotspotManager:
    """Manages Windows Mobile Hotspot for internet connection sharing"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._hotspot_status_cache_time: Optional[datetime] = None
        self._cached_hotspot_status: Optional[bool] = None
        self._administrator_privileges: Optional[bool] = None
    
    def has_administrator_privileges(self) -> bool:
        """Check if running with administrator privileges (required for hotspot control)"""
        if self._administrator_privileges is None:
            try:
                self._administrator_privileges = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except:
                self._administrator_privileges = False
        return self._administrator_privileges
    
    def is_hotspot_functionality_available(self) -> bool:
        """Check if Windows mobile hotspot functionality is available on this system"""
        if not self.has_administrator_privileges():
            return False
        
        try:
            # Test Windows Runtime hotspot API availability
            powershell_test_command = """
            try {
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) { 
                    [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    Write-Output "AVAILABLE"
                } else { exit 1 }
            } catch { exit 1 }
            """
            result = subprocess.run(["powershell", "-Command", powershell_test_command], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0 and "AVAILABLE" in result.stdout
        except Exception:
            return False
    
    def get_hotspot_status(self) -> bool:
        """Get mobile hotspot status with caching to reduce Windows API calls"""
        # Return cached status if still valid
        if (self._hotspot_status_cache_time and 
            datetime.now() - self._hotspot_status_cache_time < timedelta(seconds=Constants.HOTSPOT_STATUS_CACHE_DURATION)):
            return self._cached_hotspot_status or False
        
        return self._query_windows_hotspot_api()
    
    def get_hotspot_status_no_cache(self) -> bool:
        """Get mobile hotspot status without using cache (for critical checks)"""
        return self._query_windows_hotspot_api()
    
    def _query_windows_hotspot_api(self) -> bool:
        """Query Windows Runtime API for current hotspot operational state"""
        try:
            # Use Windows Runtime API to get tethering state
            powershell_status_command = '''
try {
    $profile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
    if ($profile) {
        $manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
        Write-Output $manager.TetheringOperationalState
    } else {
        Write-Output "0"
    }
} catch {
    Write-Output "0"
}
            '''
            
            result = subprocess.run(["powershell", "-Command", powershell_status_command], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                try:
                    api_output = result.stdout.strip()
                    self.logger.debug(f"Windows hotspot API output: '{api_output}'")
                    
                    # Handle both string and numeric responses from Windows API
                    if api_output.lower() == "on":
                        hotspot_active = True
                    elif api_output.lower() == "off":
                        hotspot_active = False
                    else:
                        # TetheringOperationalState enum: 0=Unknown, 1=Off, 2=On, 3=InTransition
                        operational_state = int(api_output)
                        hotspot_active = operational_state == 2
                    
                    self._update_hotspot_cache(hotspot_active)
                    self.logger.debug(f"Mobile hotspot status: {hotspot_active}")
                    return hotspot_active
                except ValueError:
                    self.logger.debug(f"Invalid Windows API response: '{result.stdout.strip()}'")
                    
        except subprocess.TimeoutExpired:
            self.logger.debug("Hotspot status query timed out")
        except Exception as e:
            self.logger.debug(f"Hotspot status query failed: {e}")
        
        self._update_hotspot_cache(False)
        return False
    
    def enable_mobile_hotspot(self) -> bool:
        """Enable Windows mobile hotspot for internet connection sharing"""
        if not self.has_administrator_privileges():
            raise HotspotError("Administrator privileges required for hotspot control")
        
        # Skip if hotspot is already active
        if self.get_hotspot_status():
            self.logger.info("🔥 Mobile hotspot already active")
            return True
        
        self.logger.info("🔥 Enabling mobile hotspot for connection sharing...")
        
        try:
            # Complex PowerShell command to enable hotspot via Windows Runtime API
            enable_hotspot_command = """
            try {
                # Load Windows Runtime assembly for async operations
                Add-Type -AssemblyName System.Runtime.WindowsRuntime
                
                # Helper function to await Windows Runtime async operations
                $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
                Function Await($WinRtTask, $ResultType) {
                    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                    $netTask = $asTask.Invoke($null, @($WinRtTask))
                    $netTask.Wait(-1) | Out-Null
                    $netTask.Result
                }
                
                # Get network profile and start tethering
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) {
                    $manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    $result = Await ($manager.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
                    Write-Output "SUCCESS"
                } else { Write-Output "ERROR: No internet connection profile available" }
            } catch { Write-Output "ERROR: $($_.Exception.Message)" }
            """
            
            result = subprocess.run(["powershell", "-Command", enable_hotspot_command], 
                                  capture_output=True, text=True, timeout=Constants.SUBPROCESS_EXECUTION_TIMEOUT)
            
            if result.returncode == 0 and "SUCCESS" in result.stdout:
                self._invalidate_hotspot_cache()
                time.sleep(Constants.HOTSPOT_STATE_TRANSITION_TIME)
                self.logger.info("✅ Mobile hotspot enabled - sharing internet connection")
                return True
            else:
                raise HotspotError(f"Hotspot enable operation failed: {result.stdout}")
                
        except subprocess.TimeoutExpired:
            raise HotspotError("Hotspot enable operation timed out")
    
    def disable_mobile_hotspot(self) -> bool:
        """Disable Windows mobile hotspot"""
        if not self.has_administrator_privileges():
            raise HotspotError("Administrator privileges required for hotspot control")
        
        # Skip if hotspot is already inactive
        if not self.get_hotspot_status():
            self.logger.info("🔥 Mobile hotspot already inactive")
            return True
        
        self.logger.info("🔥 Disabling mobile hotspot...")
        
        try:
            # PowerShell command to disable hotspot via Windows Runtime API
            disable_hotspot_command = """
            try {
                # Load Windows Runtime assembly for async operations
                Add-Type -AssemblyName System.Runtime.WindowsRuntime
                
                # Helper function to await Windows Runtime async operations
                $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
                Function Await($WinRtTask, $ResultType) {
                    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                    $netTask = $asTask.Invoke($null, @($WinRtTask))
                    $netTask.Wait(-1) | Out-Null
                    $netTask.Result
                }
                
                # Get network profile and stop tethering
                $profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                if ($profile) {
                    $manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]::CreateFromConnectionProfile($profile)
                    $result = Await ($manager.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
                    Write-Output "SUCCESS"
                } else { Write-Output "ERROR: No internet connection profile available" }
            } catch { Write-Output "ERROR: $($_.Exception.Message)" }
            """
            
            result = subprocess.run(["powershell", "-Command", disable_hotspot_command], 
                                  capture_output=True, text=True, timeout=Constants.SUBPROCESS_EXECUTION_TIMEOUT)
            
            if result.returncode == 0 and "SUCCESS" in result.stdout:
                self._invalidate_hotspot_cache()
                self.logger.info("✅ Mobile hotspot disabled")
                return True
            else:
                raise HotspotError(f"Hotspot disable operation failed: {result.stdout}")
                
        except subprocess.TimeoutExpired:
            raise HotspotError("Hotspot disable operation timed out")
    
    def _update_hotspot_cache(self, hotspot_status: bool) -> None:
        """Update hotspot status cache with current timestamp"""
        self._hotspot_status_cache_time = datetime.now()
        self._cached_hotspot_status = hotspot_status
    
    def _invalidate_hotspot_cache(self) -> None:
        """Force fresh hotspot status check on next query"""
        self._hotspot_status_cache_time = None
        self._cached_hotspot_status = None

# ================================= MAIN ORCHESTRATOR =================================

class WifiAutoConnector:
    """Main orchestrator for automated WiFi connection management with captive portal handling"""
    
    def __init__(self, config: WifiConfig):
        self.config = config
        self.logger = setup_logging()
        self.connection_state = ConnectionState.DISCONNECTED
        self.failed_connection_attempts = 0
        self.last_mac_reset_timestamp: Optional[datetime] = None
        
        # Initialize specialized managers
        self.network_manager = NetworkManager(self.logger, config)
        self.mac_manager = MacAddressManager(self.logger, config)
        self.browser_manager = BrowserManager(self.logger, config)
        self.hotspot_manager = HotspotManager(self.logger, config)
        
        # Setup graceful shutdown handling
        self._setup_shutdown_handlers()
    
    def _setup_shutdown_handlers(self) -> None:
        """Setup signal handlers for graceful application shutdown"""
        def shutdown_handler(signum, frame):
            self.logger.info("Received shutdown signal - performing cleanup...")
            self._perform_cleanup()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, shutdown_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, shutdown_handler)
        
        atexit.register(self._perform_cleanup)
    
    def _perform_cleanup(self) -> None:
        """Perform cleanup operations before shutdown"""
        self.logger.info("🧹 Performing application cleanup...")
        try:
            self.browser_manager._cleanup_browser_session()
            # Terminate any orphaned WebDriver processes
            subprocess.run(["taskkill", "/f", "/im", "msedgedriver.exe"], 
                         capture_output=True, timeout=5)
        except Exception:
            pass  # Ignore cleanup errors
    
    def run(self) -> None:
        """Main execution loop for continuous WiFi connection monitoring"""
        self.logger.info("🚀 Starting WiFi Auto-Connector with captive portal support...")
        
        # Verify system capabilities before starting
        self._verify_system_capabilities()
        
        try:
            # Continuous monitoring loop
            while True:
                self._display_current_status()
                
                if self.network_manager.verify_internet_connectivity():
                    self._process_successful_connection()
                else:
                    self._process_connection_failure()
                
                self._wait_for_next_check()
                
        except KeyboardInterrupt:
            self.logger.info("WiFi Auto-Connector stopped by user")
        except Exception as e:
            self.logger.error(f"Unexpected application error: {e}")
        finally:
            self._perform_cleanup()
    
    def _verify_system_capabilities(self) -> None:
        """Verify and report on available system capabilities"""
        # Check MAC spoofing availability
        if self.config.mac_spoofing_enabled:
            if not self.mac_manager.is_mac_spoofing_available():
                self.logger.warning("⚠️  MAC spoofing tool not found - feature disabled")
                self.logger.info("    Install with: pip install spoof-mac")
                self.config.mac_spoofing_enabled = False
        
        # Check mobile hotspot capability
        if self.config.mobile_hotspot_enabled:
            if not self.hotspot_manager.has_administrator_privileges():
                self.logger.warning("⚠️  Administrator privileges required for hotspot management")
            elif not self.hotspot_manager.is_hotspot_functionality_available():
                self.logger.warning("⚠️  Mobile hotspot not available on this system")
            else:
                self.logger.info("✅ Mobile hotspot functionality ready")
    
    def _display_current_status(self) -> None:
        """Display current system status and configuration"""
        os.system('cls' if os.name == 'nt' else 'clear')
        
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"--- WiFi Auto-Connector Status ({current_time}) ---")
        print(f"Connection State: {self.connection_state.value}")
        print(f"Failed Attempts: {self.failed_connection_attempts}")
        print(f"MAC Spoofing: {'Available' if self.mac_manager.is_mac_spoofing_available() else 'Unavailable'}")
        print(f"Admin Privileges: {'Yes' if self.hotspot_manager.has_administrator_privileges() else 'No'}")
        
        if self.config.mobile_hotspot_enabled:
            hotspot_status = "Active" if self.hotspot_manager.get_hotspot_status_no_cache() else "Inactive"
            print(f"Mobile Hotspot: {hotspot_status}")
        
        print("-" * 50)
    
    def _process_successful_connection(self) -> None:
        """Handle successful internet connection and manage hotspot sharing"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.logger.info("🎉 Internet connection established!")
            self.connection_state = ConnectionState.CONNECTED
            self.failed_connection_attempts = 0
            self.network_manager.invalidate_connectivity_cache()
        
        # Manage mobile hotspot for connection sharing
        if self.config.mobile_hotspot_enabled:
            should_activate_hotspot = (
                self.config.auto_enable_hotspot_on_connection or 
                self.config.persistent_hotspot_mode
            )
            
            if should_activate_hotspot and not self.hotspot_manager.get_hotspot_status():
                self._toggle_mobile_hotspot(enable=True)
    
    def _process_connection_failure(self) -> None:
        """Handle connection failure with escalating recovery strategies"""
        self.connection_state = ConnectionState.DISCONNECTED
        self.failed_connection_attempts += 1
        
        self.logger.warning(f"Connection failure #{self.failed_connection_attempts}")
        
        # Disable hotspot on connection loss if configured
        if (self.config.mobile_hotspot_enabled and 
            self.config.disable_hotspot_on_connection_loss and
            self.hotspot_manager.get_hotspot_status()):
            self._toggle_mobile_hotspot(enable=False)
        
        # Escalate to MAC address reset if repeated failures
        if self._should_reset_mac_address():
            if self._perform_mac_address_reset():
                return  # Skip captive portal login after MAC reset
        
        # Attempt captive portal authentication
        self._execute_portal_authentication()
    
    def _should_reset_mac_address(self) -> bool:
        """Determine if MAC address should be reset based on failure patterns"""
        if not self.config.mac_spoofing_enabled:
            return False
        
        if not self.mac_manager.is_mac_spoofing_available():
            return False
        
        if self.failed_connection_attempts < self.config.connection_failures_before_mac_reset:
            return False
        
        # Enforce cooldown period between MAC resets
        if self.last_mac_reset_timestamp:
            time_since_last_reset = (datetime.now() - self.last_mac_reset_timestamp).total_seconds()
            if time_since_last_reset < self.config.mac_reset_cooldown_seconds:
                return False
        
        return True
    
    def _perform_mac_address_reset(self) -> bool:
        """Perform MAC address randomization for bypassing network restrictions"""
        self.connection_state = ConnectionState.MAC_CHANGING
        
        try:
            success = self.mac_manager.randomize_network_adapter_mac()
            if success:
                self.failed_connection_attempts = 0
                self.last_mac_reset_timestamp = datetime.now()
                self.network_manager.invalidate_connectivity_cache()
                return True
        except MacAddressError as e:
            self.logger.error(f"❌ MAC address reset failed: {e}")
            # Apply cooldown even on failure to avoid rapid retry loops
            time.sleep(self.config.mac_reset_cooldown_seconds)
        
        return False
    
    def _toggle_mobile_hotspot(self, enable: bool) -> None:
        """Toggle mobile hotspot state for internet connection sharing"""
        if not self.config.mobile_hotspot_enabled:
            return
        
        self.connection_state = ConnectionState.HOTSPOT_MANAGING
        
        try:
            if enable:
                self.hotspot_manager.enable_mobile_hotspot()
                self.logger.info("🔥 Mobile hotspot activated - sharing WiFi connection")
            else:
                self.hotspot_manager.disable_mobile_hotspot()
                self.logger.info("🔥 Mobile hotspot deactivated")
        except HotspotError as e:
            self.logger.error(f"❌ Mobile hotspot operation failed: {e}")
    
    def _execute_portal_authentication(self) -> None:
        """Attempt captive portal authentication using browser automation"""
        self.connection_state = ConnectionState.RECOVERING
        
        login_result = self.browser_manager.execute_captive_portal_login()
        
        if login_result == LoginResult.SUCCESS:
            self.logger.info("✅ Captive portal authentication completed")
            self.network_manager.invalidate_connectivity_cache()
        else:
            self.logger.error(f"❌ Captive portal authentication failed: {login_result.value}")
    
    def _wait_for_next_check(self) -> None:
        """Wait for the configured interval before next connectivity check"""
        self.logger.info(f"⏳ Next connectivity check in {self.config.connectivity_check_interval} seconds...")
        time.sleep(self.config.connectivity_check_interval)

# ================================= MAIN EXECUTION =================================

def main():
    """Main application entry point with configuration validation and error handling"""
    try:
        # Initialize and validate configuration
        config = WifiConfig()
        config.validate()
        
        # Create and start the WiFi auto-connector
        wifi_connector = WifiAutoConnector(config)
        wifi_connector.run()
        
    except ConfigurationError as e:
        print(f"❌ Configuration Error: {e}")
        print("Please check your configuration and try again.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected Application Error: {e}")
        print("Please report this issue if it persists.")
        sys.exit(1)

if __name__ == "__main__":
    main()
