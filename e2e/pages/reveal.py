from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from pages.game import GamePage


class RevealPage(GamePage):
    ALBUM_NAME = (By.CSS_SELECTOR, "main h2")
    TRACK_NAMES = (By.CSS_SELECTOR, "ol li span:last-child")
    TRACK_LIST = (By.CSS_SELECTOR, "ol li")

    def wait_until_loaded(self) -> "RevealPage":
        self.wait().until(EC.visibility_of_element_located(self.TRACK_LIST))
        return self

    def album_name(self) -> str:
        return self.driver.find_element(*self.ALBUM_NAME).text

    def track_names(self) -> list[str]:
        return self.texts(self.TRACK_NAMES)
