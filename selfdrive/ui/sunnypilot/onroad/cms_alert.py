"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import os
import platform
import subprocess
import time
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget

CMS_TYPE_LABELS = {
  "1": "旅行時間",
  "2": "壅塞",
  "3": "事故",
  "4": "施工",
  "5": "停車",
  "6": "政令宣導",
  "7": "突發狀況",
}

ALERT_AUTO_HIDE_SECONDS = 10.0


class CmsAlertRenderer(Widget):
  def __init__(self):
    super().__init__()
    self._mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else ui_state.params
    self.font_bold = gui_app.font(FontWeight.BOLD)
    self.font_semi_bold = gui_app.font(FontWeight.SEMI_BOLD)
    self.font_regular = gui_app.font(FontWeight.NORMAL)

    self.current_text: str = ""
    self.current_dist: str = ""
    self.current_type: str = ""
    self.display_start_time: float = 0.0
    self.minimized: bool = False
    self.alert_rect: rl.Rectangle = rl.Rectangle(0, 0, 0, 0)
    self.active: bool = False

  def update(self):
    if ui_state.sm.recv_frame["carState"] < ui_state.started_frame:
      return

    enabled = ui_state.params.get_bool("CmsAlertEnabled")
    if not enabled:
      self.current_text = ""
      self.active = False
      return

    text = self._mem_params.get("CmsCurrentText") or ""
    dist = self._mem_params.get("CmsCurrentDist") or ""
    type_str = self._mem_params.get("CmsCurrentType") or ""

    if text:
      if text != self.current_text:
        self.current_text = text
        self.current_dist = dist
        self.current_type = type_str
        self.display_start_time = time.monotonic()
        self.minimized = False
        self.active = True

        # Check if category is muted (僅顯示)
        muted_raw = ui_state.params.get("CmsMutedTypes")
        try:
          muted_types = set(json.loads(muted_raw)) if muted_raw else set()
        except Exception:
          muted_types = set()

        if type_str not in muted_types:
          self._play_alert_sound()
      else:
        self.current_dist = dist
        self.current_type = type_str
        # Check auto-hide timer
        if not self.minimized and (time.monotonic() - self.display_start_time > ALERT_AUTO_HIDE_SECONDS):
          self.minimized = True
    else:
      self.current_text = ""
      self.active = False
      self.minimized = False

  def _play_alert_sound(self):
    try:
      sound_path = "/data/openpilot/selfdrive/assets/sounds/prompt.wav"
      if os.path.exists(sound_path):
        subprocess.Popen(["aplay", "-q", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
      pass

  def _handle_touch(self):
    """Allow user to tap the alert card to toggle minimized/dismissed state."""
    if not self.active:
      return

    if rl.is_mouse_button_pressed(rl.MouseButton.MOUSE_BUTTON_LEFT):
      mouse_pos = rl.get_mouse_position()
      if rl.check_collision_point_rec(mouse_pos, self.alert_rect):
        if not self.minimized:
          self.minimized = True
        else:
          # Re-expand for another 10 seconds if tapped while minimized
          self.minimized = False
          self.display_start_time = time.monotonic()

  def _render(self, rect: rl.Rectangle):
    if not self.active or not self.current_text:
      return

    self._handle_touch()

    # Determine Y offset based on whether RoadName is displayed at top
    road_name_offset = 70 if ui_state.road_name_toggle else 15
    y_pos = rect.y + road_name_offset

    type_label = CMS_TYPE_LABELS.get(self.current_type, "路況")
    dist_str = f"{self.current_dist}m" if self.current_dist else ""
    header_tag = f"CMS ‧ {type_label}" + (f" ({dist_str})" if dist_str else "")

    if self.minimized:
      self._render_minimized(rect, y_pos, header_tag)
    else:
      self._render_expanded(rect, y_pos, header_tag)

  def _render_minimized(self, rect: rl.Rectangle, y_pos: float, header_tag: str):
    """Render subtle minimized pill at top-center."""
    tag_font_size = 38
    sz = measure_text_cached(self.font_semi_bold, header_tag, tag_font_size)
    pill_width = sz.x + 48
    pill_height = 50

    card_rect = rl.Rectangle(rect.x + (rect.width - pill_width) / 2, y_pos, pill_width, pill_height)
    self.alert_rect = card_rect

    # Dark amber tinted pill
    rl.draw_rectangle_rounded(card_rect, 0.5, 10, rl.Color(20, 20, 24, 210))
    rl.draw_rectangle_rounded_lines_ex(card_rect, 0.5, 10, 2, rl.Color(245, 166, 35, 180))

    text_pos = rl.Vector2(card_rect.x + (card_rect.width - sz.x) / 2, card_rect.y + (card_rect.height - sz.y) / 2)
    rl.draw_text_ex(self.font_semi_bold, header_tag, text_pos, tag_font_size, 0, rl.Color(245, 166, 35, 240))

  def _render_expanded(self, rect: rl.Rectangle, y_pos: float, header_tag: str):
    """Render full high-visibility CMS alert card."""
    max_card_width = min(1100, int(rect.width - 120))
    content_width = max_card_width - 60

    font_size_text = 46
    lines = wrap_text(self.font_bold, self.current_text, font_size_text, content_width)
    if not lines:
      lines = [self.current_text]

    line_height = measure_text_cached(self.font_bold, "標", font_size_text).y
    total_text_height = len(lines) * line_height + (len(lines) - 1) * 8

    card_height = 55 + total_text_height + 25  # Header (55) + text body + bottom padding
    card_width = max_card_width
    card_rect = rl.Rectangle(rect.x + (rect.width - card_width) / 2, y_pos, card_width, card_height)
    self.alert_rect = card_rect

    # Outer glow / shadow and dark highway sign background
    rl.draw_rectangle_rounded(card_rect, 0.18, 12, rl.Color(16, 18, 22, 235))
    # Highway amber border
    rl.draw_rectangle_rounded_lines_ex(card_rect, 0.18, 12, 3, rl.Color(255, 179, 0, 240))

    # Header section: [CMS] badge + category/distance tag
    badge_rect = rl.Rectangle(card_rect.x + 24, card_rect.y + 14, 90, 36)
    rl.draw_rectangle_rounded(badge_rect, 0.3, 6, rl.Color(255, 160, 0, 255))
    badge_sz = measure_text_cached(self.font_bold, "CMS", 28)
    rl.draw_text_ex(
      self.font_bold,
      "CMS",
      rl.Vector2(badge_rect.x + (badge_rect.width - badge_sz.x) / 2, badge_rect.y + (badge_rect.height - badge_sz.y) / 2),
      28,
      0,
      rl.Color(0, 0, 0, 255),
    )

    # Sub-header text (category and distance)
    sub_text = f"{header_tag}"
    sub_sz = measure_text_cached(self.font_semi_bold, sub_text, 32)
    rl.draw_text_ex(
      self.font_semi_bold,
      sub_text,
      rl.Vector2(badge_rect.x + badge_rect.width + 16, card_rect.y + 16),
      32,
      0,
      rl.Color(255, 210, 100, 230),
    )

    # Separator line
    rl.draw_line_ex(
      rl.Vector2(card_rect.x + 20, card_rect.y + 56),
      rl.Vector2(card_rect.x + card_rect.width - 20, card_rect.y + 56),
      1.5,
      rl.Color(255, 179, 0, 80),
    )

    # Render multiline CMS message body
    curr_y = card_rect.y + 68
    for line in lines:
      line_sz = measure_text_cached(self.font_bold, line, font_size_text)
      origin = rl.Vector2(card_rect.x + (card_rect.width - line_sz.x) / 2, curr_y)
      rl.draw_text_ex(self.font_bold, line, origin, font_size_text, 0, rl.Color(255, 255, 255, 255))
      curr_y += line_height + 8
