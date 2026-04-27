import time
import unicodedata

from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


PROMOTORA_CAMPAIGN_TEXT = "56 | PROMOTORA DE INVERSIONES Y COBRANZA V2 |"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _text_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", _normalize_text(text))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.casefold()


def _scroll_to_center(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        element,
    )
    time.sleep(0.3)


def click_element(driver, element, desc: str = "elemento"):
    _scroll_to_center(driver, element)
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)
    print(f"[CLICK] {desc}.")
    return element


def _wait_until_table_has_real_rows(driver, table_body_id: str, timeout: int = 30):
    wait = WebDriverWait(driver, timeout)
    rows_xpath = f'//*[@id="{table_body_id}"]/tr'

    def has_real_rows(_driver):
        rows = _driver.find_elements(By.XPATH, rows_xpath)
        for row in rows:
            if not row.is_displayed():
                continue
            text = _normalize_text(row.text)
            if text and "No records found" not in text:
                return rows
        return False

    return wait.until(has_real_rows)


def _find_scroll_container(driver, element):
    return driver.execute_script(
        """
        let node = arguments[0];
        while (node) {
            const style = window.getComputedStyle(node);
            if ((style.overflowY === 'auto' || style.overflowY === 'scroll') &&
                node.scrollHeight > node.clientHeight) {
                return node;
            }
            node = node.parentElement;
        }
        return null;
        """,
        element,
    )


def click_campaign_group_by_text(
    driver,
    campaign_text: str = PROMOTORA_CAMPAIGN_TEXT,
    timeout: int = 30,
):
    """
    Busca la fila real de grupos de campanas por texto.
    Ignora el placeholder 'No records found' y recorre el scroll interno si existe.
    """
    table_body_id = "mainForm:dtGrupoCampanas_data"
    rows = _wait_until_table_has_real_rows(driver, table_body_id, timeout=timeout)
    scroll_container = _find_scroll_container(driver, rows[0])

    end_time = time.time() + timeout
    last_scroll_top = -1

    while time.time() < end_time:
        rows = driver.find_elements(By.XPATH, f'//*[@id="{table_body_id}"]/tr')
        for row in rows:
            text = _normalize_text(row.text)
            if not text or "No records found" in text:
                continue
            if campaign_text.casefold() in text.casefold():
                return click_element(driver, row, f"Grupo campana {campaign_text}")

        if scroll_container:
            scroll_top = driver.execute_script("return arguments[0].scrollTop;", scroll_container)
            scroll_height = driver.execute_script("return arguments[0].scrollHeight;", scroll_container)
            client_height = driver.execute_script("return arguments[0].clientHeight;", scroll_container)
            if scroll_top == last_scroll_top and scroll_top + client_height >= scroll_height:
                break
            last_scroll_top = scroll_top
            driver.execute_script(
                "arguments[0].scrollTop = Math.min(arguments[0].scrollTop + arguments[0].clientHeight, arguments[0].scrollHeight);",
                scroll_container,
            )
        else:
            driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.8));")
        time.sleep(0.6)

    raise TimeoutException(f"No se encontro la campana por texto: {campaign_text}")


def click_campaign_detail_arrow(driver, timeout: int = 30):
    wait = WebDriverWait(driver, timeout)
    icon = wait.until(
        EC.presence_of_element_located(
            (
                By.CSS_SELECTOR,
                "#mainForm\\:dtCampanas .ui-button-icon-left.ui-icon.ui-c.ui-icon-arrow-forward, "
                "#mainForm\\:dtCampanas .ui-icon-arrow-forward",
            )
        )
    )
    button = icon.find_element(By.XPATH, "./ancestor::*[self::button or self::a][1]")
    wait.until(lambda _driver: button.is_displayed() and button.is_enabled())
    return click_element(driver, button, "Detalle campana Promotora")


def click_by_visible_text(driver, texts, timeout: int = 30, desc: str = "elemento"):
    if isinstance(texts, str):
        texts = [texts]

    expected = [_text_key(text) for text in texts]
    wait = WebDriverWait(driver, timeout)
    candidate_xpath = "//*[self::a or self::button or self::span][normalize-space()]"

    def clickable_target(element):
        if element.tag_name.lower() in ("a", "button"):
            return element
        ancestors = element.find_elements(By.XPATH, "./ancestor::*[self::a or self::button][1]")
        return ancestors[0] if ancestors else element

    def find_candidate(_driver):
        visible = [
            item
            for item in _driver.find_elements(By.XPATH, candidate_xpath)
            if item.is_displayed() and item.is_enabled()
        ]

        for item in visible:
            if _text_key(item.text) in expected:
                return clickable_target(item)

        for item in visible:
            item_key = _text_key(item.text)
            if any(text in item_key for text in expected):
                return clickable_target(item)

        return False

    element = wait.until(find_candidate)
    return click_element(driver, element, desc)


def select_primefaces_option_by_text(
    driver,
    label_text: str,
    option_text: str,
    timeout: int = 30,
):
    wait = WebDriverWait(driver, timeout)
    normalized_label = _text_key(label_text)
    normalized_option = _text_key(option_text)

    all_labels_xpath = (
        "//*[self::label or self::span]"
        "[contains(concat(' ', normalize-space(@class), ' '), ' ui-selectonemenu-label ')]"
    )

    def find_label(_driver):
        exact_labels = [
            item
            for item in _driver.find_elements(By.XPATH, all_labels_xpath)
            if item.is_displayed()
            and item.is_enabled()
            and _text_key(item.text) == normalized_label
        ]
        if exact_labels:
            return exact_labels[0]

        visible_labels = [
            item
            for item in _driver.find_elements(By.XPATH, all_labels_xpath)
            if item.is_displayed() and item.is_enabled()
        ]
        if len(visible_labels) == 1:
            return visible_labels[0]
        return False

    label = wait.until(find_label)
    click_element(driver, label, f"Selector {label_text}")

    option_xpath = "//li[contains(concat(' ', normalize-space(@class), ' '), ' ui-selectonemenu-item ')]"
    option = wait.until(
        lambda _driver: next(
            (
                item
                for item in _driver.find_elements(By.XPATH, option_xpath)
                if item.is_displayed()
                and item.is_enabled()
                and _text_key(item.text) == normalized_option
            ),
            False,
        )
    )
    return click_element(driver, option, f"Opcion {option_text}")
