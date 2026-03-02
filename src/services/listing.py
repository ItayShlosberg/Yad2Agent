"""Loads the listing JSON and formats it as a prompt-ready text block."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class ListingLoader:
    """Reads listing.json once and provides a formatted prompt section."""

    def __init__(self, listing_path: Path) -> None:
        self._data: dict[str, Any] = {}
        if listing_path.exists():
            self._data = json.loads(listing_path.read_text(encoding="utf-8"))
            log.info("Listing loaded from %s", listing_path)
        else:
            log.warning("Listing file not found: %s", listing_path)

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def format_for_prompt(self) -> str:
        """Convert the raw listing dict into a readable text block for the system prompt."""
        if not self._data:
            return "[No listing data loaded — answer property questions with 'I'll check and get back to you.']\n"

        lines: list[str] = []
        self._format_property(lines)
        self._format_amenities(lines)
        self._format_location(lines)
        self._format_pricing(lines)
        self._format_availability(lines)
        self._format_highlights(lines)
        self._format_issues(lines)
        self._format_owner_instructions(lines)
        return "\n".join(lines)

    # ── Section formatters ─────────────────────────────────────────

    def _format_property(self, lines: list[str]) -> None:
        prop = self._data.get("property", {})
        if not prop:
            return
        lines.append("=== PROPERTY DETAILS (ground truth — use ONLY this data) ===")
        lines.append(f"Address: {prop.get('address', 'N/A')}")
        if prop.get("neighborhood_description"):
            lines.append(f"Neighborhood: {prop['neighborhood_description']}")
        lines.append(f"Type: {prop.get('type', 'N/A')}, {prop.get('building_type', '')}".rstrip(", "))
        lines.append(f"Rooms: {prop.get('rooms', 'N/A')} — {prop.get('rooms_breakdown', '')}")
        lines.append(f"Floor: {prop.get('floor', 'N/A')} out of {prop.get('total_floors', 'N/A')}")
        lines.append(f"Apartments per floor: {prop.get('apartments_per_floor', 'N/A')}")
        lines.append(f"Size: {prop.get('size_sqm', 'N/A')} sqm")

        if prop.get("balcony"):
            bal = f"yes, {prop.get('balcony_size_sqm', '')} sqm"
            if prop.get("balcony_view"):
                bal += f", view: {prop['balcony_view']}"
            lines.append(f"Balcony: {bal}")
        else:
            lines.append("Balcony: no")

        for key, label in [
            ("window_direction", "Window direction"),
            ("sun_exposure", "Sun exposure"),
            ("master_bedroom", "Master bedroom"),
        ]:
            if prop.get(key):
                lines.append(f"{label}: {prop[key]}")

        if prop.get("mamad"):
            lines.append(f"Mamad (safe room): yes — {prop.get('mamad_note', '')}")

        lines.append(f"Bathrooms: {prop.get('bathrooms', 'N/A')} — {prop.get('bathrooms_description', '')}")

        if prop.get("service_room"):
            lines.append(f"Service room: {prop.get('service_room_description', 'yes')}")

        if prop.get("parking"):
            lines.append(f"Parking: yes — {prop.get('parking_type', '')}, {prop.get('parking_spots', 1)} spot(s)")
        else:
            lines.append("Parking: no")

        if prop.get("storage_room"):
            lines.append(f"Storage room: yes, {prop.get('storage_room_size_sqm', '')} sqm, {prop.get('storage_room_location', '')}")
        else:
            lines.append("Storage room: no")

        lines.append(f"Elevator: {'yes' if prop.get('elevator') else 'no'}")

        for key, label in [
            ("heating_cooling", "AC/Heating"),
            ("water_heater", "Water heater"),
            ("ceiling_fans", "Ceiling fans"),
            ("pigeon_netting", "Pigeon netting"),
            ("tv_infrastructure", "TV infrastructure"),
        ]:
            if prop.get(key):
                lines.append(f"{label}: {prop[key]}")

        lines.append(f"Condition: {prop.get('condition', 'N/A')}")
        lines.append(f"Year built: {prop.get('year_built', 'N/A')}")

        if prop.get("arnona_monthly_ils"):
            lines.append(f"Arnona: {prop['arnona_monthly_ils']} ILS/month ({prop.get('arnona_bimonthly_ils', '')} ILS per two months)")
        if prop.get("vaad_bayit_monthly_ils"):
            lines.append(f"Vaad Bayit: {prop['vaad_bayit_monthly_ils']} ILS/month")

    def _format_amenities(self, lines: list[str]) -> None:
        amenities = self._data.get("building_amenities", {})
        if not amenities:
            return
        lines.append("\n=== BUILDING AMENITIES ===")
        for key, label in [("lobby", "Lobby"), ("intercom_video_entry", "Intercom / video entry system"),
                           ("trash_chute", "Trash chute"), ("bike_storage", "Bike storage")]:
            if amenities.get(key):
                lines.append(f"- {label}")
        if amenities.get("shabbat_elevator"):
            lines.append(f"- Shabbat elevator: {amenities['shabbat_elevator']}")
        if amenities.get("pets_allowed") is not None:
            lines.append(f"- Pets: {'allowed' if amenities['pets_allowed'] else 'not allowed'}")
        if amenities.get("sukkah_balcony_policy"):
            lines.append(f"- Sukkah policy: {amenities['sukkah_balcony_policy']}")
        else:
            lines.append("- Sukkah balcony policy: not known")

    def _format_location(self, lines: list[str]) -> None:
        location = self._data.get("location", {})
        if not location:
            return
        lines.append("\n=== LOCATION & PROXIMITY ===")
        for key, label in [("highway_access", "Highway"), ("distance_to_tel_aviv", "Tel Aviv"),
                           ("train_station", "Train"), ("schools", "Schools"),
                           ("shopping", "Shopping"), ("surroundings", "Surroundings")]:
            if location.get(key):
                lines.append(f"{label}: {location[key]}")

    def _format_pricing(self, lines: list[str]) -> None:
        pricing = self._data.get("pricing", {})
        if not pricing:
            return
        lines.append("\n=== PRICING ===")
        lines.append(f"Asking price: {pricing.get('asking_price', 'N/A'):,} {pricing.get('currency', 'ILS')}")
        if pricing.get("price_per_sqm"):
            lines.append(f"Price per sqm: {pricing['price_per_sqm']:,} {pricing.get('currency', 'ILS')}/sqm")
        includes = pricing.get("price_includes", [])
        if includes:
            lines.append(f"Price includes: {', '.join(includes)}")
        excludes = pricing.get("price_excludes", [])
        if excludes:
            lines.append(f"Price excludes: {', '.join(excludes)}")

    def _format_availability(self, lines: list[str]) -> None:
        avail = self._data.get("availability", {})
        if not avail:
            return
        lines.append("\n=== AVAILABILITY ===")
        lines.append(f"Status: {avail.get('status', 'N/A')}")
        if avail.get("available_from"):
            lines.append(f"Available from: {avail['available_from']}")
        lines.append(f"Flexible on date: {'yes' if avail.get('flexible_on_date') else 'no'}")
        if avail.get("reason_for_selling"):
            lines.append(f"Reason for selling: {avail['reason_for_selling']}")

    def _format_highlights(self, lines: list[str]) -> None:
        highlights = self._data.get("highlights", [])
        if not highlights:
            return
        lines.append("\n=== HIGHLIGHTS (mention naturally when relevant) ===")
        for h in highlights:
            lines.append(f"- {h}")

    def _format_issues(self, lines: list[str]) -> None:
        issues = self._data.get("known_issues", [])
        if not issues:
            return
        lines.append("\n=== KNOWN ISSUES (be honest if asked directly) ===")
        for issue in issues:
            lines.append(f"- {issue}")

    def _format_owner_instructions(self, lines: list[str]) -> None:
        owner = self._data.get("owner_instructions", {})
        if not owner:
            return
        lines.append("\n=== OWNER INSTRUCTIONS (follow strictly) ===")
        if owner.get("do_not_disclose"):
            lines.append(f"DO NOT DISCLOSE: {', '.join(owner['do_not_disclose'])}")
        if owner.get("emphasize"):
            lines.append(f"Emphasize: {', '.join(owner['emphasize'])}")
        if owner.get("visit_policy"):
            lines.append(f"Visit policy: {owner['visit_policy']}")
        if owner.get("negotiation_policy"):
            lines.append(f"Negotiation: {owner['negotiation_policy']}")
