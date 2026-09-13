"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import unittest
from sunnypilot.cms.cmsd import haversine_distance


class TestCmsLogic(unittest.TestCase):
  def test_haversine_distance_known_points(self):
    # Taipei 101: 25.033964, 121.564472
    # Taipei Main Station: 25.047761, 121.517042
    # Straight-line distance is ~5.02 km (5020m)
    dist = haversine_distance(25.033964, 121.564472, 25.047761, 121.517042)
    self.assertAlmostEqual(dist, 5020, delta=100)

  def test_haversine_zero_distance(self):
    dist = haversine_distance(25.0, 121.5, 25.0, 121.5)
    self.assertEqual(dist, 0.0)

  def test_haversine_short_distance(self):
    # Two points ~800m apart
    # 25.0000, 121.5000 to 25.0072, 121.5000 (~800m north)
    dist = haversine_distance(25.0, 121.5, 25.0072, 121.5)
    self.assertAlmostEqual(dist, 800.0, delta=20)

  def test_cms_filtering_and_radius(self):
    user_lat = 25.0500
    user_lon = 121.5000
    alert_radius = 800.0

    items = [
      {"cms_id": "CMS-01", "lat": 25.0520, "lon": 121.5000, "text": "國1北上 事故排除", "type": "3"}, # ~222m away
      {"cms_id": "CMS-02", "lat": 25.0550, "lon": 121.5000, "text": "國1北上 施工封閉", "type": "4"}, # ~555m away
      {"cms_id": "CMS-03", "lat": 25.0700, "lon": 121.5000, "text": "遠方 突發狀況", "type": "7"}, # ~2220m away
    ]

    # Scenario 1: Only type 7 enabled -> CMS-03 is type 7 but outside 800m -> None found
    enabled_types = {"7"}
    matches = []
    for item in items:
      if item["type"] in enabled_types:
        d = haversine_distance(user_lat, user_lon, item["lat"], item["lon"])
        if d <= alert_radius:
          matches.append((d, item))
    self.assertEqual(len(matches), 0)

    # Scenario 2: Types 3 and 4 enabled -> Both within radius, CMS-01 is closest
    enabled_types = {"3", "4"}
    matches = []
    for item in items:
      if item["type"] in enabled_types:
        d = haversine_distance(user_lat, user_lon, item["lat"], item["lon"])
        if d <= alert_radius:
          matches.append((d, item))
    matches.sort(key=lambda x: x[0])
    self.assertEqual(len(matches), 2)
    self.assertEqual(matches[0][1]["cms_id"], "CMS-01")
    self.assertEqual(matches[0][1]["text"], "國1北上 事故排除")

  def test_history_deduplication(self):
    history = []
    max_items = 10

    def add_history(text, cms_id, type_str, ts):
      if history and history[0].get("text") == text:
        return
      entry = {"text": text, "cms_id": cms_id, "type": type_str, "timestamp": ts}
      history.insert(0, entry)
      if len(history) > max_items:
        history.pop()

    # Add same alert multiple times
    add_history("事故已排除", "CMS-01", "3", 1000)
    add_history("事故已排除", "CMS-01", "3", 1005)
    add_history("事故已排除", "CMS-01", "3", 1010)
    self.assertEqual(len(history), 1)

    # Add different alert
    add_history("路段壅塞回堵5公里", "CMS-02", "2", 1020)
    self.assertEqual(len(history), 2)
    self.assertEqual(history[0]["text"], "路段壅塞回堵5公里")

  def test_fetch_cms_json_with_mock(self):
    from unittest.mock import patch, MagicMock
    from sunnypilot.cms.cmsd import fetch_cms_json
    import io

    sample_json = b'[{"cms_id":"TEST-1","lat":25.0,"lon":121.5,"text":"\xe6\xb8\xac\xe8\xa9\xa6","type":"7"}]'
    mock_response = MagicMock()
    mock_response.read.return_value = sample_json
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
      data = fetch_cms_json("https://example.com/cms.json", api_key="secret123")
      self.assertEqual(len(data), 1)
      self.assertEqual(data[0]["cms_id"], "TEST-1")
      self.assertEqual(data[0]["text"], "測試")
      self.assertEqual(data[0]["type"], "7")

      # Verify Request was configured with headers
      req = mock_urlopen.call_args[0][0]
      self.assertEqual(req.get_header("X-api-key"), "secret123")

  def test_fetch_cms_json_strips_key(self):
    from unittest.mock import patch, MagicMock
    from sunnypilot.cms.cmsd import fetch_cms_json

    mock_response = MagicMock()
    mock_response.read.return_value = b"[]"
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
      fetch_cms_json("  https://example.com/cms.json  ", api_key="  secret_token_abc  \n")
      req = mock_urlopen.call_args[0][0]
      self.assertEqual(req.full_url, "https://example.com/cms.json")
      self.assertEqual(req.get_header("X-api-key"), "secret_token_abc")

  def test_empty_or_malformed_items(self):
    user_lat = 25.0
    user_lon = 121.5
    items = [
      {},  # empty
      {"text": ""},  # empty text
      {"lat": "invalid", "lon": "invalid", "text": "error"},
      {"lat": 25.0001, "lon": 121.5001, "text": "   "},  # whitespace only
      {"lat": 25.0010, "lon": 121.5010, "text": "正常標誌", "type": "7"},
    ]

    valid_matches = []
    for item in items:
      try:
        lat = float(item.get("lat", 0.0))
        lon = float(item.get("lon", 0.0))
        text = str(item.get("text", "")).strip()
        if not text:
          continue
        dist = haversine_distance(user_lat, user_lon, lat, lon)
        if dist <= 800.0:
          valid_matches.append(item)
      except (ValueError, TypeError):
        continue

    self.assertEqual(len(valid_matches), 1)
    self.assertEqual(valid_matches[0]["text"], "正常標誌")


if __name__ == "__main__":
  unittest.main()
