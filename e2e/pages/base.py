from collections.abc import Callable
from typing import TypeVar

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_TIMEOUT_SECONDS = 10
STALE_RETRIES = 3

T = TypeVar("T")


class BasePage:
    """shared plumbing for page objects a driver and an explicit wait helper"""

    def __init__(self, driver: WebDriver):
        self.driver = driver

    def wait(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> WebDriverWait:
        return WebDriverWait(self.driver, timeout)

    def retry_on_stale(self, action: Callable[[], T]) -> T:
        # react can re render and replace an element between finding it and using it
        for attempt in range(STALE_RETRIES):
            try:
                return action()
            except StaleElementReferenceException:
                if attempt == STALE_RETRIES - 1:
                    raise

    def texts(self, locator) -> list[str]:
        return self.retry_on_stale(
            lambda: [element.text for element in self.driver.find_elements(*locator)]
        )

    def click_by_text(self, locator, text: str, description: str) -> None:
        def click() -> bool:
            for element in self.driver.find_elements(*locator):
                if element.text == text:
                    element.click()
                    return True
            return False

        if not self.retry_on_stale(click):
            raise AssertionError(f"no {description} named {text!r}")
