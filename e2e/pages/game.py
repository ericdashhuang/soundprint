from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from pages.base import BasePage


class GamePage(BasePage):
    """What the round and reveal screens have in common: the metric chart and
    the metric glossary."""

    CHART = (By.CSS_SELECTOR, "[data-testid='game-chart']")
    METRIC_TABS = (By.CSS_SELECTOR, "[role='tablist'][aria-label='Chart metric'] [role='tab']")
    GLOSSARY_TERMS = (By.CSS_SELECTOR, "aside[aria-label='Metric glossary'] dt")

    def chart_is_displayed(self) -> bool:
        return self.wait().until(EC.visibility_of_element_located(self.CHART)).is_displayed()

    def metric_tabs(self) -> list[str]:
        return self.texts(self.METRIC_TABS)

    def wait_for_metric_tabs(self, expected: list[str]) -> None:
        self.wait().until(lambda _: self.metric_tabs() == expected)

    def glossary(self) -> dict[str, bool]:
        """Maps each glossary term to whether it is still locked."""
        locked_badge = "Not yet revealed"
        terms = {}
        for text in self.texts(self.GLOSSARY_TERMS):
            terms[text.replace(locked_badge, "").strip()] = locked_badge in text
        return terms
