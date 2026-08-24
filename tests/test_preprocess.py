#!/usr/bin/env python3
"""Unit tests for oddbeaker_tts.preprocess (ported from jobeai tests/test_tts_units.py)."""

from oddbeaker_tts.preprocess import (
    build_spoken_text,
    clean_line_for_speech,
    expand_units,
)


def test_currency_percent():
    assert expand_units("costs $5") == "costs 5 dollars"
    assert expand_units("$1.99 each") == "1.99 dollars each"
    assert expand_units("80% humidity") == "80 percent humidity"
    assert expand_units("99.9% uptime") == "99.9 percent uptime"


def test_temperature():
    assert expand_units("56°F") == "56 degrees Fahrenheit"
    assert expand_units("20°C") == "20 degrees Celsius"
    assert expand_units("boil at 100°") == "boil at 100 degrees"
    assert expand_units("56 °F") == "56 degrees Fahrenheit"
    assert expand_units("98.6°F") == "98.6 degrees Fahrenheit"


def test_volume():
    assert expand_units("8 fl oz") == "8 fluid ounces"
    assert expand_units("8 fl. oz.") == "8 fluid ounces"
    assert expand_units("2 tbsp butter") == "2 tablespoons butter"
    assert expand_units("1 tsp salt") == "1 teaspoons salt"
    assert expand_units("250 mL") == "250 milliliters"
    assert expand_units("250 ml") == "250 milliliters"
    assert expand_units("1 gal milk") == "1 gallons milk"
    assert expand_units("2 qt water") == "2 quarts water"
    assert expand_units("2 L water") == "2 liters water"
    assert expand_units("8 fl oz juice") == "8 fluid ounces juice"


def test_weight():
    assert expand_units("500 mg") == "500 milligrams"
    assert expand_units("2 kg flour") == "2 kilograms flour"
    assert expand_units("10 lbs") == "10 pounds"
    assert expand_units("10 lb turkey") == "10 pounds turkey"
    assert expand_units("6 oz chicken") == "6 ounces chicken"
    assert expand_units("200 g sugar") == "200 grams sugar"
    assert expand_units("1.5 g protein") == "1.5 grams protein"


def test_length():
    assert expand_units("1200 sq ft") == "1200 square feet"
    assert expand_units("50 sq m") == "50 square meters"
    assert expand_units("65 mph") == "65 miles per hour"
    assert expand_units("100 km/h") == "100 kilometers per hour"
    assert expand_units("100 kph") == "100 kilometers per hour"
    assert expand_units("3 mm gap") == "3 millimeters gap"
    assert expand_units("30 cm") == "30 centimeters"
    assert expand_units("5 km away") == "5 kilometers away"
    assert expand_units("6 ft tall") == "6 feet tall"
    assert expand_units("1.5 ft") == "1.5 feet"
    assert expand_units('12"') == "12 inches"
    assert expand_units("5'") == "5 feet"
    assert expand_units('5\'10"') == "5 feet 10 inches"
    assert expand_units("14 in pipe") == "14 inches pipe"
    assert expand_units("3 mi trail") == "3 miles trail"
    assert expand_units("10 yd") == "10 yards"
    assert expand_units("100 m sprint") == "100 meters sprint"
    assert expand_units("5 km") == "5 kilometers"
    assert expand_units("3 mm") == "3 millimeters"


def test_file_sizes():
    assert expand_units("256 GB") == "256 gigabytes"
    assert expand_units("512 MB") == "512 megabytes"
    assert expand_units("128 KB") == "128 kilobytes"
    assert expand_units("2 TB") == "2 terabytes"


def test_no_false_positives():
    assert expand_units("put it in the box") == "put it in the box"
    assert expand_units("call them") == "call them"
    assert expand_units("going home") == "going home"
    assert expand_units("this is a good point") == "this is a good point"
    assert expand_units("Look at that") == "Look at that"
    assert expand_units("10 in the box") == "10 in the box"
    assert expand_units("5 in a row") == "5 in a row"


def test_multiple_units():
    got = expand_units(
        "Heat to 375°F and add 2 tbsp butter and 1 cup (8 fl oz) milk"
    )
    assert got == (
        "Heat to 375 degrees Fahrenheit and add 2 tablespoons butter "
        "and 1 cup (8 fluid ounces) milk"
    )


def test_clean_line_integration():
    assert (
        clean_line_for_speech("**Temperature:** 56°F")
        == "Temperature: 56 degrees Fahrenheit"
    )
    assert (
        clean_line_for_speech("Set oven to 375°F for 30 min.")
        == "Set oven to 375 degrees Fahrenheit for 30 min."
    )


def test_build_spoken_code_and_list():
    text = "Intro\n\n```python\nprint(1)\n```\n\n- one\n- two\n- three\n- four"
    spoken = build_spoken_text(text)
    assert spoken is not None
    assert "code snippet" in spoken.lower()
    assert "4 items" in spoken or "four" in spoken.lower() or "one" in spoken.lower()


def test_build_spoken_emptyish():
    assert build_spoken_text("```\nonly code\n```") is not None
