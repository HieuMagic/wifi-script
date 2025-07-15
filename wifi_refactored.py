#!/usr/bin/env python3
"""
WiFi Auto-Connector - Refactored Version
Tự động kết nối WiFi với captive portal login và MAC address spoofing
"""

import logging
import os
import signal
import subprocess
import sys
import time
import atexit
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
import requests
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


# ================================= CONFIGURATION =================================

@dataclass
class WifiConfig:
    """Configuration for WiFi auto-connector"""
    edge_driver_path: str = r"C:\Users\Hieu\Desktop\Edge_Driver\msedgedriver.exe"
    xpath_popup_remind_later: str = "//*[@id='remind-me']"
    xpath_button_1: str = "/html/body/main/div[1]/div[3]/div/div/div/div[1]/button"
    xpath_button_2: str = "//*[@id='connectToInternet']"
    check_interval: int = 10
    max_failures_before_mac_change: int = 4
    mac_change_cooldown: int = 300  # 5 minutes
    browser_timeout: int = 40
    network_timeout: int = 10
    mac_stabilization_time: int = 15

    def validate(self) -> None:
        """Validate configuration"""
        if not os.path.exists(self.edge_driver_path):
            raise ConfigurationError(f"Edge driver not found: {self.edge_driver_path}")
        
        if "DÁN_XPATH" in (self.xpath_button_1, self.xpath_button_2, self.xpath_popup_remind_later):
            raise ConfigurationError("Please replace XPath placeholders with actual values")


# ================================= EXCEPTIONS =================================

class WifiConnectionError(Exception):
    """WiFi connection related errors"""
    pass


class MacAddressError(Exception):
    """MAC address management errors"""
    pass


class BrowserAutomationError(Exception):
    """Browser automation errors"""
    pass


class ConfigurationError(Exception):
    """Configuration validation errors"""
    pass


# ================================= ENUMS =================================

class ConnectionState(Enum):
    """Connection states"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECOVERING = "recovering"
    MAC_CHANGING = "mac_changing"


class LoginResult(Enum):
    """Login attempt results"""
    SUCCESS = "success"
    ERROR = "error"
    MAC_DETECTED = "mac_detected"


# ================================= LOGGING SETUP =================================

class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output"""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[92m',       # Green
        'WARNING': '\033[93m',    # Yellow
        'ERROR': '\033[91m',      # Red
        'CRITICAL': '\033[95m'    # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging() -> logging.Logger:
    """Setup logging configuration"""
    logger = logging.getLogger('wifi_connector')
    logger.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger


# ================================= UTILITY CLASSES =================================

class ProcessManager:
    """Manages Edge browser processes created by the script"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.created_processes: List[int] = []
    
    def get_edge_processes(self) -> List[int]:
        """Get list of current Edge process PIDs"""
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
        except Exception as e:
            self.logger.warning(f"Failed to get Edge processes: {e}")
            return []
    
    def track_new_processes(self, existing_pids: List[int]) -> None:
        """Track new processes created after browser launch"""
        current_pids = self.get_edge_processes()
        new_pids = [pid for pid in current_pids if pid not in existing_pids]
        
        if new_pids:
            self.created_processes.extend(new_pids)
            self.logger.debug(f"Tracking {len(new_pids)} new Edge processes: {new_pids}")
    
    def cleanup_script_processes(self) -> None:
        """Clean up processes created by this script"""
        if not self.created_processes:
            self.logger.debug("No script processes to clean up")
            return
        
        cleaned_count = 0
        for pid in self.created_processes:
            try:
                result = subprocess.run(
                    ["taskkill", "/f", "/pid", str(pid)],
                    capture_output=True, text=True, timeout=5
                )
                if "SUCCESS" in result.stdout:
                    cleaned_count += 1
            except Exception:
                pass
        
        if cleaned_count > 0:
            self.logger.info(f"Cleaned up {cleaned_count} script processes")
        
        self.created_processes.clear()
    
    def cleanup_orphaned_drivers(self) -> None:
        """Clean up orphaned Edge driver processes"""
        try:
            result = subprocess.run(
                ["taskkill", "/f", "/im", "msedgedriver.exe"],
                capture_output=True, text=True, timeout=5
            )
            if "SUCCESS" in result.stdout:
                self.logger.info("Cleaned up orphaned Edge drivers")
        except Exception as e:
            self.logger.warning(f"Failed to clean up Edge drivers: {e}")


class NetworkChecker:
    """Handles network connectivity checking"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig):
        self.logger = logger
        self.config = config
        self._last_check_time: Optional[datetime] = None
        self._last_check_result: Optional[bool] = None
        self._cache_duration = timedelta(seconds=5)
    
    def check_internet_connection(self) -> bool:
        """Check if internet connection is available"""
        # Use cache if recent check available
        if (self._last_check_time and 
            datetime.now() - self._last_check_time < self._cache_duration):
            return self._last_check_result
        
        self.logger.info("Checking internet connection...")
        
        try:
            headers = {
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(
                "https://www.google.com",
                timeout=self.config.network_timeout,
                headers=headers
            )
            
            is_connected = (response.status_code == 200 and 
                          '<title>Google</title>' in response.text)
            
            # Cache result
            self._last_check_time = datetime.now()
            self._last_check_result = is_connected
            
            if is_connected:
                self.logger.info("✅ Internet connection stable")
            else:
                self.logger.warning("❌ Blocked by captive portal")
            
            return is_connected
            
        except requests.RequestException as e:
            self.logger.warning(f"❌ No internet connection: {e}")
            self._last_check_time = datetime.now()
            self._last_check_result = False
            return False
    
    def clear_cache(self) -> None:
        """Clear connection check cache"""
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
        
        self.logger.info(f"Changing MAC address using: {spoof_mac_path}")
        
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
            
            self.logger.info("MAC address changed successfully")
            self.logger.info(f"Waiting {self.config.mac_stabilization_time}s for network stabilization...")
            time.sleep(self.config.mac_stabilization_time)
            
            return True
            
        except subprocess.CalledProcessError as e:
            raise MacAddressError(f"spoof-mac command failed: {e.stderr}")
        except Exception as e:
            raise MacAddressError(f"Unexpected error changing MAC: {e}")


class BrowserAutomator:
    """Handles browser automation for captive portal login"""
    
    def __init__(self, logger: logging.Logger, config: WifiConfig, process_manager: ProcessManager):
        self.logger = logger
        self.config = config
        self.process_manager = process_manager
        self.driver: Optional[webdriver.Edge] = None
    
    def setup_driver(self) -> webdriver.Edge:
        """Setup and return Edge WebDriver"""
        service = Service(executable_path=self.config.edge_driver_path)
        options = webdriver.EdgeOptions()
        
        # Configure options for headless and optimized performance
        options.add_argument("--headless")
        options.add_argument("--log-level=3")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
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
        existing_pids = self.process_manager.get_edge_processes()
        
        try:
            self.driver = self.setup_driver()
            self.process_manager.track_new_processes(existing_pids)
            
            self.logger.info("Starting browser automation...")
            self.driver.get("http://neverssl.com")
            
            wait = WebDriverWait(self.driver, self.config.browser_timeout)
            
            # Handle popup if present
            self._handle_popup(wait)
            
            # Click first button
            self.logger.info("Waiting for first button...")
            button1 = wait.until(
                EC.element_to_be_clickable((By.XPATH, self.config.xpath_button_1))
            )
            self.driver.execute_script("arguments[0].click();", button1)
            self.logger.info("✅ First button clicked")
            
            # Wait as required by the website
            self.logger.info("Waiting 6 seconds as required...")
            time.sleep(6)
            
            # Click second button
            self.logger.info("Waiting for second button...")
            button2 = wait.until(
                EC.element_to_be_clickable((By.XPATH, self.config.xpath_button_2))
            )
            self.driver.execute_script("arguments[0].click();", button2)
            self.logger.info("✅ Second button clicked")
            
            # Wait for connection
            self.logger.info("Waiting 10 seconds for connection...")
            time.sleep(10)
            
            self.logger.info("✅ Login sequence completed successfully")
            return LoginResult.SUCCESS
            
        except TimeoutException as e:
            self.logger.error(f"Timeout during browser automation: {e}")
            return LoginResult.ERROR
        except WebDriverException as e:
            self.logger.error(f"WebDriver error: {e}")
            return LoginResult.ERROR
        except Exception as e:
            self.logger.error(f"Unexpected error during login: {e}")
            return LoginResult.ERROR
        finally:
            self.close_driver()
    
    def _handle_popup(self, wait: WebDriverWait) -> None:
        """Handle popup if present"""
        try:
            popup_wait = WebDriverWait(self.driver, 15)
            remind_later_button = popup_wait.until(
                EC.element_to_be_clickable((By.XPATH, self.config.xpath_popup_remind_later))
            )
            self.logger.info("Found popup, dismissing...")
            time.sleep(1)  # Small delay to avoid timing issues
            self.driver.execute_script("arguments[0].click();", remind_later_button)
            self.logger.info("✅ Popup dismissed")
        except TimeoutException:
            self.logger.debug("No popup found, continuing...")
    
    def close_driver(self) -> None:
        """Safely close the WebDriver"""
        if self.driver:
            try:
                self.logger.debug("Closing browser...")
                self.driver.quit()
                self.logger.debug("Browser closed successfully")
            except Exception as e:
                self.logger.warning(f"Error closing browser: {e}")
                # Fallback to process cleanup
                self.process_manager.cleanup_script_processes()
            finally:
                self.driver = None


# ================================= MAIN ORCHESTRATOR =================================

class WifiAutoConnector:
    """Main class that orchestrates the WiFi auto-connection process"""
    
    def __init__(self, config: WifiConfig):
        self.config = config
        self.logger = setup_logging()
        self.state = ConnectionState.DISCONNECTED
        self.consecutive_failures = 0
        self.last_mac_change_time: Optional[datetime] = None
        
        # Initialize managers
        self.process_manager = ProcessManager(self.logger)
        self.network_checker = NetworkChecker(self.logger, config)
        self.mac_manager = MacAddressManager(self.logger, config)
        self.browser_automator = BrowserAutomator(self.logger, config, self.process_manager)
        
        # Setup signal handlers
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info("Received shutdown signal, cleaning up...")
            self.graceful_shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
        
        atexit.register(self.graceful_shutdown)
    
    def graceful_shutdown(self) -> None:
        """Perform graceful shutdown"""
        self.logger.info("🧹 Performing graceful shutdown...")
        self.process_manager.cleanup_script_processes()
        self.browser_automator.close_driver()
    
    def run(self) -> None:
        """Main execution loop"""
        self.logger.info("🚀 Starting WiFi Auto-Connector...")
        
        try:
            # Initial cleanup
            self.process_manager.cleanup_orphaned_drivers()
            
            # Validate MAC tool availability
            if not self.mac_manager.is_tool_available():
                self.logger.warning("⚠️ spoof-mac tool not found. MAC address changing will be unavailable.")
            
            # Main monitoring loop
            while True:
                self._clear_screen()
                self._display_status()
                
                if self.network_checker.check_internet_connection():
                    self._handle_connected_state()
                else:
                    self._handle_disconnected_state()
                
                self._sleep_with_status()
                
        except KeyboardInterrupt:
            self.logger.info("Script interrupted by user")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            self.graceful_shutdown()
    
    def _clear_screen(self) -> None:
        """Clear terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def _display_status(self) -> None:
        """Display current status"""
        print(f"--- WiFi Auto-Connector Status ({datetime.now().strftime('%H:%M:%S')}) ---")
        print(f"State: {self.state.value}")
        print(f"Consecutive failures: {self.consecutive_failures}")
        print(f"MAC tool available: {'Yes' if self.mac_manager.is_tool_available() else 'No'}")
        print("-" * 50)
    
    def _handle_connected_state(self) -> None:
        """Handle when internet connection is available"""
        if self.state != ConnectionState.CONNECTED:
            self.logger.info("🎉 Internet connection restored!")
            self.state = ConnectionState.CONNECTED
            self.consecutive_failures = 0
            self.network_checker.clear_cache()
    
    def _handle_disconnected_state(self) -> None:
        """Handle when internet connection is not available"""
        self.state = ConnectionState.DISCONNECTED
        self.consecutive_failures += 1
        
        self.logger.warning(f"Connection failure #{self.consecutive_failures}")
        
        # Check if MAC address change is needed
        if self._should_change_mac():
            if self._attempt_mac_change():
                return  # Skip login attempt after MAC change
        
        # Attempt login
        self._attempt_login()
    
    def _should_change_mac(self) -> bool:
        """Determine if MAC address should be changed"""
        if not self.mac_manager.is_tool_available():
            return False
        
        if self.consecutive_failures < self.config.max_failures_before_mac_change:
            return False
        
        # Check cooldown
        if self.last_mac_change_time:
            cooldown_elapsed = (datetime.now() - self.last_mac_change_time).total_seconds()
            if cooldown_elapsed < self.config.mac_change_cooldown:
                return False
        
        return True
    
    def _attempt_mac_change(self) -> bool:
        """Attempt to change MAC address"""
        self.state = ConnectionState.MAC_CHANGING
        self.logger.info("🔄 Attempting MAC address change...")
        
        try:
            success = self.mac_manager.change_mac_address()
            if success:
                self.consecutive_failures = 0
                self.last_mac_change_time = datetime.now()
                self.network_checker.clear_cache()
                self.logger.info("✅ MAC address changed successfully")
                return True
        except MacAddressError as e:
            self.logger.error(f"❌ MAC address change failed: {e}")
            self.logger.info(f"⏳ Waiting {self.config.mac_change_cooldown}s before retry...")
            time.sleep(self.config.mac_change_cooldown)
        
        return False
    
    def _attempt_login(self) -> None:
        """Attempt captive portal login"""
        self.state = ConnectionState.RECOVERING
        self.logger.info("🔐 Attempting captive portal login...")
        
        # Clean up any existing processes
        self.process_manager.cleanup_script_processes()
        
        # Perform login
        result = self.browser_automator.perform_login()
        
        if result == LoginResult.SUCCESS:
            self.logger.info("✅ Login attempt completed")
            self.network_checker.clear_cache()
        else:
            self.logger.error("❌ Login attempt failed")
    
    def _sleep_with_status(self) -> None:
        """Sleep with status indication"""
        self.logger.info(f"⏳ Next check in {self.config.check_interval} seconds...")
        time.sleep(self.config.check_interval)


# ================================= MAIN EXECUTION =================================

def main():
    """Main entry point"""
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
