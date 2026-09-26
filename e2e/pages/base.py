from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_TIMEOUT_SECONDS = 10


class BasePage:
    """Shared plumbing for page objects: a driver and an explicit-wait helper."""

    def __init__(self, driver: WebDriver):
        self.driver = driver

    def wait(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> WebDriverWait:
        return WebDriverWait(self.driver, timeout)
