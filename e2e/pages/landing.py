from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from pages.base import BasePage
from pages.round import RoundPage


class LandingPage(BasePage):
    ARTIST_INPUT = (By.CSS_SELECTOR, "input[aria-label='Artist name']")
    SUGGESTIONS = (By.CSS_SELECTOR, "[role='listbox'] [role='option']")
    START_BUTTON = (By.CSS_SELECTOR, "button[type='submit']")
    ERROR = (By.CSS_SELECTOR, "[role='alert']")

    def open(self, url: str) -> "LandingPage":
        self.driver.get(url)
        self.wait().until(EC.visibility_of_element_located(self.ARTIST_INPUT))
        return self

    def type_artist(self, text: str) -> None:
        field = self.driver.find_element(*self.ARTIST_INPUT)
        field.clear()
        field.send_keys(text)

    def suggestion_names(self) -> list[str]:
        self.wait().until(EC.presence_of_element_located(self.SUGGESTIONS))
        return [option.text for option in self.driver.find_elements(*self.SUGGESTIONS)]

    def choose_suggestion(self, name: str) -> RoundPage:
        self.suggestion_names()
        for option in self.driver.find_elements(*self.SUGGESTIONS):
            if option.text == name:
                option.click()
                break
        else:
            raise AssertionError(f"No suggestion named {name!r}")
        return RoundPage(self.driver).wait_until_loaded()

    def submit(self) -> None:
        self.driver.find_element(*self.START_BUTTON).click()

    def error_text(self) -> str:
        return self.wait().until(EC.visibility_of_element_located(self.ERROR)).text
