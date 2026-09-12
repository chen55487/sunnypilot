#!/usr/bin/env python3
"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import math
import os
import platform
import signal
import sys
import threading
import time
import urllib.request
from datetime import datetime

try:
  from cereal import messaging
  from openpilot.common.gps import get_gps_location_service
  from openpilot.common.params import Params
  from openpilot.common.realtime import Ratekeeper
  from openpilot.common.swaglog import cloudlog
except ImportError:
  messaging = None
  get_gps_location_service = None
  Params = None
  Ratekeeper = None
  import logging
  cloudlog = logging.getLogger("cmsd")

DEFAULT_CMS_URL = "https://cms.tnchen.info/active_cms.json"
DEFAULT_ALERT_RADIUS = 800.0
DEFAULT_POLL_INTERVAL = 20.0
MAX_HISTORY_ITEMS = 10


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  """Calculate the great-circle distance between two coordinates in meters."""
  radius = 6371000.0  # Earth radius in meters
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  delta_phi = math.radians(lat2 - lat1)
  delta_lambda = math.radians(lon2 - lon1)

  a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
  c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
  return radius * c


def fetch_cms_json(url_str: str, api_key: str = "", timeout: float = 10.0) -> list[dict]:
  """Fetch active CMS data from server with optional x-api-key header."""
  if not url_str:
    return []

  req = urllib.request.Request(url_str)
  req.add_header("User-Agent", "sunnypilot-cms/1.0")

  if api_key and url_str.lower().startswith("https://"):
    req.add_header("x-api-key", api_key)

  with urllib.request.urlopen(req, timeout=timeout) as response:
    raw_data = response.read().decode("utf-8")
    return json.loads(raw_data)


class CmsDaemon:
  def __init__(self):
    self.params = Params()
    self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else self.params

    self._running = True
    self._cached_items: list[dict] = []
    self._items_lock = threading.Lock()
    self._last_fetch_time = 0.0

    self._last_alert_text: str | None = None
    self._alert_history: list[dict] = []

    # Load initial history from params if present
    try:
      history_raw = self.params.get("CmsAlertHistory")
      if history_raw:
        self._alert_history = json.loads(history_raw)
    except Exception:
      self._alert_history = []

  def _poll_worker(self):
    """Background worker thread that periodically fetches CMS data from server."""
    while self._running:
      try:
        enabled = self.params.get_bool("CmsAlertEnabled")
        if enabled:
          url = self.params.get("CmsAlertUrl") or DEFAULT_CMS_URL
          api_key = self.params.get("CmsApiKey") or ""

          items = fetch_cms_json(url, api_key)
          with self._items_lock:
            self._cached_items = items

          now_str = datetime.now().strftime("%H:%M:%S")
          status_msg = f"✅ Connected ({now_str})"
          self.mem_params.put("CmsFetchStatus", status_msg)
          self._last_fetch_time = time.monotonic()
      except Exception as e:
        cloudlog.warning(f"CMS fetch error: {e}")
        self.mem_params.put("CmsFetchStatus", "❌ Connection Failed")

      # Sleep in small increments to respond quickly to shutdown
      for _ in range(int(DEFAULT_POLL_INTERVAL * 2)):
        if not self._running:
          break
        time.sleep(0.5)

  def _add_alert_history(self, text: str, cms_id: str, type_str: str):
    """Add new alert to history if not duplicate of the latest entry."""
    now_ts = int(time.time())
    if self._alert_history and self._alert_history[0].get("text") == text:
      return

    entry = {
      "text": text,
      "cms_id": cms_id,
      "type": type_str,
      "timestamp": now_ts,
    }
    self._alert_history = [entry] + self._alert_history[:MAX_HISTORY_ITEMS - 1]
    try:
      self.mem_params.put("CmsAlertHistory", json.dumps(self._alert_history))
    except Exception:
      pass

  def _clear_active_cms(self):
    self.mem_params.put("CmsCurrentText", "")
    self.mem_params.put("CmsCurrentDist", "")
    self.mem_params.put("CmsCurrentType", "")
    self.mem_params.put("CmsCurrentId", "")

  def run(self):
    """Main daemon loop connecting to GPS and updating CMS proximity."""
    signal.signal(signal.SIGINT, self._handle_signal)
    signal.signal(signal.SIGTERM, self._handle_signal)

    # Start network fetch worker
    fetch_thread = threading.Thread(target=self._poll_worker, daemon=True)
    fetch_thread.start()

    gps_service = get_gps_location_service(self.params)
    sm = messaging.SubMaster([gps_service, "gpsLocationExternal", "gpsLocation"])

    rk = Ratekeeper(5, print_delay_threshold=None)  # 5 Hz update rate

    cloudlog.info("cmsd daemon started")

    while self._running:
      sm.update(0)

      enabled = self.params.get_bool("CmsAlertEnabled")
      if not enabled:
        self._clear_active_cms()
        rk.keep_time()
        continue

      # Retrieve current GPS location
      gps = None
      if sm.valid[gps_service]:
        gps = sm[gps_service]
      elif sm.valid["gpsLocationExternal"]:
        gps = sm["gpsLocationExternal"]
      elif sm.valid["gpsLocation"]:
        gps = sm["gpsLocation"]

      if gps is None or not (hasattr(gps, "latitude") and hasattr(gps, "longitude")):
        rk.keep_time()
        continue

      cur_lat = gps.latitude
      cur_lon = gps.longitude

      # Skip invalid / zero coordinates
      if abs(cur_lat) < 1e-4 and abs(cur_lon) < 1e-4:
        rk.keep_time()
        continue

      # Read configuration params
      try:
        radius_str = self.params.get("CmsAlertRadius")
        alert_radius = float(radius_str) if radius_str else DEFAULT_ALERT_RADIUS
      except Exception:
        alert_radius = DEFAULT_ALERT_RADIUS

      try:
        enabled_types_raw = self.params.get("CmsEnabledTypes")
        enabled_types = set(json.loads(enabled_types_raw)) if enabled_types_raw else {"7"}
      except Exception:
        enabled_types = {"7"}

      with self._items_lock:
        items = list(self._cached_items)

      closest_item = None
      closest_dist = float("inf")

      for item in items:
        try:
          type_str = str(item.get("type", ""))
          if enabled_types and type_str not in enabled_types:
            continue

          lat = float(item.get("lat", 0.0))
          lon = float(item.get("lon", 0.0))
          text = str(item.get("text", "")).strip()

          if not text:
            continue

          dist = haversine_distance(cur_lat, cur_lon, lat, lon)
          if dist <= alert_radius and dist < closest_dist:
            closest_dist = dist
            closest_item = item
        except (ValueError, TypeError):
          continue

      if closest_item is not None:
        text = str(closest_item.get("text", "")).strip()
        cms_id = str(closest_item.get("cms_id", ""))
        type_str = str(closest_item.get("type", ""))

        self.mem_params.put("CmsCurrentText", text)
        self.mem_params.put("CmsCurrentDist", str(int(closest_dist)))
        self.mem_params.put("CmsCurrentType", type_str)
        self.mem_params.put("CmsCurrentId", cms_id)

        if text != self._last_alert_text:
          self._last_alert_text = text
          self._add_alert_history(text, cms_id, type_str)
      else:
        self._clear_active_cms()
        self._last_alert_text = None

      rk.keep_time()

    self._clear_active_cms()
    cloudlog.info("cmsd daemon stopped")

  def _handle_signal(self, signum, frame):
    self._running = False


def main():
  daemon = CmsDaemon()
  daemon.run()


if __name__ == "__main__":
  main()
