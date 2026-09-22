"""What the weather is doing somewhere, and what it will do next.

This is AWORG's first installed Capability, and it is a small one on purpose.
It exists to be the proof that the thing works: a folder that AWORG does not
need, sitting in capabilities/ in the owner's home, loaded and called exactly
like a built-in tool. Delete the folder and the Resident loses the weather and
nothing else. That is the whole shape of a capability in one example.

It is also written the way an installed capability has to be written, and the
two differences from a built-in are both here:

    from aworg.tools.base import ...    absolute, because a folder in the
                                        home is not inside the package and
                                        has no `..` to reach up through

    httpx                               taken from what AWORG already
                                        depends on. A capability runs in
                                        AWORG's process, with AWORG's
                                        interpreter and AWORG's environment,
                                        so it may use what is there -- and
                                        anything that is not there, it has to
                                        bring with it.

Open-Meteo needs no API key and asks for nothing about the caller, which is
why it is the one used: a shipped example that wanted a credential would be
an example nobody could run.
"""

from __future__ import annotations

import httpx

from aworg.tools.base import ToolContext, ToolError, ToolResult


NAME = "get_weather"

DESCRIPTION = (
    "Look up the current weather and the forecast for a place, by name. "
    "Give a town, city, postcode or landmark -- 'Dayton, Ohio', 'Kyoto', "
    "'45402'. Returns conditions now and a day-by-day forecast."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "place": {
            "type": "string",
            "description": (
                "Where to look up. A town or city, optionally with a region "
                "or country to tell two of the same name apart."
            ),
        },
        "units": {
            "type": "string",
            "description": (
                "'metric' for Celsius and km/h, 'imperial' for Fahrenheit "
                "and mph. Defaults to metric."
            ),
        },
        "days": {
            "type": "integer",
            "description": (
                "How many days of forecast to include, 0 to 7. Defaults to 3. "
                "0 gives current conditions only."
            ),
        },
    },
    "required": ["place"],
}

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 20
MAX_DAYS = 7

#: WMO weather interpretation codes, which is what the forecast comes back
#: as. Written out rather than passed through as a number, because "code 61"
#: is not weather and a model asked to translate it will sometimes invent a
#: translation.
CONDITIONS = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "heavy freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "light snow showers", 86: "snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail",
    99: "thunderstorms with heavy hail",
}


async def run(
    context: ToolContext,
    place: str,
    units: str = "metric",
    days: int = 3,
) -> ToolResult:
    place = (place or "").strip()
    if not place:
        raise ToolError("get_weather needs a place to look up.")

    imperial = str(units).strip().lower() in ("imperial", "us", "f", "fahrenheit")
    degrees = "F" if imperial else "C"
    speed = "mph" if imperial else "km/h"
    days = max(0, min(int(days), MAX_DAYS))

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        found = await _geocode(client, place)
        weather = await _forecast(client, found, imperial, days)

    current = weather.get("current") or {}
    where = _describe_place(found)
    lines = [f"{where}  (local time {(current.get('time') or '?').replace('T', ' ')})"]
    lines.append(
        "Now: {temp}°{d}{feels}, {sky}, wind {wind} {s}, humidity {humidity}%".format(
            temp=_number(current.get("temperature_2m")),
            d=degrees,
            feels=(
                f" (feels like {_number(current.get('apparent_temperature'))}°{degrees})"
                if current.get("apparent_temperature") is not None else ""
            ),
            sky=CONDITIONS.get(current.get("weather_code"), "unknown conditions"),
            wind=_number(current.get("wind_speed_10m")),
            s=speed,
            humidity=_number(current.get("relative_humidity_2m")),
        )
    )

    daily = weather.get("daily") or {}
    dates = daily.get("time") or []
    if dates:
        lines.append("")
        for index, date in enumerate(dates):
            chance = _at(daily.get("precipitation_probability_max"), index)
            lines.append(
                "{date}  {sky:<22} {low} to {high}°{d}{rain}".format(
                    date=date,
                    sky=CONDITIONS.get(
                        _at(daily.get("weather_code"), index), "unknown"
                    ),
                    low=_number(_at(daily.get("temperature_2m_min"), index)),
                    high=_number(_at(daily.get("temperature_2m_max"), index)),
                    d=degrees,
                    rain=f"   {chance}% chance of precipitation"
                    if chance not in (None, "") else "",
                )
            )

    return ToolResult(
        text="\n".join(lines),
        # The whole answer, for an owner who opens the Activity. The tool
        # showed the model a readable summary; this is what it was made from.
        payload={"place": found, "weather": weather},
        summary="{temp}°{d}, {sky}".format(
            temp=_number(current.get("temperature_2m")),
            d=degrees,
            sky=CONDITIONS.get(current.get("weather_code"), "?"),
        ),
    )


async def _geocode(client: httpx.AsyncClient, place: str) -> dict:
    """Turn a place name into a point on the earth.

    Failures here are told in the words of the thing that failed. "No place
    called 'Daytn, Ohio'" is something a model can act on by spelling it
    again; a traceback is not.
    """
    try:
        response = await client.get(
            GEOCODE_URL,
            params={"name": place, "count": 1, "language": "en", "format": "json"},
        )
        response.raise_for_status()
        results = (response.json() or {}).get("results") or []
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the place lookup service: {exc}") from exc
    except ValueError as exc:
        raise ToolError(f"The place lookup service answered with nonsense: {exc}") from exc

    if not results:
        raise ToolError(
            f"No place called {place!r} was found. Try adding a region or "
            "country, or check the spelling."
        )
    return results[0]


async def _forecast(
    client: httpx.AsyncClient, found: dict, imperial: bool, days: int
) -> dict:
    params = {
        "latitude": found.get("latitude"),
        "longitude": found.get("longitude"),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "precipitation,weather_code,wind_speed_10m",
        "timezone": "auto",
    }
    if days:
        params["daily"] = ("weather_code,temperature_2m_max,temperature_2m_min,"
                           "precipitation_probability_max")
        params["forecast_days"] = days
    if imperial:
        params["temperature_unit"] = "fahrenheit"
        params["wind_speed_unit"] = "mph"
        params["precipitation_unit"] = "inch"

    try:
        response = await client.get(FORECAST_URL, params=params)
        response.raise_for_status()
        return response.json() or {}
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the weather service: {exc}") from exc
    except ValueError as exc:
        raise ToolError(f"The weather service answered with nonsense: {exc}") from exc


def _describe_place(found: dict) -> str:
    """Where it actually looked, which is not always where it was asked.

    A name matched loosely is the commonest way a weather answer is wrong,
    and the only defence is saying plainly which of the four Springfields
    this is.
    """
    parts = [found.get("name")]
    for key in ("admin1", "country"):
        value = found.get(key)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(part for part in parts if part)


def _at(values, index):
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _number(value) -> str:
    if value is None:
        return "?"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
