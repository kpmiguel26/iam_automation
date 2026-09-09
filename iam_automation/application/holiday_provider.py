"""Read public holiday suggestions from the configured external provider."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HolidayProviderError(ValueError):
    """Raised when a public-holiday provider cannot return usable data."""


def fetch_public_holidays(country_code: str, year: int) -> list[dict[str, object]]:
    """Fetch public holidays for one country/year from Nager.Date.

    The result is a suggestion for an administrator. It is never used live by
    rule evaluation; the caller persists a reviewed local calendar snapshot.
    """
    country_code = str(country_code or "").strip().upper()
    try:
        year = int(year)
    except (TypeError, ValueError) as exc:
        raise HolidayProviderError("Year must be a valid number.") from exc
    if len(country_code) != 2 or not country_code.isalpha():
        raise HolidayProviderError("Country code must be a two-letter ISO code, for example US or GT.")
    if year < 2000 or year > 2100:
        raise HolidayProviderError("Choose a year between 2000 and 2100.")

    base_url = os.getenv("NAGER_HOLIDAYS_URL", "https://date.nager.at/api/v3/PublicHolidays").rstrip("/")
    url = f"{base_url}/{year}/{country_code}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "IAM-Automation/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HolidayProviderError("The holiday provider could not be reached. Review the country/year and try again.") from exc
    if not isinstance(payload, list):
        raise HolidayProviderError("The holiday provider returned an unexpected response.")

    holidays: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("date"):
            continue
        holidays.append({
            "date": str(item["date"]),
            "label": str(item.get("localName") or item.get("name") or "Public holiday"),
            "source": "NAGER_DATE",
            "country": country_code,
            "year": year,
            "type": ", ".join(str(value) for value in (item.get("types") or []) if value),
            "observed_date": str(item.get("observedDate") or item.get("date")),
            "enabled": True,
        })
    if not holidays:
        raise HolidayProviderError("The holiday provider returned no holidays for that country and year.")
    return holidays
