from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from pages.game import GamePage
from pages.reveal import RevealPage

ROUND_SECTION = "//h2[starts-with(normalize-space(.), 'Guess the')]/ancestor::section"


class RoundPage(GamePage):
    HEADING = (By.XPATH, "//h2[starts-with(normalize-space(.), 'Guess the')]")
    ALBUM_BUTTONS = (By.XPATH, f"{ROUND_SECTION}//ul//button")
    WRONG_GUESS_LINE = (By.XPATH, "//p[contains(., 'wrong guess')]")
    GIVE_UP_BUTTON = (By.XPATH, "//button[starts-with(normalize-space(.), 'Give up')]")

    def wait_until_loaded(self) -> "RoundPage":
        self.wait().until(EC.visibility_of_element_located(self.HEADING))
        return self

    def heading(self) -> str:
        return self.driver.find_element(*self.HEADING).text

    def album_options(self) -> list[str]:
        return self.texts(self.ALBUM_BUTTONS)

    def guess(self, album_name: str) -> None:
        self.click_by_text(self.ALBUM_BUTTONS, album_name, "album option")

    def guess_wrong(self, album_name: str) -> None:
        """Guess an album expected to be wrong and wait until it is eliminated."""
        self.guess(album_name)
        self.wait_until_eliminated(album_name)

    def guess_correct(self, album_name: str) -> RevealPage:
        self.guess(album_name)
        return RevealPage(self.driver).wait_until_loaded()

    def wait_until_eliminated(self, album_name: str) -> None:
        self.wait().until(lambda _: album_name not in self.album_options())

    def wrong_guess_line(self) -> str:
        return self.retry_on_stale(
            lambda: self.wait().until(EC.visibility_of_element_located(self.WRONG_GUESS_LINE)).text
        )

    def give_up(self) -> RevealPage:
        self.driver.find_element(*self.GIVE_UP_BUTTON).click()
        return RevealPage(self.driver).wait_until_loaded()
